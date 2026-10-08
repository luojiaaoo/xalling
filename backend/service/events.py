"""Ordered, bounded WebSocket delivery on the application event loop."""

from typing import Any

import anyio
import asyncer
from fastapi import WebSocket, WebSocketDisconnect


class EventConnection:
    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.lock = anyio.Lock()
        self.closed = False

    async def send(self, payload: dict[str, Any]) -> bool:
        async with self.lock:
            if self.closed:
                return False
            try:
                with anyio.fail_after(5):
                    await self.websocket.send_json(payload)
                return True
            except (WebSocketDisconnect, RuntimeError, OSError, TimeoutError):
                self.closed = True
                return False


class WebSocketEvents:
    """Deliver events directly on FastAPI's loop with bounded send time."""

    def __init__(self) -> None:
        self._connections: set[EventConnection] = set()

    def connect(self, websocket: WebSocket) -> EventConnection:
        connection = EventConnection(websocket)
        self._connections.add(connection)
        return connection

    def disconnect(self, connection: EventConnection) -> bool:
        """Remove the UI connection and report whether this was the last one."""
        connection.closed = True
        self._connections.discard(connection)
        return not self._connections

    async def publish(self, payload: dict[str, Any]) -> bool:
        connections = tuple(self._connections)
        if not connections:
            return False
        async with asyncer.create_task_group() as tasks:
            sends = [
                tasks.soonify(connection.send)({"type": "event", "event": "chat", "data": payload})
                for connection in connections
            ]
        return any(send.value for send in sends)
