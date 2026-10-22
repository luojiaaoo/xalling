"""Token-authenticated FastAPI server, lifespan and WebSocket events."""

from __future__ import annotations

import secrets
import socket
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from threading import Thread

import psutil
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from yarl import URL

from backend.application import ApplicationServices
from backend.router import routers
from backend.router.events import router as event_router
from backend.service.chat.events import WebSocketEvents
from backend.service.chat.service import ChatService
from backend.service.desktop.window import WindowService
from backend.service.scheduling.service import set_scheduled_task_executor, shutdown_scheduler

MAX_MESSAGE_BYTES = 70 * 1024 * 1024


def create_app(
    *,
    directory: Path,
    token: str,
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
    app.state.first_access = True
    app.state.events = events

    @app.middleware("http")
    async def protect_launch_link(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        supplied = request.query_params.getlist("token")
        rejection: tuple[int, str] | None = None
        if supplied:
            if request.method != "GET" or request.url.path != "/":
                rejection = (401, "此请求不支持 query 认证")
            elif (
                not app.state.first_access
                or len(supplied) != 1
                or not app.state.token
                or not secrets.compare_digest(supplied[0].encode(), app.state.token.encode())
            ):
                rejection = (401, "连接链接无效或已使用")
            else:
                # Check and consume on the ASGI loop before yielding to another request.
                app.state.first_access = False

        if rejection is not None:
            status_code, detail = rejection
            response = JSONResponse(status_code=status_code, content={"detail": detail})
        else:
            response = await call_next(request)
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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
    """Bind an ephemeral port on all IPv4 interfaces before opening the UI."""

    def __init__(self, directory: Path, window: WindowService) -> None:
        self.events = WebSocketEvents()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind(("0.0.0.0", 0))
        self._socket.listen(128)
        port = self._socket.getsockname()[1]
        token = secrets.token_urlsafe(32)
        base_url = URL.build(scheme="http", host="127.0.0.1", port=port)
        self.url = str(base_url.with_path("/").with_query(token=token))
        self.app = create_app(
            directory=directory,
            token=token,
            events=self.events,
            window=window,
        )
        self._server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host="0.0.0.0",
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
        # 让远程浏览器也能关闭后端服务
        window.bind_shutdown(self.request_shutdown)
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

    def connection_urls(self) -> list[str]:
        """Return launch links for every configured local IPv4 address."""
        addresses = {"127.0.0.1"}
        addresses.update(
            address.address
            for interface in psutil.net_if_addrs().values()
            for address in interface
            if address.family == socket.AF_INET and address.address != "0.0.0.0"
        )
        url = URL(self.url)
        return [self.url, *(str(url.with_host(host)) for host in sorted(addresses - {url.host}))]

    def stop(self) -> None:
        self.request_shutdown()
        if self._thread.is_alive():
            self._thread.join(timeout=10)
        self._socket.close()

    def request_shutdown(self) -> None:
        """Let Uvicorn finish the close response before exiting its event loop."""
        self._server.should_exit = True

    def wait(self) -> None:
        """Keep headless mode alive while allowing Ctrl+C on the main thread."""
        while self._thread.is_alive():
            time.sleep(0.2)
