"""Shared FastAPI dependencies for token authentication and services."""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, WebSocket, WebSocketException

from backend.application import ApplicationServices
from backend.service.chat import ChatService
from backend.service.window import WindowService


async def authenticate(request: Request) -> None:
    supplied = request.headers.get("authorization", "")
    token = request.app.state.token
    if (
        request.app.state.first_access
        or not token
        or not secrets.compare_digest(supplied.encode(), f"Bearer {token}".encode())
    ):
        raise HTTPException(status_code=401, detail="连接凭证无效")


async def authenticate_websocket(websocket: WebSocket) -> None:
    protocols = websocket.scope.get("subprotocols", [])
    token = websocket.app.state.token
    if (
        "xalling" not in protocols
        or websocket.app.state.first_access
        or not token
        or not any(secrets.compare_digest(protocol.encode(), f"auth.{token}".encode()) for protocol in protocols)
    ):
        raise WebSocketException(code=1008, reason="连接凭证无效")


async def get_services(request: Request) -> ApplicationServices:
    return request.app.state.services


async def get_chat(services: Annotated[ApplicationServices, Depends(get_services)]) -> ChatService:
    return services.chat


async def get_window(services: Annotated[ApplicationServices, Depends(get_services)]) -> WindowService:
    return services.window


ServicesDep = Annotated[ApplicationServices, Depends(get_services)]
ChatDep = Annotated[ChatService, Depends(get_chat)]
WindowDep = Annotated[WindowService, Depends(get_window)]
