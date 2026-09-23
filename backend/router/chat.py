"""Chat methods exposed to the local Web UI."""

from __future__ import annotations

import json
from typing import Any

from webview.errors import JavascriptException, WebViewException

from backend.py2js import evaluate_js as evaluate_js_with_notify
from backend.router.command import CommandRouter
from backend.service.chat import ChatService


class ChatRouter(CommandRouter):
    """Validate UI input and adapt application settings to the chat client."""

    _window: Any | None = None

    def __init__(self) -> None:
        super().__init__()
        self._chat_service = ChatService(event_sink=self._dispatch_chat_event)

    def _dispatch_chat_event(self, payload: dict[str, Any]) -> bool:
        """py2js 桥接：把会话事件推送给前端窗口，返回是否送达。"""
        window = self._window
        if window is None:
            return False
        detail = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        script = (
            "window.dispatchEvent(new CustomEvent('xalling:chat-event',"
            f"{{detail:{detail}}}));"
        )
        try:
            evaluate_js_with_notify(
                window,
                script,
                action=f"chat-event:{payload['event']}",
            )
        except (JavascriptException, WebViewException):
            return False
        return True

    async def send_chat_message(
        self,
        prompt: str,
        project_path: str | None = None,
        session_id: str | None = None,
        effort: str = "high",
        permission_mode: str = "default",
        model_site: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Run one turn through the public synchronous bridge."""
        return await self._chat_service.send_chat_message(
            prompt,
            project_path=project_path,
            session_id=session_id,
            effort=effort,
            permission_mode=permission_mode,
            model_site=model_site,
            model=model,
        )

    async def list_scheduled_tasks(
        self,
        project_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """List scheduled tasks belonging to the requested project workspace."""
        return await self._chat_service.list_scheduled_tasks(
            project_path=project_path,
        )

    async def list_all_scheduled_tasks(self) -> list[dict[str, Any]]:
        """List all scheduled tasks for the local automation page."""
        return await self._chat_service.list_all_scheduled_tasks()

    async def delete_scheduled_task(
        self,
        task_id: str,
        project_path: str | None = None,
    ) -> dict[str, Any]:
        """Delete one scheduled task belonging to the requested workspace."""
        return await self._chat_service.delete_scheduled_task(
            task_id,
            project_path=project_path,
        )

    async def _get_chat_server_info(
        self,
        session_id: str,
        project_path: str | None = None,
        effort: str = "high",
        permission_mode: str = "default",
    ) -> dict[str, Any]:
        return await self._chat_service._get_chat_server_info(
            session_id,
            project_path=project_path,
            effort=effort,
            permission_mode=permission_mode,
        )

    async def get_context_usage(self, session_id: str) -> dict[str, Any] | None:
        """Return the live context-window usage for the active chat, if any."""
        return await self._chat_service.get_context_usage(session_id)

    async def list_chat_sessions(self) -> list[dict[str, Any]]:
        return await self._chat_service.list_chat_sessions()

    async def search_chat_sessions(self, query: str) -> list[dict[str, Any]]:
        return await self._chat_service.search_chat_sessions(query)

    async def get_chat_session(
        self,
        project_path: str | None = None,
        session_id: str | None = None,
        effort: str = "high",
        permission_mode: str = "default",
    ) -> dict[str, Any]:
        return await self._chat_service.get_chat_session(
            project_path=project_path,
            session_id=session_id,
            effort=effort,
            permission_mode=permission_mode,
        )

    def get_active_chat(self, session_id: str) -> dict[str, object] | None:
        return self._chat_service.get_active_chat(session_id)

    async def stop_chat_message(self, session_id: str | None = None) -> bool:
        return await self._chat_service.stop_chat_message(session_id)

    async def close_chat_client(self, session_id: str | None = None) -> bool:
        return await self._chat_service.close_chat_client(session_id)

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
        return await self._chat_service.set_chat_permission_mode(
            session_id,
            permission_mode=permission_mode,
            project_path=project_path,
            effort=effort,
        )

    def respond_chat_permission(
        self,
        permission_id: str,
        allowed: bool,
        answers: dict[str, str | list[str]] | None = None,
        feedback: str | None = None,
        execution_mode: str | None = None,
    ) -> bool:
        return self._chat_service.respond_chat_permission(
            permission_id,
            allowed,
            answers=answers,
            feedback=feedback,
            execution_mode=execution_mode,
        )
