"""Chat methods exposed to the local Web UI."""

from __future__ import annotations

import asyncio
import json
from contextlib import AsyncExitStack
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from time import time
from typing import Any, Literal
from uuid import UUID, uuid4

import asyncer
from claude_agent_sdk import (
    ClaudeSDKError,
    PermissionMode,
    PermissionResultAllow,
    PermissionResultDeny,
)
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from webview.errors import JavascriptException, WebViewException

from backend.claude_chat_client import ChatEvent, ClaudeChatClient, ClaudeChatHistory
from backend.claude_chat_client.models import render_event
from backend.config.current import CurrentConfig
from backend.config.setting import (
    ModelConfig,
    ModelSiteConfig,
    default_project_folder,
    get_settings,
)
from backend.py2js import evaluate_js as evaluate_js_with_notify
from backend.router._claude_options import (
    ChatEffort,
    ClaudeConnectionConfig,
    configured_claude_client,
)
from backend.router.command import CommandRouter, is_allowed_leading_slash

CHAT_CLIENT_IDLE_SECONDS = 10 * 60
_UI_PERMISSION_MODES = frozenset(
    {"default", "acceptEdits", "plan", "auto", "bypassPermissions"}
)
EMPTY_COMMAND_RESULTS = {"compact": "上下文已压缩。"}


def _user_facing_error(error: ValidationError) -> ValueError:
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
    first_token = prompt.split(maxsplit=1)[0]
    if not first_token.startswith("/"):
        return
    name = first_token.removeprefix("/")
    if name and is_allowed_leading_slash(name, server_info):
        return
    raise ValueError(f"不允许执行命令 {first_token}")


class _ChatConfigRequest(BaseModel):
    """Validated chat configuration shared by message and command fetches."""

    model_config = ConfigDict(validate_default=True)

    project_path: Path | None = None
    session_id: str | None = None
    effort: ChatEffort = "high"
    permission_mode: PermissionMode = "default"

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
        if not isinstance(value, str) or value not in {
            "low",
            "medium",
            "high",
            "max",
        }:
            raise ValueError("推理强度无效")
        return value

    @field_validator("permission_mode", mode="before")
    @classmethod
    def _validate_permission_mode(cls, value: object) -> object:
        if not isinstance(value, str) or value not in _UI_PERMISSION_MODES:
            raise ValueError("权限模式无效")
        return value


class _ChatMessageRequest(_ChatConfigRequest):
    prompt: str

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


class _ChatPermissionModeRequest(BaseModel):
    """Validated payload for changing a live chat's permission mode."""

    permission_mode: PermissionMode

    @field_validator("permission_mode", mode="before")
    @classmethod
    def _validate_permission_mode(cls, value: object) -> object:
        if not isinstance(value, str) or value not in _UI_PERMISSION_MODES:
            raise ValueError("权限模式无效")
        return value


class _ChatPermissionDecision(BaseModel):
    permission_id: str
    allowed: bool
    answers: dict[str, str | list[str]] | None = None
    feedback: str | None = None
    execution_mode: Literal[
        "default",
        "acceptEdits",
        "auto",
    ] | None = None

    @field_validator("permission_id", mode="before")
    @classmethod
    def _validate_permission_id(cls, value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("权限请求标识必须是字符串")
        normalized = value.strip()
        if not normalized or len(normalized) > 512:
            raise ValueError("权限请求标识无效")
        return normalized

    @field_validator("allowed", mode="before")
    @classmethod
    def _validate_allowed(cls, value: object) -> bool:
        if type(value) is not bool:
            raise TypeError("权限决定必须是布尔值")
        return value

    @field_validator("answers", mode="before")
    @classmethod
    def _validate_answers(
        cls,
        value: object,
    ) -> dict[str, str | list[str]] | None:
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
            if any(
                not isinstance(item, str) or not item.strip() for item in answer
            ):
                raise ValueError("多选回答不能包含空值")
            normalized[question] = [item.strip() for item in answer]
        return normalized

    @field_validator("feedback", mode="before")
    @classmethod
    def _validate_feedback(cls, value: object) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise TypeError("计划反馈必须是字符串")
        normalized = value.strip()
        if len(normalized) > 20_000:
            raise ValueError("计划反馈过长")
        return normalized or None


@dataclass(slots=True)
class _ActiveChat:
    client: ClaudeChatClient
    config: ClaudeConnectionConfig
    resources: AsyncExitStack
    events: list[ChatEvent]
    metadata: dict[str, object]
    running: bool = False
    cleanup_task: asyncio.Task[None] | None = None
    cleanup_generation: int = 0


class ChatRouter(CommandRouter):
    """Validate UI input and adapt application settings to the chat client."""

    _window: Any | None = None

    def __init__(self) -> None:
        super().__init__()
        self._active_chats: dict[str, _ActiveChat] = {}
        self._history = ClaudeChatHistory()

    async def send_chat_message(
        self,
        prompt: str,
        project_path: str | None = None,
        session_id: str | None = None,
        effort: str = "high",
        permission_mode: str = "default",
    ) -> dict[str, Any]:
        """Run one turn and dispatch the client's public event envelopes."""
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
        existing = self._active_chats.get(active_session_id)
        if existing is not None and existing.running:
            raise RuntimeError("当前会话正在生成，请先停止后再发送")

        site, model = await self._get_current_provider()
        config = ClaudeConnectionConfig(
            api_key=site.api_key,
            api_url=site.api_url,
            effort=request.effort,
            max_context_tokens=model.max_context_tokens,
            model=model.name,
            permission_mode=request.permission_mode,
            project=request.project_path,
            session_id=active_session_id,
            api_protocol=site.api_protocol,
        )
        active_chat = await self._get_or_create_chat(config)
        client = active_chat.client

        first_token = request.prompt.split(maxsplit=1)[0]
        server_info = await client.get_server_info() if first_token.startswith("/") else {}
        _validate_leading_slash(request.prompt, server_info or {})

        if active_chat.cleanup_task is not None:
            active_chat.cleanup_task.cancel()
            active_chat.cleanup_task = None
        now = int(time() * 1000)
        title = " ".join(request.prompt.split()) or "未命名会话"
        active_chat.events.clear()
        active_chat.metadata = {
            "session_id": active_session_id,
            "title": title[:100],
            "summary": title[:100],
            "cwd": str(request.project_path),
            "file_size": None,
            "custom_title": None,
            "first_prompt": request.prompt,
            "git_branch": None,
            "tag": None,
            "last_modified": now,
            "created_at": active_chat.metadata.get("created_at", now),
        }
        active_chat.running = True

        command_name = first_token.removeprefix("/") if first_token.startswith("/") else ""
        try:
            result = await client.send(
                request.prompt,
                session_id=active_session_id,
                on_event=partial(
                    self._emit_chat_event,
                    session_id=active_session_id,
                ),
                empty_result_content=EMPTY_COMMAND_RESULTS.get(command_name),
            )
            return result.to_dict()
        except ClaudeSDKError as error:
            raise RuntimeError(f"Claude SDK 请求失败：{error}") from error
        finally:
            retained = self._active_chats.get(active_session_id)
            if retained is not None and retained.client is client:
                retained.running = False
                self._schedule_client_cleanup(active_session_id, retained)

    async def _get_or_create_chat(
        self,
        config: ClaudeConnectionConfig,
    ) -> _ActiveChat:
        active_chat = self._active_chats.get(config.session_id)
        # 已经有了session，并且配置保持一样
        if active_chat is not None and active_chat.config.config_equal(config):
            active_chat.client.set_permission_mode(config.permission_mode)
            return active_chat
        # 已经有了，但是配置变了，先关闭
        if active_chat is not None:
            await self._close_active_chat(config.session_id, active_chat)
        # 新建client
        resources = AsyncExitStack()
        try:
            client = await resources.enter_async_context(
                configured_claude_client(config, is_new_session=not self._history.has_session(config.session_id))
            )
        except BaseException:
            await resources.aclose()
            raise
        now = int(time() * 1000)
        active_chat = _ActiveChat(
            client=client,
            config=config,
            resources=resources,
            events=[],
            metadata={
                "session_id": config.session_id,
                "title": "未命名会话",
                "summary": "未命名会话",
                "cwd": str(config.project),
                "file_size": None,
                "custom_title": None,
                "first_prompt": None,
                "git_branch": None,
                "tag": None,
                "last_modified": now,
                "created_at": now,
            },
        )
        self._active_chats[config.session_id] = active_chat
        self._schedule_client_cleanup(config.session_id, active_chat)
        return active_chat

    async def _get_chat_server_info(
        self,
        session_id: str,
        project_path: str | None = None,
        effort: str = "high",
        permission_mode: str = "default",
    ) -> dict[str, Any]:
        try:
            config_request = _ChatConfigRequest.model_validate(
                {
                    "project_path": project_path,
                    "session_id": session_id,
                    "effort": effort,
                    "permission_mode": permission_mode,
                }
            )
        except ValidationError as error:
            raise _user_facing_error(error) from error

        normalized_session_id = config_request.session_id
        if normalized_session_id is None:
            raise ValueError("会话标识无效")

        site, model = await self._get_current_provider()
        config = ClaudeConnectionConfig(
            api_key=site.api_key,
            api_url=site.api_url,
            effort=config_request.effort,
            max_context_tokens=model.max_context_tokens,
            model=model.name,
            permission_mode=config_request.permission_mode,
            project=config_request.project_path,
            session_id=normalized_session_id,
            api_protocol=site.api_protocol,
        )
        active_chat = await self._get_or_create_chat(config)
        try:
            return await active_chat.client.get_server_info() or {}
        finally:
            if not active_chat.running:
                self._schedule_client_cleanup(
                    active_chat.config.session_id,
                    active_chat,
                )

    async def get_context_usage(self, session_id: str) -> dict[str, Any] | None:
        """Return the live context-window usage for the active chat, if any."""
        normalized = self._normalize_optional_session_id(session_id)
        if normalized is None:
            raise ValueError("会话标识无效")
        active_chat = self._active_chats.get(normalized)
        if active_chat is None:
            return None
        try:
            return dict(await active_chat.client.get_context_usage())
        except Exception: # 第一次获取的时候，软件关闭，导致client挂掉，忽略报错，关闭时间延长
            pass
        finally:
            if not active_chat.running:
                self._schedule_client_cleanup(normalized, active_chat)

    def _schedule_client_cleanup(
        self,
        session_id: str,
        active_chat: _ActiveChat,
    ) -> None:
        if active_chat.running:
            return
        if active_chat.cleanup_task is not None:
            active_chat.cleanup_task.cancel()
        active_chat.cleanup_generation += 1
        generation = active_chat.cleanup_generation
        active_chat.cleanup_task = asyncio.create_task(
            self._expire_chat_client(session_id, active_chat.client, generation),
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
        if (
            active_chat is None
            or active_chat.client is not client
            or active_chat.running
            or active_chat.cleanup_generation != generation
        ):
            return
        await self._close_active_chat(session_id, active_chat)

    async def _close_active_chat(
        self,
        session_id: str,
        active_chat: _ActiveChat,
    ) -> None:
        if self._active_chats.get(session_id) is active_chat:
            self._active_chats.pop(session_id, None)
        cleanup_task = active_chat.cleanup_task
        active_chat.cleanup_task = None
        if cleanup_task is not None and cleanup_task is not asyncio.current_task():
            cleanup_task.cancel()
        await active_chat.resources.aclose()

    async def _shutdown_chat_clients(self) -> None:
        active_items = list(self._active_chats.items())
        self._active_chats.clear()
        for _, active_chat in active_items:
            if active_chat.cleanup_task is not None:
                active_chat.cleanup_task.cancel()
                active_chat.cleanup_task = None
        for _, active_chat in active_items:
            await active_chat.resources.aclose()

    async def list_chat_sessions(self) -> list[dict[str, Any]]:
        sessions = await asyncer.asyncify(self._history.list_sessions)()
        sessions_by_id = {
            session.session_id: {**session.to_dict(), "running": False}
            for session in sessions
        }
        for session_id, active_chat in self._active_chats.items():
            if not active_chat.running:
                continue
            persisted = sessions_by_id.get(session_id)
            sessions_by_id[session_id] = {
                **(persisted or active_chat.metadata),
                "last_modified": active_chat.metadata["last_modified"],
                "running": True,
            }
        return sorted(
            sessions_by_id.values(),
            key=lambda session: int(session["last_modified"]),
            reverse=True,
        )

    async def search_chat_sessions(self, query: str) -> list[dict[str, Any]]:
        if not isinstance(query, str):
            raise TypeError("搜索关键词必须是字符串")
        matches = await asyncer.asyncify(self._history.search_sessions)(query)
        return [match.to_dict() for match in matches]

    async def get_chat_session(self, session_id: str) -> dict[str, Any]:
        normalized = self._normalize_optional_session_id(session_id)
        if normalized is None:
            raise ValueError("会话标识无效")
        try:
            snapshot = await asyncer.asyncify(self._history.get_session)(normalized)
            payload = snapshot.to_dict()
            payload["render_events"] = [
                self._event_payload(event, normalized)
                for event in snapshot.events
            ]
            return payload
        except ValueError:
            active_chat = self._active_chats.get(normalized)
            if active_chat is None or not active_chat.running:
                raise
            return {**active_chat.metadata, "events": []}

    def get_active_chat(self, session_id: str) -> dict[str, object] | None:
        normalized = self._normalize_optional_session_id(session_id)
        if normalized is None:
            return None
        active_chat = self._active_chats.get(normalized)
        if active_chat is None or not active_chat.running:
            return None
        pending_ids = set(active_chat.client.pending_permission_ids)
        events = [
            self._event_payload(event, normalized)
            for event in active_chat.events
            if event.event != "permission.requested"
            or event.data.get("request_id") in pending_ids
        ]
        return {
            "session_id": normalized,
            "events": events,
            "render_events": events,
        }

    async def stop_chat_message(self, session_id: str | None = None) -> bool:
        normalized = self._normalize_optional_session_id(session_id)
        if normalized is None:
            running = [
                chat
                for chat in self._active_chats.values()
                if chat.running
            ]
            if not running:
                return False
            if len(running) > 1:
                raise ValueError("存在多个正在生成的会话，请指定要停止的会话")
            active_chat = running[0]
        else:
            active_chat = self._active_chats.get(normalized)
            if active_chat is None or not active_chat.running:
                return False
        await active_chat.client.request_stop()
        return True

    async def set_chat_permission_mode(
        self,
        session_id: str | None = None,
        permission_mode: str = "default",
        project_path: str | None = None,
        effort: str = "high",
    ) -> bool:
        """Update a retained chat's live SDK permission mode.

        A chat without a client gets one created so a mode the current model
        does not support fails immediately instead of on the next turn.
        Existing clients are updated in place so a mode change made while a
        turn is running takes effect immediately.
        """
        normalized = self._normalize_optional_session_id(session_id)
        if normalized is None:
            raise ValueError("会话ID标识无效")
        try:
            request = _ChatPermissionModeRequest.model_validate(
                {"permission_mode": permission_mode}
            )
        except ValidationError as error:
            raise _user_facing_error(error) from error

        active_chat = self._active_chats.get(normalized)
        if active_chat is None:
            try:
                config_request = _ChatConfigRequest.model_validate(
                    {
                        "project_path": project_path,
                        "session_id": normalized,
                        "effort": effort,
                        "permission_mode": request.permission_mode,
                    }
                )
            except ValidationError as error:
                raise _user_facing_error(error) from error
            site, model = await self._get_current_provider()
            config = ClaudeConnectionConfig(
                api_key=site.api_key,
                api_url=site.api_url,
                effort=config_request.effort,
                max_context_tokens=model.max_context_tokens,
                model=model.name,
                permission_mode=config_request.permission_mode,
                project=config_request.project_path,
                session_id=normalized,
                api_protocol=site.api_protocol,
            )
            active_chat = await self._get_or_create_chat(config)
            # 初始化的时候不报错，很奇怪，所以需要单独执行一次来判断，但是报错之后
            # 其实 permission_mode 和 config 就对不上了，不过可以动态修改，倒是也无所谓
            await active_chat.client.set_permission_mode(request.permission_mode)
            return True
        else:
            await active_chat.client.set_permission_mode(request.permission_mode)
            active_chat.config = replace(
                active_chat.config,
                permission_mode=request.permission_mode,
            )
            return True

    def respond_chat_permission(
        self,
        permission_id: str,
        allowed: bool,
        answers: dict[str, str | list[str]] | None = None,
        feedback: str | None = None,
        execution_mode: str | None = None,
    ) -> bool:
        try:
            decision = _ChatPermissionDecision.model_validate(
                {
                    "permission_id": permission_id,
                    "allowed": allowed,
                    "answers": answers,
                    "feedback": feedback,
                    "execution_mode": execution_mode,
                }
            )
        except ValidationError as error:
            raise _user_facing_error(error) from error

        located = self._find_permission(decision.permission_id)
        if located is None:
            return False
        client, tool_name, tool_input = located
        if decision.execution_mode is not None and (
            tool_name != "ExitPlanMode" or not decision.allowed
        ):
            raise ValueError("只有执行计划时才能选择执行方式")
        if tool_name == "ExitPlanMode" and decision.allowed and decision.execution_mode is None:
            raise ValueError("ExitPlanMode requires an explicit execution mode")
        normalized_answers = self._validate_tool_answers(
            tool_name,
            tool_input,
            decision,
        )
        normalized_feedback = self._validate_tool_feedback(tool_name, decision)
        try:
            if tool_name == "ExitPlanMode":
                client.resolve_plan_approval(
                    decision.permission_id,
                    approved=decision.allowed,
                    mode=decision.execution_mode if decision.allowed else None,
                    message=normalized_feedback or "",
                )
            elif decision.allowed:
                updated_input = dict(tool_input)
                if tool_name == "AskUserQuestion":
                    updated_input["answers"] = normalized_answers
                client.resolve_permission(
                    decision.permission_id,
                    PermissionResultAllow(updated_input=updated_input),
                )
            else:
                client.resolve_permission(
                    decision.permission_id,
                    PermissionResultDeny(message="用户已拒绝本次工具调用"),
                )
        except (KeyError, RuntimeError):
            return False
        return True

    def _find_permission(
        self,
        request_id: str,
    ) -> tuple[ClaudeChatClient, str, dict[str, Any]] | None:
        for active_chat in self._active_chats.values():
            if request_id not in active_chat.client.pending_permission_ids:
                continue
            for event in reversed(active_chat.events):
                if (
                    event.event == "permission.requested"
                    and event.data.get("request_id") == request_id
                ):
                    tool_name = event.data.get("tool_name")
                    tool_input = event.data.get("tool_input")
                    if isinstance(tool_name, str) and isinstance(tool_input, dict):
                        return active_chat.client, tool_name, tool_input
        return None

    @staticmethod
    def _validate_tool_feedback(
        tool_name: str,
        decision: _ChatPermissionDecision,
    ) -> str | None:
        if decision.feedback is None:
            return None
        if tool_name != "ExitPlanMode" or decision.allowed:
            raise ValueError("只有继续规划时才能提交计划反馈")
        return decision.feedback

    @staticmethod
    def _validate_tool_answers(
        tool_name: str,
        tool_input: dict[str, Any],
        decision: _ChatPermissionDecision,
    ) -> dict[str, str | list[str]] | None:
        if tool_name != "AskUserQuestion":
            if decision.answers is not None:
                raise ValueError("普通工具权限确认不能包含用户回答")
            return None
        if not decision.allowed:
            return None
        if decision.answers is None:
            raise ValueError("请回答全部问题后再提交")
        raw_questions = tool_input.get("questions")
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

    def _emit_chat_event(self, event: ChatEvent, *, session_id: str) -> bool:
        active_chat = self._active_chats.get(session_id)
        if active_chat is not None:
            active_chat.events.append(event)
            if event.event == "permission.mode.changed":
                mode = event.data.get("mode")
                if isinstance(mode, str) and mode in _UI_PERMISSION_MODES:
                    active_chat.config = replace(
                        active_chat.config,
                        permission_mode=mode,
                    )
        if self._window is None:
            self._deny_undeliverable_permission(active_chat, event)
            return False
        detail = json.dumps(
            self._event_payload(event, session_id),
            ensure_ascii=True,
            separators=(",", ":"),
        )
        script = (
            "window.dispatchEvent(new CustomEvent('xalling:chat-event',"
            f"{{detail:{detail}}}));"
        )
        try:
            evaluate_js_with_notify(
                self._window,
                script,
                action=f"chat-event:{event.event}",
            )
        except (JavascriptException, WebViewException):
            self._deny_undeliverable_permission(active_chat, event)
            return False
        return True

    @staticmethod
    def _deny_undeliverable_permission(
        active_chat: _ActiveChat | None,
        event: ChatEvent,
    ) -> None:
        if active_chat is None or event.event != "permission.requested":
            return
        request_id = event.data.get("request_id")
        tool_name = event.data.get("tool_name")
        if not isinstance(request_id, str):
            return
        message = "无法显示工具权限确认，已拒绝本次调用"
        try:
            if tool_name == "ExitPlanMode":
                active_chat.client.resolve_plan_approval(
                    request_id,
                    approved=False,
                    mode=None,
                    message=message,
                )
            else:
                active_chat.client.resolve_permission(
                    request_id,
                    PermissionResultDeny(message=message),
                )
        except (KeyError, RuntimeError, ValueError):
            return

    @staticmethod
    def _event_payload(event: ChatEvent, session_id: str) -> dict[str, Any]:
        render = render_event(event)
        render["session_id"] = session_id
        return {**event.to_dict(), "session_id": session_id, "render": render}

    @staticmethod
    def _normalize_optional_session_id(value: object) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise TypeError("会话标识必须是字符串")
        try:
            return str(UUID(value))
        except ValueError as error:
            raise ValueError("会话标识无效") from error

    @staticmethod
    async def _get_current_provider() -> tuple[ModelSiteConfig, ModelConfig]:
        current = CurrentConfig().model
        if not current.site or not current.name:
            raise ValueError("请先在模型管理中配置并选择模型")
        settings = await get_settings()
        site = next((item for item in settings.model if item.name == current.site), None)
        model = (
            next((item for item in site.models if item.name == current.name), None)
            if site is not None
            else None
        )
        if site is None or model is None:
            raise ValueError("当前选择的模型已不存在，请重新选择")
        if not site.api_url.strip():
            raise ValueError("当前供应商尚未填写 API 地址")
        if not site.api_key.strip():
            raise ValueError("当前供应商尚未填写 API Key")
        return site, model
