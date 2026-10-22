"""Native FastAPI contracts, event-loop ownership and desktop lifecycle."""

import asyncio
import socket
from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.sync.client import connect
from yarl import URL

from backend.application import ApplicationServices
from backend.service.chat.events import WebSocketEvents
from backend.service.chat.service import ChatService
from backend.service.desktop.window import WindowService
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
def transport(tmp_path):
    (tmp_path / "index.html").write_text("<html>Xalling</html>", encoding="utf-8")
    app = create_app(directory=tmp_path, token=TOKEN, chat_factory=ChatStub)
    app.state.first_access = False  # Simulate an already-authorized connection for API tests.
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        yield client, app


def test_mcp_status_authentication_validation_and_missing_client(transport):
    client, _ = transport
    path = "/api/chat/sessions/00000000-0000-0000-0000-000000000001/mcp"
    assert client.get(path).status_code == 401
    response = client.get(path, headers=AUTH)
    assert response.status_code == 200
    assert response.json() is None
    assert client.get("/api/chat/sessions/invalid/mcp", headers=AUTH).status_code == 400
    assert client.get(f"/api/chat/sessions/{'a' * 129}/mcp", headers=AUTH).status_code == 422


def test_mcp_status_returns_live_result_and_sanitizes_errors(transport, monkeypatch):
    client, app = transport
    path = "/api/chat/sessions/00000000-0000-0000-0000-000000000001/mcp"
    status = {"servers": [{"name": "WebSearch", "status": "pending", "tool_count": None}]}

    async def get_status(session_id):
        assert session_id == "00000000-0000-0000-0000-000000000001"
        return status

    monkeypatch.setattr(app.state.services.chat, "get_mcp_status", get_status)
    assert client.get(path, headers=AUTH).json() == status
    status["servers"][0].update(status="connected", tool_count=3)
    assert client.get(path, headers=AUTH).json() == status

    async def fail(_session_id):
        raise RuntimeError("private-mcp-details")

    monkeypatch.setattr(app.state.services.chat, "get_mcp_status", fail)
    response = client.get(path, headers=AUTH)
    assert response.status_code == 500
    assert "private-mcp-details" not in response.text


def test_mcp_reconnect_authentication_validation_and_missing_client(transport):
    client, _ = transport
    path = "/api/chat/sessions/00000000-0000-0000-0000-000000000001/mcp/reconnect"
    body = {"server_name": "Research"}
    assert client.post(path, json=body).status_code == 401
    response = client.post(path, headers=AUTH, json=body)
    assert response.status_code == 400
    assert client.post("/api/chat/sessions/invalid/mcp/reconnect", headers=AUTH, json=body).status_code == 400
    for invalid in [{}, {"server_name": ""}, {"server_name": 1},
                    {"server_name": "a" * 513}, {"server_name": "Research", "extra": True}]:
        assert client.post(path, headers=AUTH, json=invalid).status_code == 422
    assert client.post(
        f"/api/chat/sessions/{'a' * 129}/mcp/reconnect", headers=AUTH, json=body,
    ).status_code == 422


def test_mcp_reconnect_calls_the_session_service_and_sanitizes_errors(transport, monkeypatch):
    client, app = transport
    session_id = "00000000-0000-0000-0000-000000000001"
    path = f"/api/chat/sessions/{session_id}/mcp/reconnect"
    body = {"server_name": "Research/论文"}
    calls = []

    async def reconnect(session_id, server_name):
        calls.append((session_id, server_name))
        return True

    monkeypatch.setattr(app.state.services.chat, "reconnect_mcp_server", reconnect)
    response = client.post(path, headers=AUTH, json=body)
    assert response.status_code == 200
    assert response.json() is True
    assert calls == [(session_id, "Research/论文")]

    async def fail(session_id, server_name):
        raise RuntimeError("private-mcp-details")

    monkeypatch.setattr(app.state.services.chat, "reconnect_mcp_server", fail)
    response = client.post(path, headers=AUTH, json=body)
    assert response.status_code == 500
    assert "private-mcp-details" not in response.text


def test_mcp_status_remains_available_while_reconnecting(transport, monkeypatch):
    client, app = transport
    path = "/api/chat/sessions/00000000-0000-0000-0000-000000000001/mcp"
    started = Event()
    release = asyncio.Event()

    async def reconnect(session_id, server_name):
        started.set()
        await release.wait()
        return True

    async def status(session_id):
        release.set()
        return {"servers": [{"name": "Research", "status": "pending", "tool_count": None}]}

    monkeypatch.setattr(app.state.services.chat, "reconnect_mcp_server", reconnect)
    monkeypatch.setattr(app.state.services.chat, "get_mcp_status", status)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.post, f"{path}/reconnect", headers=AUTH, json={"server_name": "Research"})
        try:
            assert started.wait(5)
            response = client.get(path, headers=AUTH)
            assert response.json()["servers"][0]["status"] == "pending"
            assert pending.result(timeout=5).json() is True
        finally:
            client.portal.call(release.set)


def test_window_capabilities_require_auth_and_report_headless_mode(transport):
    client, _ = transport
    assert client.get("/api/window/capabilities").status_code == 401
    response = client.get("/api/window/capabilities", headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {"native_window": False}


def test_window_capabilities_enable_native_controls_after_binding(transport):
    client, app = transport
    resized = []
    window = SimpleNamespace(resize=lambda *args: resized.append(args))
    app.state.services.window.bind_window(window)
    assert client.get("/api/window/capabilities", headers=AUTH).json() == {"native_window": True}
    assert client.post(
        "/api/window/resize", headers=AUTH, json={"width": 1200, "height": 800, "edge": "e"},
    ).status_code == 200
    assert resized[0][:2] == (1200, 800)


def test_window_capabilities_sanitize_internal_errors(transport, monkeypatch):
    client, app = transport

    def fail():
        raise RuntimeError("private-window-details")

    monkeypatch.setattr(app.state.services.window, "get_capabilities", fail)
    response = client.get("/api/window/capabilities", headers=AUTH)
    assert response.status_code == 500
    assert "private-window-details" not in response.text


def test_launch_token_is_one_time_and_session_survives_reconnect(transport):
    client, app = transport
    app.state.first_access = True
    headers = AUTH
    assert client.get("/api/window/home-folder", headers=headers).status_code == 401
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("ws://127.0.0.1:8765/ws", subprotocols=PROTOCOLS, headers={"origin": ORIGIN}),
    ):
        pass
    first = client.get("/", params={"token": TOKEN, "view": "chat"})
    assert first.status_code == 200 and "Xalling" in first.text
    assert not first.history
    assert "set-cookie" not in first.headers
    assert first.headers["referrer-policy"] == "no-referrer"
    assert first.headers["cache-control"] == "no-store"
    assert app.state.first_access is False
    assert app.state.token == TOKEN
    assert client.get("/", params={"token": TOKEN}).status_code == 401
    assert client.get("/").status_code == 200
    assert client.get("/api/window/home-folder", headers=headers).status_code == 200
    for _ in range(2):
        with client.websocket_connect("ws://127.0.0.1:8765/ws", subprotocols=PROTOCOLS,
                                      headers={"origin": ORIGIN}):
            pass
    # The public HTML shell cannot access business APIs without the saved header.
    assert client.get("/").status_code == 200
    assert client.get("/", params={"token": TOKEN}).status_code == 401
    assert client.get("/api/window/home-folder").status_code == 401


def test_launch_authorization_rejects_invalid_parameters(transport):
    client, app = transport
    app.state.first_access = True
    for token in ["", "wrong", "中文", "x" * 129]:
        response = client.get("/", params={"token": token})
        assert response.status_code == 401
        assert TOKEN not in response.text
    assert client.post("/", params={"token": TOKEN}).status_code == 401
    assert client.get("/api/window/home-folder", params={"token": TOKEN}, headers=AUTH).status_code == 401
    for values in [[TOKEN, "wrong"], ["wrong", TOKEN], [TOKEN, TOKEN]]:
        assert client.get("/", params=[("token", value) for value in values]).status_code == 401
    assert app.state.first_access is True
    assert client.get("/", params={"token": TOKEN}).status_code == 200


def test_concurrent_launch_token_redemptions_have_one_winner(transport):
    client, app = transport
    app.state.first_access = True

    def redeem(_):
        return client.get("/", params={"token": TOKEN}, follow_redirects=False).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sorted(pool.map(redeem, range(4))) == [200, 401, 401, 401]


@pytest.mark.parametrize(
    ("host", "origin"),
    [("192.168.1.10:8765", "http://192.168.1.10:8765"), ("remote.example", "https://client.example"),
     ("localhost:9999", "null"), ("remote.example:8765", None)],
)
def test_remote_launch_http_and_websocket_require_only_token(transport, host, origin):
    client, app = transport
    app.state.first_access = True
    headers = {"host": host}
    if origin is not None:
        headers["origin"] = origin
    authorized = {**headers, "authorization": f"Bearer {TOKEN}"}
    assert client.get("/api/window/home-folder", headers=authorized).status_code == 401
    assert client.get("/", params={"token": "wrong"}, headers=headers).status_code == 401
    assert app.state.first_access
    assert client.get("/", params={"token": TOKEN}, headers=headers).status_code == 200
    assert client.get("/", params={"token": TOKEN}, headers=headers).status_code == 401
    assert client.get("/api/window/home-folder", headers=headers).status_code == 401
    assert client.get("/api/window/home-folder", headers={**headers, "authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/window/home-folder", headers=authorized).status_code == 200
    with client.websocket_connect(f"ws://{host}/ws", subprotocols=PROTOCOLS, headers=headers.copy()) as websocket:
        assert websocket.accepted_subprotocol == "xalling"
    with (
        pytest.raises(WebSocketDisconnect) as error,
        client.websocket_connect(f"ws://{host}/ws", subprotocols=["xalling", "auth.wrong"], headers=headers.copy()),
    ):
        pass
    assert error.value.code == 1008


def test_cors_preflight_allows_bearer_header_without_bypassing_token_auth(transport):
    client, app = transport
    app.state.first_access = True
    headers = {"host": "remote.example", "origin": "https://client.example"}
    response = client.options("/api/window/home-folder", headers={
        **headers,
        "access-control-request-method": "GET",
        "access-control-request-headers": "authorization,content-type",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "authorization" in response.headers["access-control-allow-headers"]
    assert app.state.first_access
    assert client.get("/api/window/home-folder", headers={**headers, **AUTH}).status_code == 401
    assert client.get("/", params={"token": TOKEN}, headers=headers).status_code == 200
    response = client.get("/api/window/home-folder", headers=headers)
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "*"
    response = client.get("/api/window/home-folder", headers={**headers, "authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_directory_api_browses_backend_without_native_window(transport, tmp_path, monkeypatch):
    client, _ = transport
    folder = tmp_path / "远程项目 #&"
    folder.mkdir()
    (folder / "child").mkdir()
    monkeypatch.setattr("backend.service.desktop.file.default_project_folder", lambda: folder)
    assert client.get("/api/files/directories").status_code == 401
    assert client.get("/api/files/directories", headers={**AUTH, "origin": "https://remote.example"}).status_code == 200
    response = client.get("/api/files/directories", params={"path": str(folder)}, headers=AUTH)
    assert response.status_code == 200
    data = response.json()
    assert data["current"] == {"name": folder.name, "path": str(folder.resolve())}
    assert data["directories"] == [{"name": "child", "path": str(folder / "child")}]
    assert data["parent_path"] == str(tmp_path)
    assert client.get("/api/files/directories", headers=AUTH).json() == data
    assert client.post("/api/window/project-folder", headers=AUTH).status_code == 404


def test_root_directory_api_requires_auth_and_returns_backend_paths(transport, monkeypatch):
    client, _ = transport
    folders = [{"name": "/", "path": "/"}, {"name": "etc", "path": "/etc"}]
    monkeypatch.setattr("backend.service.desktop.file.FileService.list_root_directories", lambda: folders)
    assert client.get("/api/files/roots").status_code == 401
    assert client.get("/api/files/roots", headers={**AUTH, "origin": "https://remote.example"}).status_code == 200
    assert client.get("/api/files/roots", headers=AUTH).json() == folders

    def fail():
        raise RuntimeError("private internal details")

    monkeypatch.setattr("backend.service.desktop.file.FileService.list_root_directories", fail)
    response = client.get("/api/files/roots", headers=AUTH)
    assert response.status_code == 500
    assert "private" not in response.text


def test_directory_api_rejects_invalid_paths_and_sanitizes_errors(transport, tmp_path, monkeypatch):
    client, _ = transport
    for path in ["", "x" * 32769]:
        assert client.get("/api/files/directories", params={"path": path}, headers=AUTH).status_code == 422
    for path in ["relative", str(tmp_path / "missing"), str(tmp_path / "index.html")]:
        assert client.get("/api/files/directories", params={"path": path}, headers=AUTH).status_code == 400

    def fail(_path):
        raise RuntimeError("private internal details")

    monkeypatch.setattr("backend.service.desktop.file.FileService.list_directories", fail)
    response = client.get("/api/files/directories", headers=AUTH)
    assert response.status_code == 500
    assert "private" not in response.text


@pytest.mark.parametrize(
    ("protocols", "origin"),
    [([], ORIGIN), (["xalling", "auth.wrong"], ORIGIN), (["xalling", "auth.wrong"], "https://remote.example"),
     (["xalling"], "null"), ([f"auth.{TOKEN}"], ORIGIN)],
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
    assert "Xalling" in client.get("/", headers=AUTH).text
    assert client.get("/", headers={"host": "remote.example"}).status_code == 200
    assert client.get("/api/window/home-folder").status_code == 401
    assert client.get("/api/window/home-folder", headers={**AUTH, "origin": "https://remote.example"}).status_code == 200
    assert client.get("/api/window/home-folder", headers=AUTH).status_code == 200
    for body in [{"width": "10", "height": 20, "edge": "e"}, {"width": 10, "height": 20, "edge": "e", "unexpected": 1}]:
        assert client.post("/api/window/resize", headers=AUTH, json=body).status_code == 422
    assert client.put("/api/theme", headers=AUTH, json={"name": "invalid-theme"}).status_code == 400
    monkeypatch.setattr(
        "backend.service.settings.theme.ThemeService.get_current_theme",
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
            "ws://127.0.0.1:8765/ws", subprotocols=PROTOCOLS, headers=AUTH
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

    monkeypatch.setattr("backend.service.settings.model.ModelService.delete_model_site", delete_site)
    name = "group/../供应商 ?#"
    response = client.delete("/api/models/sites", params={"name": name}, headers=AUTH)
    assert response.status_code == 200
    assert received == [name]


def test_websocket_rejects_old_rpc_messages(transport):
    client, _ = transport
    with client.websocket_connect(
        "ws://127.0.0.1:8765/ws", subprotocols=PROTOCOLS, headers=AUTH
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
        events = MagicMock()

        def minimize(self):
            minimized.set()

    def create_window(_title, **options):
        captured.update(options)
        return Window()

    def start(**options):
        url = URL(captured["url"])
        assert not url.fragment
        response = httpx.get(
            str(url),
            follow_redirects=False,
            timeout=3,
            trust_env=False,
        )
        assert response.status_code == 200
        token = url.query["token"]
        with connect(
            str(url.with_scheme("ws").with_path("/ws").with_query(None)),
            origin=str(url.origin()),
            subprotocols=["xalling", f"auth.{token}"],
            proxy=None,
            open_timeout=3,
            close_timeout=3,
        ):
            response = httpx.post(
                str(url.with_path("/api/window/minimize").with_query(None)),
                headers={"authorization": f"Bearer {token}", "origin": str(url.origin())},
                timeout=3,
                trust_env=False,
            )
            assert response.status_code == 200
            assert minimized.is_set()

    monkeypatch.setattr(main, "hide_claude_console_windows", lambda: None)
    monkeypatch.setattr(main, "configure_logging", lambda **kwargs: None)
    monkeypatch.setattr(main, "SingleInstance", lambda: Mock(acquire=Mock(return_value=True)))
    monkeypatch.setattr(main.webview, "create_window", create_window)
    monkeypatch.setattr(main.webview, "start", start)
    main.main()
    assert "js_api" not in captured
    assert URL(captured["url"]).host == "127.0.0.1"
    (tmp_path / "index.html").write_text("Xalling", encoding="utf-8")
    server = LocalWebSocketServer(tmp_path, WindowService())
    assert server._socket.getsockname()[0] == "0.0.0.0"
    assert server._server.config.host == "0.0.0.0"
    server.start()
    services = server.app.state.services
    server.stop()
    assert services.closing
    assert not server._thread.is_alive()
    assert server._socket.fileno() == -1


@pytest.mark.parametrize("interface_name", ["Ethernet", "eth0"])
def test_connection_urls_cover_all_ipv4_interfaces_with_one_shared_token(tmp_path, monkeypatch, interface_name):
    monkeypatch.setattr("backend.websocket_server.psutil.net_if_addrs", lambda: {
        interface_name: [
            SimpleNamespace(family=socket.AF_INET, address="192.168.1.10"),
            SimpleNamespace(family=socket.AF_INET, address="10.0.0.2"),
            SimpleNamespace(family=socket.AF_INET6, address="::1"),
            SimpleNamespace(family=socket.AF_INET, address="0.0.0.0"),
        ],
        "loopback": [SimpleNamespace(family=socket.AF_INET, address="127.0.0.1")],
        "virtual": [SimpleNamespace(family=socket.AF_INET, address="192.168.1.10")],
    })
    server = LocalWebSocketServer(tmp_path, WindowService())
    try:
        launch = URL(server.url)
        urls = [URL(url) for url in server.connection_urls()]
        assert [url.host for url in urls] == ["127.0.0.1", "10.0.0.2", "192.168.1.10"]
        assert all(url.port == launch.port and url.query == launch.query and url.path == "/" for url in urls)
        monkeypatch.setattr("backend.websocket_server.psutil.net_if_addrs", dict)
        assert server.connection_urls() == [server.url]
    finally:
        server.stop()


@pytest.mark.parametrize("desktop", [False, True])
def test_close_api_responds_then_stops_server_in_both_modes(tmp_path, desktop):
    destroyed = Event()

    class Window:
        def destroy(self):
            destroyed.set()

    window = WindowService()
    if desktop:
        window.bind_window(Window())
    (tmp_path / "index.html").write_text("Xalling", encoding="utf-8")
    server = LocalWebSocketServer(tmp_path, window)
    try:
        server.start()
        url = URL(server.url)
        with httpx.Client(timeout=3, trust_env=False) as client:
            assert client.get(str(url)).status_code == 200
            response = client.post(str(url.with_path("/api/window/close").with_query(None)),
                                   headers={"authorization": f"Bearer {url.query['token']}", "origin": str(url.origin())})
        assert response.status_code == 200 and response.json() == {"closing": True}
        server._thread.join(timeout=3)
        assert not server._thread.is_alive()
        assert server.app.state.services.closing
        assert destroyed.is_set() == desktop
    finally:
        server.stop()


def test_desktop_closes_window_before_client_cleanup_finishes(tmp_path, monkeypatch):
    cleanup_started, release, destroyed = Event(), Event(), Event()

    class Window:
        def destroy(self):
            destroyed.set()

    window = WindowService()
    window.bind_window(Window())
    (tmp_path / "index.html").write_text("Xalling", encoding="utf-8")
    server = LocalWebSocketServer(tmp_path, window)
    try:
        server.start()
        chat = server.app.state.services.chat
        original_shutdown = chat.shutdown_clients

        async def delayed_shutdown():
            assert destroyed.is_set()
            cleanup_started.set()
            while not release.is_set():
                await asyncio.sleep(0.01)
            await original_shutdown()

        monkeypatch.setattr(chat, "shutdown_clients", delayed_shutdown)
        url = URL(server.url)
        headers = {"authorization": f"Bearer {url.query['token']}", "origin": str(url.origin())}
        with httpx.Client(base_url=str(url.origin()), timeout=3, trust_env=False) as client:
            assert client.get(str(url)).status_code == 200
            assert client.post("/api/window/close", headers=headers).json() == {"closing": True}
            assert cleanup_started.wait(1)
            assert destroyed.is_set()
            assert server._thread.is_alive()
        release.set()
        server._thread.join(timeout=3)
        assert not server._thread.is_alive()
    finally:
        release.set()
        server.stop()


@pytest.mark.anyio
async def test_event_delivery_reports_no_ui():
    events = WebSocketEvents()
    assert not await events.publish({"event": "permission.requested"})
