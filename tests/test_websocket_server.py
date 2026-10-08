"""Native FastAPI contracts, event-loop ownership and desktop lifecycle."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.sync.client import connect
from yarl import URL

from backend.application import ApplicationServices
from backend.service.chat import ChatService
from backend.service.events import WebSocketEvents
from backend.service.window import WindowService
from backend.websocket_server import LocalWebSocketServer, create_app

ORIGIN = "http://127.0.0.1:8765"
TOKEN = "test-connection-credential"
PROTOCOLS = ["xalling", f"auth.{TOKEN}"]
AUTH = {"authorization": f"Bearer {TOKEN}", "origin": ORIGIN}


class ChatStub(ChatService):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.started = Event()
        self.release = asyncio.Event()
        self.closed = False
        self.disconnected = Event()
        self.calls: list[int] = []
        self.permission = False

    async def send_chat_message(self, prompt, **kwargs):
        self.calls.append(get_ident())
        self.started.set()
        await self.release.wait()
        assert await self._event_sink(
            {"event": "turn.completed", "data": {"content": prompt}, "session_id": kwargs["session_id"]}
        )
        return {"content": prompt}

    async def stop_chat_message(self, session_id=None):
        self.calls.append(get_ident())
        self.release.set()
        return True

    def respond_chat_permission(self, **kwargs):
        self.calls.append(get_ident())
        self.permission = kwargs["allowed"]
        return True

    def deny_pending_permissions(self):
        self.calls.append(get_ident())
        self.disconnected.set()

    async def shutdown_clients(self):
        self.calls.append(get_ident())
        self.closed = True


@pytest.fixture
def transport(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.service.log._ensure_logging_configured", lambda: None)
    (tmp_path / "index.html").write_text("<html>Xalling</html>", encoding="utf-8")
    app = create_app(directory=tmp_path, token=TOKEN, origin=ORIGIN, chat_factory=ChatStub)
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        yield client, app


@pytest.mark.parametrize(
    ("protocols", "origin"),
    [([], ORIGIN), (["xalling", "auth.wrong"], ORIGIN), (PROTOCOLS, "https://evil.example"), (PROTOCOLS, "null")],
)
def test_event_connection_authentication(transport, protocols, origin):
    client, _ = transport
    with (
        pytest.raises(WebSocketDisconnect) as error,
        client.websocket_connect("ws://127.0.0.1:8765/ws", subprotocols=protocols, headers={"origin": origin}),
    ):
        pass
    assert error.value.code == 1008


def test_http_routes_authentication_and_safe_errors(transport, monkeypatch):
    client, _ = transport
    assert "Xalling" in client.get("/").text
    assert client.get("/", headers={"host": "evil.example"}).status_code == 400
    assert client.get("/api/window/home-folder").status_code == 401
    assert client.get("/api/window/home-folder", headers={**AUTH, "origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/window/home-folder", headers=AUTH).status_code == 200
    for body in [{"width": "10", "height": 20, "edge": "e"}, {"width": 10, "height": 20, "edge": "e", "unexpected": 1}]:
        assert client.post("/api/window/resize", headers=AUTH, json=body).status_code == 422
    assert client.put("/api/theme", headers=AUTH, json={"name": "invalid-theme"}).status_code == 400
    monkeypatch.setattr(
        "backend.service.theme.ThemeService.get_current_theme",
        lambda: (_ for _ in ()).throw(RuntimeError("api_key=secret")),
    )
    response = client.get("/api/theme", headers=AUTH)
    assert response.status_code == 500
    assert "secret" not in response.text
    assert (
        client.post("/api/chat/permissions", headers=AUTH, json={"permission_id": "test", "allowed": "yes"}).status_code
        == 422
    )
    assert (
        client.post("/api/models/remote-names", headers=AUTH, json={"api_url": 42, "api_key": "secret"}).status_code
        == 422
    )


def test_long_http_chat_stop_permission_and_events_share_asgi_loop(transport):
    client, app = transport
    chat = app.state.services.chat
    with (
        client.websocket_connect(
            "ws://127.0.0.1:8765/ws", subprotocols=PROTOCOLS, headers={"origin": ORIGIN}
        ) as websocket,
        ThreadPoolExecutor() as workers,
    ):
        result = workers.submit(
            client.post, "/api/chat/messages", headers=AUTH, json={"prompt": "hello", "session_id": "session-1"}
        )
        assert chat.started.wait(timeout=3)
        assert (
            client.post("/api/chat/permissions", headers=AUTH, json={"permission_id": "test", "allowed": True}).json()
            is True
        )
        assert client.post("/api/chat/stop", headers=AUTH, json={"session_id": "session-1"}).json() is True
        event = websocket.receive_json()
        assert event["type"] == "event"
        assert event["data"]["data"]["content"] == "hello"
        assert result.result(timeout=3).json() == {"content": "hello"}
    assert chat.disconnected.wait(timeout=3)
    assert len(set(chat.calls)) == 1
    assert chat.permission


def test_model_site_names_are_not_interpreted_as_url_paths(transport, monkeypatch):
    client, _ = transport
    received = []

    async def delete_site(name):
        received.append(name)

    monkeypatch.setattr("backend.service.model.ModelService.delete_model_site", delete_site)
    name = "group/../供应商 ?#"
    response = client.delete("/api/models/sites", params={"name": name}, headers=AUTH)
    assert response.status_code == 200
    assert received == [name]


def test_websocket_rejects_old_rpc_messages(transport):
    client, _ = transport
    with client.websocket_connect(
        "ws://127.0.0.1:8765/ws", subprotocols=PROTOCOLS, headers={"origin": ORIGIN}
    ) as websocket:
        websocket.send_json({"type": "request", "id": "1", "method": "get_current_theme"})
        with pytest.raises(WebSocketDisconnect) as error:
            websocket.receive_json()
        assert error.value.code == 1008


@pytest.mark.anyio
async def test_http_cancellation_retains_turn_and_lifespan_stops_owned_work():
    class Chat:
        def __init__(self):
            self.started = asyncio.Event()
            self.finished = False
            self.closed = False

        async def send_chat_message(self, **parameters):
            self.started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.finished = True

        def deny_pending_permissions(self):
            pass

        async def shutdown_clients(self):
            self.closed = True

    chat = Chat()
    services = ApplicationServices(chat=chat, window=WindowService())
    caller = asyncio.create_task(services.send_chat_message(prompt="hello"))
    await chat.started.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert services.tasks
    assert not chat.finished
    await services.shutdown()
    assert chat.finished and chat.closed
    assert not services.tasks


def test_local_server_and_desktop_bootstrap(tmp_path, monkeypatch):
    import main

    captured: dict[str, Any] = {}
    minimized = Event()

    class Window:
        def minimize(self):
            minimized.set()

    def create_window(_title, **options):
        captured.update(options)
        return Window()

    def start(**options):
        url = URL(captured["url"])
        token = url.fragment.removeprefix("token=")
        with connect(
            str(url.with_scheme("ws").with_path("/ws").with_fragment("")),
            origin=str(url.origin()),
            subprotocols=["xalling", f"auth.{token}"],
            proxy=None,
            open_timeout=3,
            close_timeout=3,
        ):
            response = httpx.post(
                str(url.with_path("/api/window/minimize").with_fragment("")),
                headers={"authorization": f"Bearer {token}", "origin": str(url.origin())},
                timeout=3,
                trust_env=False,
            )
            assert response.status_code == 200
            assert minimized.is_set()

    monkeypatch.setattr(main, "hide_claude_console_windows", lambda: None)
    monkeypatch.setattr(main.webview, "create_window", create_window)
    monkeypatch.setattr(main.webview, "start", start)
    main.main()
    assert "js_api" not in captured
    assert URL(captured["url"]).host == "127.0.0.1"
    (tmp_path / "index.html").write_text("Xalling", encoding="utf-8")
    server = LocalWebSocketServer(tmp_path)
    server.start()
    services = server.app.state.services
    server.stop()
    assert services.closing
    assert not server._thread.is_alive()
    assert server._socket.fileno() == -1


@pytest.mark.anyio
async def test_event_delivery_reports_no_ui():
    events = WebSocketEvents()
    assert not await events.publish({"event": "permission.requested"})
