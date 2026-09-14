"""Chat methods exposed to the local Web UI."""

import asyncio
import json
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from time import time
from typing import Any
from uuid import UUID, uuid4

import asyncer
from claude_agent_sdk import (
    ClaudeSDKError,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from webview.errors import JavascriptException, WebViewException

from backend.chat import (
    ChatEffort,
    ChatEvent,
    ChatPermissionMode,
    ChatReply,
    ClaudeChatClient,
    ClaudeChatConfig,
    ClaudeChatHistory,
)
from backend.config.current import CurrentConfig
from backend.config.setting import ModelSiteConfig, Settings, default_project_folder
from backend.router.command import is_allowed_leading_slash

# 对话结束后 SDK 客户端保留时长：期间命令/技能请求与下一轮对话复用同一连接，超时自动关闭
CHAT_CLIENT_IDLE_SECONDS = 5 * 60


def _user_facing_error(error: ValidationError) -> ValueError:
    """Translate the first pydantic error into the message shown by the Web UI."""
    first = error.errors()[0]
    message = str(first["msg"])
    if message.startswith("Value error, "):
        message = message.removeprefix("Value error, ")
    else:
        message = f"参数 {first['loc'][0]} 无效"
    return ValueError(message)


def _validate_leading_slash(
    prompt: str,
    server_info: dict[str, Any],
) -> None:
    """Reject commands and skills not included in the runtime allowlist."""
    first_token = prompt.split(maxsplit=1)[0]
    if not first_token.startswith("/"):
        # 非斜杠开头的普通消息直接放行
        return
    name = first_token.removeprefix("/")
    if name and is_allowed_leading_slash(name, server_info):
        return
    # 未在白名单内的斜杠命令/技能一律拦截，避免误发给 SDK
    raise ValueError(f"不允许执行命令 {first_token}")


class _ChatMessageRequest(BaseModel):
    """Validate and normalize one send_chat_message payload from the Web UI."""

    model_config = ConfigDict(validate_default=True)

    prompt: str
    project_path: Path | None = None
    session_id: str | None = None
    effort: ChatEffort = "high"
    permission_mode: ChatPermissionMode = "default"

    @field_validator("prompt", mode="before")
    @classmethod
    def _validate_prompt(cls, value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("消息内容必须是字符串")
        normalized = value.strip()
        if not normalized:
            raise ValueError("消息内容不能为空")
        if len(normalized) > 500_000:
            raise ValueError("消息内容过长")
        return normalized

    @field_validator("project_path", mode="before")
    @classmethod
    def _validate_project_path(cls, value: object) -> Path:
        if value is None or value == "":
            return default_project_folder()
        if not isinstance(value, str):
            raise TypeError("项目路径必须是字符串")
        project = Path(value).resolve()
        if not project.is_dir():
            raise ValueError("选择的项目文件夹已不存在")
        return project

    @field_validator("session_id", mode="before")
    @classmethod
    def _validate_session_id(cls, value: object) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise TypeError("会话标识必须是字符串")
        try:
            return str(UUID(value))
        except ValueError as error:
            raise ValueError("会话标识无效") from error

    @field_validator("effort", mode="before")
    @classmethod
    def _validate_effort(cls, value: object) -> object:
        if not isinstance(value, str) or value not in {"low", "medium", "high", "max"}:
            raise ValueError("推理强度无效")
        return value

    @field_validator("permission_mode", mode="before")
    @classmethod
    def _validate_permission_mode(cls, value: object) -> object:
        permission_modes = {
            "default",
            "acceptEdits",
            "plan",
            "auto",
            "bypassPermissions",
        }
        if not isinstance(value, str) or value not in permission_modes:
            raise ValueError("权限模式无效")
        return value


class _ChatPermissionDecision(BaseModel):
    """Validate and normalize one respond_chat_permission payload from the Web UI."""

    permission_id: str
    allowed: bool
    answers: dict[str, str | list[str]] | None = None

    @field_validator("permission_id", mode="before")
    @classmethod
    def _validate_permission_id(cls, value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("权限请求标识必须是字符串")
        try:
            return str(UUID(value))
        except ValueError as error:
            raise ValueError("权限请求标识无效") from error

    @field_validator("allowed", mode="before")
    @classmethod
    def _validate_allowed(cls, value: object) -> bool:
        if type(value) is not bool:
            raise TypeError("权限决定必须是布尔值")
        return value

    @field_validator("answers", mode="before")
    @classmethod
    def _validate_answers(cls, value: object) -> dict[str, str | list[str]] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise TypeError("用户回答必须是对象")

        normalized: dict[str, str | list[str]] = {}
        for question, answer in value.items():
            if not isinstance(question, str) or not question.strip():
                raise ValueError("问题文本无效")
            if isinstance(answer, str):
                clean_answer = answer.strip()
                if not clean_answer:
                    raise ValueError("用户回答不能为空")
                normalized[question] = clean_answer
                continue
            if not isinstance(answer, list) or not answer:
                raise TypeError("用户回答必须是字符串或非空字符串列表")
            if any(not isinstance(item, str) or not item.strip() for item in answer):
                raise ValueError("多选回答不能包含空值")
            normalized[question] = [item.strip() for item in answer]
        return normalized


@dataclass(frozen=True)
class _PermissionDecision:
    """One user decision returned to the waiting SDK callback."""

    allowed: bool
    answers: dict[str, str | list[str]] | None = None


@dataclass
class _PendingPermission:
    """Context required to validate and resume one pending tool call."""

    tool_name: str
    input_data: dict[str, Any]
    future: asyncio.Future[_PermissionDecision]
    session_id: str | None = None


@dataclass
class _ActiveChat:
    """Session state retained while running and for a short idle period."""

    client: ClaudeChatClient
    # 本回合已产生的事件流，供断线重连的前端补拉
    events: list[ChatEvent]
    metadata: dict[str, object]
    running: bool = False
    cleanup_task: asyncio.Task[None] | None = None
    # 每次重新调度自增，用于让过期的清理任务失效
    cleanup_generation: int = 0


class ChatRouter:
    """Validate UI input and delegate agent turns to the chat library."""

    _window: Any | None = None

    def __init__(self) -> None:
        super().__init__()
        self._active_chats: dict[str, _ActiveChat] = {}
        self._history = ClaudeChatHistory()
        self._pending_permissions: dict[str, _PendingPermission] = {}

    async def send_chat_message(
        self,
        prompt: str,
        project_path: str | None = None,
        session_id: str | None = None,
        effort: str = "high",
        permission_mode: str = "default",
    ) -> ChatReply:
        """Run one turn, stream text events, and return the final response."""
        try:
            request = _ChatMessageRequest.model_validate(
                {
                    "prompt": prompt,
                    "project_path": project_path,
                    "session_id": session_id,
                    "effort": effort,
                    "permission_mode": permission_mode,
                }
            )
        except ValidationError as error:
            raise _user_facing_error(error) from error

        active_session_id = request.session_id or str(uuid4())
        is_new_session = not await asyncer.asyncify(self._history.has_session)(
            active_session_id
        )
        site, model_name = await asyncer.asyncify(self._get_current_provider)()
        config = ClaudeChatConfig(
            api_key=site.api_key,
            api_url=site.api_url,
            can_use_tool=partial(
                self._request_tool_permission,
                session_id=active_session_id,
            ),
            effort=request.effort,
            is_new_session=is_new_session,
            model=model_name,
            permission_mode=request.permission_mode,
            project=request.project_path,
            session_id=active_session_id,
        )
        client = self._get_or_create_chat_client(config)
        # 仅斜杠开头时才实时拉取 server info 做白名单校验，避免普通消息多一次请求
        first_token = request.prompt.split(maxsplit=1)[0]
        server_info = (
            await client.get_server_info() if first_token.startswith("/") else {}
        )
        _validate_leading_slash(request.prompt, server_info)

        active_chat = self._active_chats[active_session_id]
        if active_chat.running:
            raise RuntimeError("当前会话正在生成，请先停止后再发送")
        # 新一轮对话开始，取消空闲清理倒计时并刷新客户端配置
        if active_chat.cleanup_task is not None:
            active_chat.cleanup_task.cancel()
            active_chat.cleanup_task = None
        client.prepare(config)
        now = int(time() * 1000)
        title = " ".join(request.prompt.split()) or "未命名会话"
        active_chat.events.clear()
        active_chat.metadata = {
            "session_id": active_session_id,
            "title": title[:100],
            "project_path": str(request.project_path),
            "project_name": request.project_path.name,
            "last_modified": now,
            "created_at": active_chat.metadata.get("created_at", now),
            "prompt": request.prompt,
        }
        active_chat.running = True
        self._emit_chat_event(
            {"type": "session_started", "session_id": active_session_id},
            session_id=active_session_id,
        )

        try:
            reply = await client.send(
                request.prompt,
                on_event=partial(
                    self._emit_chat_event,
                    session_id=active_session_id,
                ),
            )
            self._emit_chat_event(
                {"type": "chat_complete", "reply": reply},
                session_id=active_session_id,
            )
            return reply
        except ClaudeSDKError as error:
            self._emit_chat_event(
                {"type": "chat_error", "message": str(error)},
                session_id=active_session_id,
            )
            raise RuntimeError(f"Claude SDK 请求失败：{error}") from error
        except Exception as error:
            self._emit_chat_event(
                {"type": "chat_error", "message": str(error)},
                session_id=active_session_id,
            )
            raise
        finally:
            # 回合结束（成功/失败/停止）后标记空闲，并启动保留期倒计时
            active_chat = self._active_chats.get(active_session_id)
            # 客户端可能已被新配置替换，仅当仍是同一实例时才更新状态
            if active_chat is not None and active_chat.client is client:
                active_chat.running = False
                self._schedule_client_cleanup(
                    active_session_id,
                    active_chat,
                )

    def _get_or_create_chat_client(
        self,
        config: ClaudeChatConfig,
    ) -> ClaudeChatClient:
        active_chat = self._active_chats.get(config.session_id)
        if active_chat is None:
            now = int(time() * 1000)
            active_chat = _ActiveChat(
                client=ClaudeChatClient(config),
                events=[],
                metadata={
                    "session_id": config.session_id,
                    "title": "未命名会话",
                    "project_path": str(config.project),
                    "project_name": config.project.name,
                    "last_modified": now,
                    "created_at": now,
                    "prompt": "",
                },
            )
            self._active_chats[config.session_id] = active_chat
        elif not active_chat.running:
            # 空闲复用时同步最新配置（站点/模型可能已切换）
            active_chat.client.prepare(config)
        self._schedule_client_cleanup(config.session_id, active_chat)
        return active_chat.client

    async def _get_chat_server_info(
        self,
        session_id: str,
    ) -> dict[str, Any]:
        normalized_session_id = self._normalize_optional_session_id(session_id)
        if normalized_session_id is None:
            raise ValueError("会话标识无效")

        project = default_project_folder()
        is_new_session = not await asyncer.asyncify(self._history.has_session)(
            normalized_session_id
        )
        if not is_new_session:
            # 已有会话沿用历史记录中的项目目录，保证技能/命令上下文一致
            history = await asyncer.asyncify(self._history.get_session)(
                normalized_session_id
            )
            history_path = history.get("project_path")
            if isinstance(history_path, str):
                candidate = Path(history_path).resolve()
                if candidate.is_dir():
                    project = candidate

        site, model_name = await asyncer.asyncify(self._get_current_provider)()
        config = ClaudeChatConfig(
            api_key=site.api_key,
            api_url=site.api_url,
            can_use_tool=partial(
                self._request_tool_permission,
                session_id=normalized_session_id,
            ),
            effort="high",
            is_new_session=is_new_session,
            model=model_name,
            permission_mode="default",
            project=project,
            session_id=normalized_session_id,
        )
        client = self._get_or_create_chat_client(config)
        try:
            return await client.get_server_info()
        finally:
            # 读取完毕后重新进入保留期倒计时（进行中的回合不受影响）
            active_chat = self._active_chats.get(normalized_session_id)
            if active_chat is not None and not active_chat.running:
                self._schedule_client_cleanup(
                    normalized_session_id,
                    active_chat,
                )

    def _schedule_client_cleanup(
        self,
        session_id: str,
        active_chat: _ActiveChat,
    ) -> None:
        """Close an idle session client after its five-minute grace period."""
        if active_chat.running:
            return
        if active_chat.cleanup_task is not None:
            active_chat.cleanup_task.cancel()
        # 递增代数：旧定时器触发时会因代数不匹配而自动放弃
        active_chat.cleanup_generation += 1
        generation = active_chat.cleanup_generation
        active_chat.cleanup_task = asyncio.create_task(
            self._expire_chat_client(
                session_id,
                active_chat.client,
                generation,
            ),
            name=f"expire-chat-{session_id[:8]}",
        )

    async def _expire_chat_client(
        self,
        session_id: str,
        client: ClaudeChatClient,
        generation: int,
    ) -> None:
        try:
            await asyncio.sleep(CHAT_CLIENT_IDLE_SECONDS)
        except asyncio.CancelledError:
            return
        active_chat = self._active_chats.get(session_id)
        # 客户端被替换、重新开始运行、或已有更新的定时任务时，放弃本次清理
        if (
            active_chat is None
            or active_chat.client is not client
            or active_chat.running
            or active_chat.cleanup_generation != generation
        ):
            return
        self._active_chats.pop(session_id)
        await client.close()

    async def _shutdown_chat_clients(self) -> None:
        """Close every retained session client during application shutdown."""
        active_chats = list(self._active_chats.values())
        self._active_chats.clear()
        for pending in self._pending_permissions.values():
            if not pending.future.done():
                pending.future.set_result(_PermissionDecision(allowed=False))
        for active_chat in active_chats:
            if active_chat.cleanup_task is not None:
                active_chat.cleanup_task.cancel()
        for active_chat in active_chats:
            await active_chat.client.close()

    async def list_chat_sessions(self) -> list[dict[str, object]]:
        """Return all Claude sessions for the workspace-grouped sidebar."""
        sessions = await asyncer.asyncify(self._history.list_sessions)()
        sessions_by_id = {str(session["session_id"]): session for session in sessions}
        for session_id, active_chat in self._active_chats.items():
            if not active_chat.running:
                continue
            active_summary = {
                key: value
                for key, value in active_chat.metadata.items()
                if key != "prompt"
            }
            persisted_summary = sessions_by_id.get(session_id)
            if persisted_summary is None:
                sessions_by_id[session_id] = active_summary
            else:
                sessions_by_id[session_id] = {
                    **persisted_summary,
                    "last_modified": active_summary["last_modified"],
                }
        return sorted(
            sessions_by_id.values(),
            key=lambda session: int(session["last_modified"]),
            reverse=True,
        )

    async def get_chat_session(self, session_id: str) -> dict[str, object]:
        """Load one Claude session and its user-visible message text."""
        normalized_session_id = self._normalize_optional_session_id(session_id)
        if normalized_session_id is None:
            raise ValueError("会话标识无效")
        try:
            return await asyncer.asyncify(self._history.get_session)(
                normalized_session_id
            )
        except ValueError:
            active_chat = self._active_chats.get(normalized_session_id)
            if active_chat is None or not active_chat.running:
                raise
            metadata = active_chat.metadata
            prompt = str(metadata["prompt"])
            return {
                **{
                    key: value
                    for key, value in metadata.items()
                    if key != "prompt"
                },
                "messages": [
                    {
                        "key": f"active-user-{normalized_session_id}",
                        "role": "user",
                        "content": prompt,
                    }
                ],
            }

    def get_active_chat(self, session_id: str) -> dict[str, object] | None:
        """Return buffered events while a chat turn is still running."""
        normalized_session_id = self._normalize_optional_session_id(session_id)
        if normalized_session_id is None:
            return None
        active_chat = self._active_chats.get(normalized_session_id)
        if active_chat is None or not active_chat.running:
            return None
        return {
            "session_id": normalized_session_id,
            "events": [dict(event) for event in active_chat.events],
        }

    async def stop_chat_message(self, session_id: str | None = None) -> bool:
        """Interrupt one active chat turn and release its permission prompts."""
        normalized_session_id = self._normalize_optional_session_id(session_id)
        if normalized_session_id is None:
            # 未指定会话时：无运行中会话返回 False，多个则要求前端明确指定
            running_chats = [
                (chat_session_id, active_chat)
                for chat_session_id, active_chat in self._active_chats.items()
                if active_chat.running
            ]
            if not running_chats:
                return False
            if len(running_chats) > 1:
                raise ValueError("存在多个正在生成的会话，请指定要停止的会话")
            normalized_session_id, active_chat = running_chats[0]
        else:
            active_chat = self._active_chats.get(normalized_session_id)
            if active_chat is None or not active_chat.running:
                return False
        client = active_chat.client

        # 停止时以"拒绝"释放该会话所有挂起的权限询问，避免 SDK 一直等待
        pending_decisions = [
            pending.future
            for pending in self._pending_permissions.values()
            if (
                pending.session_id == normalized_session_id
                and not pending.future.done()
            )
        ]
        for decision in pending_decisions:
            decision.set_result(_PermissionDecision(allowed=False))

        await client.request_stop()
        return True

    def respond_chat_permission(
        self,
        permission_id: str,
        allowed: bool,
        answers: dict[str, str | list[str]] | None = None,
    ) -> bool:
        """Resolve a pending SDK tool permission request from the Web UI."""
        try:
            decision = _ChatPermissionDecision.model_validate(
                {
                    "permission_id": permission_id,
                    "allowed": allowed,
                    "answers": answers,
                }
            )
        except ValidationError as error:
            raise _user_facing_error(error) from error

        pending = self._pending_permissions.get(decision.permission_id)
        if pending is None:
            return False
        normalized_answers = self._validate_tool_answers(pending, decision)
        future = pending.future
        if future.done():
            return False
        future.set_result(
            _PermissionDecision(
                allowed=decision.allowed,
                answers=normalized_answers,
            )
        )
        return True

    async def _request_tool_permission(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: ToolPermissionContext,
        *,
        session_id: str | None = None,
    ) -> PermissionResultAllow | PermissionResultDeny:
        """Pause a tool call until the matching Web UI request is answered."""
        permission_id = str(uuid4())
        decision = asyncio.get_running_loop().create_future()
        self._pending_permissions[permission_id] = _PendingPermission(
            tool_name=tool_name,
            input_data=input_data,
            future=decision,
            session_id=session_id,
        )

        event: ChatEvent = {
            "type": "permission_request",
            "permission_id": permission_id,
            "tool_name": tool_name,
            "input": input_data,
            "title": context.title or f"Claude 请求使用 {tool_name}",
            "display_name": context.display_name or tool_name,
            "description": (context.description or context.decision_reason or "此操作需要你的确认后才能继续。"),
            "blocked_path": context.blocked_path or "",
        }
        if not self._emit_chat_event(event, session_id=session_id):
            self._pending_permissions.pop(permission_id, None)
            return PermissionResultDeny(message="无法显示工具权限确认，已拒绝本次调用")

        try:
            response = await decision
        finally:
            self._pending_permissions.pop(permission_id, None)

        if response.allowed:
            if tool_name == "AskUserQuestion":
                return PermissionResultAllow(updated_input={**input_data, "answers": response.answers})
            return PermissionResultAllow()
        return PermissionResultDeny(message="用户已拒绝本次工具调用")

    @staticmethod
    def _validate_tool_answers(
        pending: _PendingPermission,
        decision: _ChatPermissionDecision,
    ) -> dict[str, str | list[str]] | None:
        """Require one non-empty answer for every AskUserQuestion item."""
        if pending.tool_name != "AskUserQuestion":
            if decision.answers is not None:
                raise ValueError("普通工具权限确认不能包含用户回答")
            return None
        if not decision.allowed:
            return None
        if decision.answers is None:
            raise ValueError("请回答全部问题后再提交")

        raw_questions = pending.input_data.get("questions")
        if not isinstance(raw_questions, list) or not raw_questions:
            raise ValueError("AskUserQuestion 问题数据无效")

        question_texts: list[str] = []
        for raw_question in raw_questions:
            if not isinstance(raw_question, dict):
                raise TypeError("AskUserQuestion 问题数据无效")
            question = raw_question.get("question")
            if not isinstance(question, str) or not question.strip():
                raise ValueError("AskUserQuestion 问题数据无效")
            question_texts.append(question)

        if len(question_texts) != len(set(question_texts)):
            raise ValueError("AskUserQuestion 包含重复问题")
        if set(decision.answers) != set(question_texts):
            raise ValueError("请回答全部问题后再提交")
        return decision.answers

    def _emit_chat_event(
        self,
        event: ChatEvent,
        *,
        session_id: str | None = None,
    ) -> bool:
        """Dispatch one structured progress event to the Web UI."""
        detail_event = {**event, "session_id": session_id} if session_id else event
        if session_id is not None:
            active_chat = self._active_chats.get(session_id)
            if active_chat is not None:
                detail_event = {
                    **detail_event,
                    "event_index": len(active_chat.events),
                }
                active_chat.events.append(detail_event)
        if self._window is None:
            return False

        detail = json.dumps(
            detail_event,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        script = f"window.dispatchEvent(new CustomEvent('xalling:chat-event',{{detail:{detail}}}));"
        try:
            self._window.evaluate_js(script)
        except (JavascriptException, WebViewException):
            # The native window may be closing while the SDK finishes a turn.
            return False
        return True

    @staticmethod
    def _normalize_optional_session_id(value: object) -> str | None:
        """Normalize an optional session UUID used to address a live client."""
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise TypeError("会话标识必须是字符串")
        try:
            return str(UUID(value))
        except ValueError as error:
            raise ValueError("会话标识无效") from error

    @staticmethod
    def _get_current_provider() -> tuple[ModelSiteConfig, str]:
        current = CurrentConfig().model
        if not current.site or not current.name:
            raise ValueError("请先在模型管理中配置并选择模型")

        site = next((item for item in Settings().model if item.name == current.site), None)
        if site is None or not any(model.name == current.name for model in site.models):
            raise ValueError("当前选择的模型已不存在，请重新选择")
        if not site.api_url.strip():
            raise ValueError("当前供应商尚未填写 API 地址")
        if not site.api_key.strip():
            raise ValueError("当前供应商尚未填写 API Key")
        return site, current.name
