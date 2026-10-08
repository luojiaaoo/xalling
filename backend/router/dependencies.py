"""Shared FastAPI dependencies for local authentication and services."""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, WebSocket, WebSocketException

from backend.application import ApplicationServices
from backend.service.chat import ChatService
from backend.service.window import WindowService


async def authenticate(request: Request) -> None:
    authorization = request.headers.get("authorization", "")
    expected = f"Bearer {request.app.state.token}"
    if not secrets.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="本机连接凭证无效")
    origin = request.headers.get("origin")
    if origin is not None and origin != request.app.state.origin:
        raise HTTPException(status_code=403, detail="请求来源无效")


async def authenticate_websocket(websocket: WebSocket) -> None:
    protocols = websocket.scope.get("subprotocols", [])
    expected = f"auth.{websocket.app.state.token}".encode()
    if (
        "xalling" not in protocols
        or not any(secrets.compare_digest(protocol.encode(), expected) for protocol in protocols)
        or websocket.headers.get("origin") != websocket.app.state.origin
    ):
        raise WebSocketException(code=1008, reason="连接凭证或来源无效")


async def get_services(request: Request) -> ApplicationServices:
    return request.app.state.services


async def get_chat(services: Annotated[ApplicationServices, Depends(get_services)]) -> ChatService:
    return services.chat


async def get_window(services: Annotated[ApplicationServices, Depends(get_services)]) -> WindowService:
    return services.window


ServicesDep = Annotated[ApplicationServices, Depends(get_services)]
ChatDep = Annotated[ChatService, Depends(get_chat)]
WindowDep = Annotated[WindowService, Depends(get_window)]
