"""Headless startup, console output and server cleanup."""

from unittest.mock import Mock

import pytest

import main


@pytest.fixture
def headless_startup(tmp_path, monkeypatch):
    index = tmp_path / "frontend" / "dist" / "index.html"
    index.parent.mkdir(parents=True)
    index.write_text("Xalling", encoding="utf-8")
    monkeypatch.setattr(main, "__file__", str(tmp_path / "main.py"))
    monkeypatch.setattr(main, "hide_claude_console_windows", Mock())
    logging = Mock()
    monkeypatch.setattr(main, "configure_logging", logging)
    server = Mock(url="http://127.0.0.1:8765/?token=test-token")
    monkeypatch.setattr(main, "LocalWebSocketServer", Mock(return_value=server))
    create_window, start_window = Mock(), Mock()
    monkeypatch.setattr(main.webview, "create_window", create_window)
    monkeypatch.setattr(main.webview, "start", start_window)
    return server, logging, create_window, start_window


def test_headless_prints_only_url_and_stops_on_ctrl_c(headless_startup, capsys):
    server, logging, create_window, start_window = headless_startup
    server.wait.side_effect = KeyboardInterrupt
    main.main(headless=True)
    assert capsys.readouterr() == (f"{server.url}\n", "")
    logging.assert_called_once_with(console=False)
    server.start.assert_called_once_with()
    server.stop.assert_called_once_with()
    create_window.assert_not_called()
    start_window.assert_not_called()


def test_desktop_initializes_loguru_with_console_output(headless_startup):
    server, logging, create_window, start_window = headless_startup
    main.main()
    logging.assert_called_once_with(console=True)
    create_window.assert_called_once()
    start_window.assert_called_once()
    server.wait.assert_not_called()
    server.stop.assert_called_once_with()


@pytest.mark.parametrize("failure_at", ["start", "wait"])
def test_headless_cleans_up_after_server_failure(headless_startup, capsys, failure_at):
    server, _, create_window, start_window = headless_startup
    getattr(server, failure_at).side_effect = RuntimeError("server failed")
    with pytest.raises(RuntimeError, match="server failed"):
        main.main(headless=True)
    assert capsys.readouterr() == ("" if failure_at == "start" else f"{server.url}\n", "")
    server.stop.assert_called_once_with()
    create_window.assert_not_called()
    start_window.assert_not_called()
