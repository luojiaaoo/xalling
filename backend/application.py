"""Application-owned services on FastAPI's event loop."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import anyio

from backend.service.chat.service import ChatService
from backend.service.desktop.window import WindowService


@dataclass(slots=True, eq=False)
class _Operation:
    done: anyio.Event = field(default_factory=anyio.Event)
    scope: anyio.CancelScope = field(default_factory=anyio.CancelScope)
    result: Any = None
    error: BaseException | None = None


@dataclass(slots=True)
class ApplicationServices:
    """Keep chat work alive across HTTP requests and UI reconnects."""

    chat: ChatService
    window: WindowService
    task_group: anyio.abc.TaskGroup
    tasks: list[_Operation] = field(default_factory=list)
    closing: bool = False

    async def send_chat_message(self, **parameters: Any) -> dict[str, Any]:
        return await self._submit(self.chat.send_chat_message, parameters)

    async def rewind_chat_files(self, **parameters: Any) -> dict[str, object]:
        return await self._submit(self.chat.rewind_chat_files, parameters)

    async def _submit(self, action: Callable[..., Awaitable[Any]], parameters: dict[str, Any]) -> Any:
        if self.closing:
            raise RuntimeError("应用正在关闭")
        operation = _Operation()
        self.tasks.append(operation)
        self.task_group.create_task(self._run(operation, action, parameters))
        # The lifespan owns the worker; cancelling this wait leaves it running.
        await operation.done.wait()
        if operation.error is not None:
            raise operation.error
        return operation.result

    async def _run(
        self, operation: _Operation, action: Callable[..., Awaitable[Any]], parameters: dict[str, Any],
    ) -> None:
        try:
            with operation.scope:
                try:
                    operation.result = await action(**parameters)
                except BaseException as error:
                    operation.error = error
                    if isinstance(error, anyio.get_cancelled_exc_class()):
                        raise
        finally:
            operation.done.set()
            self.tasks.remove(operation)

    async def shutdown(self) -> None:
        self.closing = True
        self.chat.deny_pending_permissions()
        with anyio.CancelScope(shield=True):
            pending = tuple(self.tasks)
            for operation in pending:
                operation.scope.cancel()
            for operation in pending:
                await operation.done.wait()
            await self.chat.shutdown_clients()
