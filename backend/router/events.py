"""Authenticated WebSocket endpoint for live chat events."""

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from backend.router.dependencies import authenticate_websocket
from backend.service.events import WebSocketEvents

router = APIRouter(tags=["events"], dependencies=[Depends(authenticate_websocket)])


@router.websocket("/ws")
async def chat_events(websocket: WebSocket) -> None:
    await websocket.accept(subprotocol="xalling")
    events: WebSocketEvents = websocket.app.state.events
    connection = events.connect(websocket)
    try:
        while True:
            # Business calls use HTTP; reading detects a disconnected UI.
            await websocket.receive_text()
            await websocket.close(code=1008, reason="此连接只推送聊天事件")
            break
    except WebSocketDisconnect:
        return
    finally:
        if events.disconnect(connection):
            websocket.app.state.services.chat.deny_pending_permissions()
