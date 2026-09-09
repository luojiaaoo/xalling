"""Chat methods exposed to the local Web UI."""

import asyncio
import json
from concurrent.futures import Future
from functools import partial
from pathlib import Path
from threading import Lock
from typing import Any, cast
from uuid import UUID, uuid4

from claude_agent_sdk import (
    ClaudeSDKError,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)
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
from backend.config.setting import ModelSiteConfig, Settings


class ChatRouter:
    """Validate UI input and delegate agent turns to the chat library."""

    _window: Any | None = None

    def __init__(self) -> None:
        super().__init__()
        self._permission_lock = Lock()
        self._pending_permissions: dict[str, tuple[str, Future[bool]]] = {}

    def send_chat_message(
        self,
        prompt: str,
        project_path: str | None = None,
        session_id: str | None = None,
        effort: str = "high",
        request_id: str | None = None,
        permission_mode: str = "default",
    ) -> ChatReply:
        """Run one turn, stream text events, and return the final response."""
        normalized_prompt = self._validate_prompt(prompt)
        project = self._validate_project_path(project_path)
        resume = self._validate_session_id(session_id)
        normalized_effort = self._validate_effort(effort)
        normalized_permission_mode = self._validate_permission_mode(permission_mode)
        stream_request_id = self._validate_request_id(request_id)
        site, model_name = self._get_current_provider()
        can_use_tool = (
            partial(self._request_tool_permission, stream_request_id)
            if stream_request_id is not None
            else None
        )
        client = ClaudeChatClient(
            ClaudeChatConfig(
                api_key=site.api_key,
                api_url=site.api_url,
                can_use_tool=can_use_tool,
                effort=normalized_effort,
                model=model_name,
                permission_mode=normalized_permission_mode,
                project=project,
                resume=resume,
            )
        )

        try:
            return asyncio.run(
                client.send(
                    normalized_prompt,
                    on_event=(
                        lambda event: self._emit_chat_event(stream_request_id, event)
                    )
                    if stream_request_id is not None
                    else None,
                )
            )
        except ClaudeSDKError as error:
            raise RuntimeError(f"Claude SDK 请求失败：{error}") from error

    def respond_chat_permission(
        self,
        request_id: str,
        permission_id: str,
        allowed: bool,
    ) -> bool:
        """Resolve a pending SDK tool permission request from the Web UI."""
        normalized_request_id = self._validate_request_id(request_id)
        normalized_permission_id = self._validate_permission_id(permission_id)
        if normalized_request_id is None:
            raise ValueError("请求标识无效")
        if type(allowed) is not bool:
            raise TypeError("权限决定必须是布尔值")

        with self._permission_lock:
            pending = self._pending_permissions.get(normalized_permission_id)
            if pending is None or pending[0] != normalized_request_id:
                return False
            decision = pending[1]
            if decision.done():
                return False
            decision.set_result(allowed)
        return True

    async def _request_tool_permission(
        self,
        request_id: str,
        tool_name: str,
        input_data: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        """Pause a tool call until the matching Web UI request is answered."""
        permission_id = str(uuid4())
        decision: Future[bool] = Future()
        with self._permission_lock:
            self._pending_permissions[permission_id] = (request_id, decision)

        event: ChatEvent = {
            "type": "permission_request",
            "permission_id": permission_id,
            "tool_name": tool_name,
            "input": input_data,
            "title": context.title or f"Claude 请求使用 {tool_name}",
            "display_name": context.display_name or tool_name,
            "description": (
                context.description
                or context.decision_reason
                or "此操作需要你的确认后才能继续。"
            ),
            "blocked_path": context.blocked_path or "",
        }
        if not self._emit_chat_event(request_id, event):
            with self._permission_lock:
                self._pending_permissions.pop(permission_id, None)
            return PermissionResultDeny(message="无法显示工具权限确认，已拒绝本次调用")

        try:
            allowed = await asyncio.wrap_future(decision)
        finally:
            with self._permission_lock:
                self._pending_permissions.pop(permission_id, None)

        if allowed:
            return PermissionResultAllow()
        return PermissionResultDeny(message="用户已拒绝本次工具调用")

    def _emit_chat_event(self, request_id: str, event: ChatEvent) -> bool:
        """Dispatch one structured progress event to the matching Web UI request."""
        if self._window is None:
            return False

        event_detail = {"request_id": request_id, **event}
        detail = json.dumps(
            event_detail,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        script = (
            "window.dispatchEvent(new CustomEvent('xalling:chat-event',"
            f"{{detail:{detail}}}));"
        )
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

    @staticmethod
    def _validate_prompt(value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("消息内容必须是字符串")
        normalized = value.strip()
        if not normalized:
            raise ValueError("消息内容不能为空")
        if len(normalized) > 500_000:
            raise ValueError("消息内容过长")
        return normalized

    @staticmethod
    def _validate_project_path(value: object) -> Path:
        if value is None or value == "":
            return Path.home().resolve()
        if not isinstance(value, str):
            raise TypeError("项目路径必须是字符串")
        project = Path(value).resolve()
        if not project.is_dir():
            raise ValueError("选择的项目文件夹已不存在")
        return project

    @staticmethod
    def _validate_session_id(value: object) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise TypeError("会话标识必须是字符串")
        try:
            return str(UUID(value))
        except ValueError as error:
            raise ValueError("会话标识无效") from error

    @staticmethod
    def _validate_effort(value: object) -> ChatEffort:
        if not isinstance(value, str) or value not in {"low", "medium", "high", "max"}:
            raise ValueError("推理强度无效")
        return cast(ChatEffort, value)

    @staticmethod
    def _validate_permission_mode(value: object) -> ChatPermissionMode:
        permission_modes = {
            "default",
            "acceptEdits",
            "plan",
            "auto",
            "bypassPermissions",
        }
        if not isinstance(value, str) or value not in permission_modes:
            raise ValueError("权限模式无效")
        return cast(ChatPermissionMode, value)

    @staticmethod
    def _validate_permission_id(value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("权限请求标识必须是字符串")
        try:
            return str(UUID(value))
        except ValueError as error:
            raise ValueError("权限请求标识无效") from error

    @staticmethod
    def _validate_request_id(value: object) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise TypeError("请求标识必须是字符串")
        normalized = value.strip()
        if not normalized or len(normalized) > 128:
            raise ValueError("请求标识无效")
        return normalized
