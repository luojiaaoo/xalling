"""Headless startup, console output and server cleanup."""

from unittest.mock import MagicMock, Mock

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
    instance = Mock()
    instance.acquire.return_value = True
    monkeypatch.setattr(main, "SingleInstance", Mock(return_value=instance))
    server = Mock(url="http://127.0.0.1:8765/?token=test-token")
    server.connection_urls.return_value = [server.url, "http://192.168.1.10:8765/?token=test-token"]
    monkeypatch.setattr(main, "console_logger", Mock())
    monkeypatch.setattr(main, "LocalWebSocketServer", Mock(return_value=server))
    create_window, start_window = Mock(), Mock()
    create_window.return_value = MagicMock()
    shown = create_window.return_value.events.shown
    shown.__iadd__.return_value = shown
    monkeypatch.setattr(main.webview, "create_window", create_window)
    monkeypatch.setattr(main.webview, "start", start_window)
    return server, logging, create_window, start_window


def test_headless_logs_all_connection_urls_and_stops_on_ctrl_c(headless_startup, capsys):
    server, logging, create_window, start_window = headless_startup
    server.wait.side_effect = KeyboardInterrupt
    main.main(headless=True)
    assert capsys.readouterr() == ("", "")
    main.console_logger.info.assert_called_once()
    message = main.console_logger.info.call_args.args[0]
    assert message.startswith("Xalling 连接地址\n")
    assert "首次授权后全部失效" in message
    assert all(url in message for url in server.connection_urls.return_value)
    logging.assert_called_once_with()
    server.start.assert_called_once_with()
    server.stop.assert_called_once_with()
    create_window.assert_not_called()
    start_window.assert_not_called()


def test_desktop_uses_same_console_channel_and_connection_urls(headless_startup):
    server, logging, create_window, start_window = headless_startup
    main.main()
    logging.assert_called_once_with()
    main.console_logger.info.assert_called_once()
    message = main.console_logger.info.call_args.args[0]
    assert message.startswith("Xalling 连接地址\n")
    assert "首次授权后全部失效" in message
    assert all(url in message for url in server.connection_urls.return_value)
    create_window.assert_called_once()
    start_window.assert_called_once()
    server.wait.assert_not_called()
    server.stop.assert_called_once_with()
    instance = main.SingleInstance.return_value
    shown = create_window.return_value.events.shown.__iadd__.call_args.args[0]
    shown()
    instance.start.assert_called_once()
    instance.close.assert_called_once_with()


@pytest.mark.parametrize("headless", [False, True])
def test_duplicate_launch_does_not_initialize_runtime(headless_startup, headless):
    server, logging, create_window, start_window = headless_startup
    instance = main.SingleInstance.return_value
    instance.acquire.return_value = False
    main.main(headless=headless)
    logging.assert_not_called()
    main.hide_claude_console_windows.assert_not_called()
    main.LocalWebSocketServer.assert_not_called()
    server.start.assert_not_called()
    create_window.assert_not_called()
    start_window.assert_not_called()
    instance.close.assert_called_once_with()


def test_lock_failure_does_not_start_a_second_runtime(headless_startup):
    _, logging, create_window, _ = headless_startup
    instance = main.SingleInstance.return_value
    instance.acquire.side_effect = OSError("系统锁访问失败")
    with pytest.raises(OSError, match="系统锁访问失败"):
        main.main()
    logging.assert_not_called()
    main.LocalWebSocketServer.assert_not_called()
    create_window.assert_not_called()
    instance.close.assert_called_once_with()


@pytest.mark.parametrize("failure_at", ["start", "wait"])
def test_headless_cleans_up_after_server_failure(headless_startup, capsys, failure_at):
    server, _, create_window, start_window = headless_startup
    getattr(server, failure_at).side_effect = RuntimeError("server failed")
    with pytest.raises(RuntimeError, match="server failed"):
        main.main(headless=True)
    assert capsys.readouterr() == ("", "")
    assert main.console_logger.info.call_count == (0 if failure_at == "start" else 1)
    server.stop.assert_called_once_with()
    main.SingleInstance.return_value.close.assert_called_once_with()
    create_window.assert_not_called()
    start_window.assert_not_called()
