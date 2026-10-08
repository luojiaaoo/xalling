"""Local FastAPI server, application lifespan and native WebSocket events."""

from __future__ import annotations

import secrets
import socket
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from threading import Thread

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.trustedhost import TrustedHostMiddleware
from yarl import URL

from backend.application import ApplicationServices
from backend.router import routers
from backend.router.events import router as event_router
from backend.scheduler import set_scheduled_task_executor, shutdown_scheduler
from backend.service.chat import ChatService
from backend.service.events import WebSocketEvents
from backend.service.window import WindowService

MAX_MESSAGE_BYTES = 70 * 1024 * 1024


def create_app(
    *,
    directory: Path,
    token: str,
    origin: str,
    events: WebSocketEvents | None = None,
    window: WindowService | None = None,
    chat_factory: Callable[..., ChatService] = ChatService,
) -> FastAPI:
    """Own SDK clients and scheduled work in the ASGI lifespan."""
    events = events or WebSocketEvents()
    window = window or WindowService()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        services = ApplicationServices(chat=chat_factory(event_sink=events.publish), window=window)
        app.state.services = services
        try:
            yield
        finally:
            shutdown_scheduler()
            set_scheduled_task_executor(None)
            await services.shutdown()
            await logger.complete()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token
    app.state.origin = origin
    app.state.events = events
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1"])

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": [{"loc": item["loc"], "msg": item["msg"], "type": item["type"]} for item in error.errors()]
            },
        )

    @app.exception_handler(ValueError)
    @app.exception_handler(TypeError)
    async def invalid_parameter(_request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @app.exception_handler(Exception)
    async def internal_error(_request: Request, _error: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": "后端调用失败，请查看错误日志"})

    for router in routers:
        app.include_router(router)
    app.include_router(event_router)
    app.frontend("/", directory=str(directory))
    return app


class LocalWebSocketServer:
    """Bind an ephemeral loopback port before opening the desktop window."""

    def __init__(self, directory: Path, window: WindowService | None = None) -> None:
        self.events = WebSocketEvents()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(128)
        port = self._socket.getsockname()[1]
        self._token = secrets.token_urlsafe(32)
        base_url = URL.build(scheme="http", host="127.0.0.1", port=port)
        self.url = str(base_url.with_path("/").with_fragment(f"token={self._token}"))
        self.app = create_app(
            directory=directory,
            token=self._token,
            origin=str(base_url),
            events=self.events,
            window=window,
        )
        self._server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host="127.0.0.1",
                port=port,
                loop="asyncio",
                http="h11",
                ws="websockets-sansio",
                ws_max_size=MAX_MESSAGE_BYTES,
                access_log=False,
                log_config=None,
                timeout_graceful_shutdown=5,
            )
        )
        self._thread = Thread(
            target=partial(self._server.run, sockets=[self._socket]),
            name="xalling-websocket",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() >= deadline:
                self.stop()
                raise RuntimeError("无法启动本地 WebSocket 服务")
            time.sleep(0.01)

    def stop(self) -> None:
        self._server.should_exit = True
        if self._thread.is_alive():
            self._thread.join(timeout=10)
        self._socket.close()
