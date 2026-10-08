"""Application-owned services on FastAPI's event loop."""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from backend.service.chat import ChatService
from backend.service.window import WindowService


@dataclass(slots=True)
class ApplicationServices:
    """Keep chat work alive across HTTP requests and UI reconnects."""

    chat: ChatService
    window: WindowService
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    closing: bool = False

    async def send_chat_message(self, **parameters: Any) -> dict[str, Any]:
        if self.closing:
            raise RuntimeError("应用正在关闭")
        task = asyncio.create_task(self.chat.send_chat_message(**parameters))
        self.tasks.add(task)
        task.add_done_callback(self._finish_task)
        # HTTP cancellation must not discard the logical turn or its events.
        return await asyncio.shield(task)

    def _finish_task(self, task: asyncio.Task[Any]) -> None:
        self.tasks.discard(task)
        if not task.cancelled():
            task.exception()  # Consume errors even if its HTTP caller disconnected.

    async def shutdown(self) -> None:
        self.closing = True
        self.chat.deny_pending_permissions()
        for task in tuple(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        await self.chat.shutdown_clients()
