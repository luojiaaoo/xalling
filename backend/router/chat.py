"""Chat methods exposed to the local Web UI."""

import asyncio
import json
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import UUID, uuid4

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
)
from backend.config.current import CurrentConfig
from backend.config.setting import ModelSiteConfig, Settings, default_project_folder


def _user_facing_error(error: ValidationError) -> ValueError:
    """Translate the first pydantic error into the message shown by the Web UI."""
    first = error.errors()[0]
    message = str(first["msg"])
    if message.startswith("Value error, "):
        message = message.removeprefix("Value error, ")
    else:
        message = f"参数 {first['loc'][0]} 无效"
    return ValueError(message)


class ChatMessageRequest(BaseModel):
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


class ChatPermissionDecision(BaseModel):
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
    future: Future[_PermissionDecision]


class ChatRouter:
    """Validate UI input and delegate agent turns to the chat library."""

    _window: Any | None = None

    def __init__(self) -> None:
        super().__init__()
        self._active_chat_client: ClaudeChatClient | None = None
        self._permission_lock = Lock()
        self._pending_permissions: dict[str, _PendingPermission] = {}

    def send_chat_message(
        self,
        prompt: str,
        project_path: str | None = None,
        session_id: str | None = None,
        effort: str = "high",
        permission_mode: str = "default",
    ) -> ChatReply:
        """Run one turn, stream text events, and return the final response."""
        try:
            request = ChatMessageRequest.model_validate(
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

        site, model_name = self._get_current_provider()
        client = ClaudeChatClient(
            ClaudeChatConfig(
                api_key=site.api_key,
                api_url=site.api_url,
                can_use_tool=self._request_tool_permission,
                effort=request.effort,
                model=model_name,
                permission_mode=request.permission_mode,
                project=request.project_path,
                resume=request.session_id,
            )
        )

        if self._active_chat_client is not None:
            raise RuntimeError("当前会话正在生成，请先停止后再发送")
        self._active_chat_client = client

        try:
            return asyncio.run(
                client.send(
                    request.prompt,
                    on_event=self._emit_chat_event,
                )
            )
        except ClaudeSDKError as error:
            raise RuntimeError(f"Claude SDK 请求失败：{error}") from error
        finally:
            if self._active_chat_client is client:
                self._active_chat_client = None

    def stop_chat_message(self) -> bool:
        """Interrupt the active single-chat turn and release permission prompts."""
        client = self._active_chat_client
        if client is None:
            return False

        with self._permission_lock:
            pending_decisions = [
                pending.future
                for pending in self._pending_permissions.values()
                if not pending.future.done()
            ]
            for decision in pending_decisions:
                decision.set_result(_PermissionDecision(allowed=False))

        interrupt = client.request_stop()
        if interrupt is not None:
            interrupt.result(timeout=5)
        return True

    def respond_chat_permission(
        self,
        permission_id: str,
        allowed: bool,
        answers: dict[str, str | list[str]] | None = None,
    ) -> bool:
        """Resolve a pending SDK tool permission request from the Web UI."""
        try:
            decision = ChatPermissionDecision.model_validate(
                {
                    "permission_id": permission_id,
                    "allowed": allowed,
                    "answers": answers,
                }
            )
        except ValidationError as error:
            raise _user_facing_error(error) from error

        with self._permission_lock:
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
    ) -> PermissionResultAllow | PermissionResultDeny:
        """Pause a tool call until the matching Web UI request is answered."""
        permission_id = str(uuid4())
        decision: Future[_PermissionDecision] = Future()
        with self._permission_lock:
            self._pending_permissions[permission_id] = _PendingPermission(
                tool_name=tool_name,
                input_data=input_data,
                future=decision,
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
        if not self._emit_chat_event(event):
            with self._permission_lock:
                self._pending_permissions.pop(permission_id, None)
            return PermissionResultDeny(message="无法显示工具权限确认，已拒绝本次调用")

        try:
            response = await asyncio.wrap_future(decision)
        finally:
            with self._permission_lock:
                self._pending_permissions.pop(permission_id, None)

        if response.allowed:
            if tool_name == "AskUserQuestion":
                return PermissionResultAllow(
                    updated_input={**input_data, "answers": response.answers}
                )
            return PermissionResultAllow()
        return PermissionResultDeny(message="用户已拒绝本次工具调用")

    @staticmethod
    def _validate_tool_answers(
        pending: _PendingPermission,
        decision: ChatPermissionDecision,
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

    def _emit_chat_event(self, event: ChatEvent) -> bool:
        """Dispatch one structured progress event to the Web UI."""
        if self._window is None:
            return False

        detail = json.dumps(
            event,
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
