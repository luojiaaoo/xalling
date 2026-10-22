import logging
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from loguru import logger

from backend.service.desktop import log
from backend.service.desktop.log import LogService
from backend.websocket_server import create_app


@pytest.fixture(autouse=True)
def close_test_log_sinks():
    yield
    # Do not retain console sinks pointing at a completed test's captured stream.
    logger.complete()
    logger.remove()


def configure_test_logging(
    log_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Point every application log path at one isolated test directory."""
    monkeypatch.setattr(log, "LOG_DIRECTORY", log_directory)
    monkeypatch.setattr(log, "BROWSER_LOG_FILEPATH", log_directory / "browser.log")
    monkeypatch.setattr(log, "ERROR_LOG_FILEPATH", log_directory / "error.log")
    monkeypatch.setattr(log, "CLAUDE_SDK_FILEPATH", log_directory / "claude-sdk.log")
    monkeypatch.setattr(log, "OTHER_LOG_FILEPATH", log_directory / "other.log")
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(root, "level", logging.INFO)
    for name in ("uvicorn", "pywebview"):
        library_logger = logging.getLogger(name)
        monkeypatch.setattr(library_logger, "handlers", list(library_logger.handlers))
        monkeypatch.setattr(library_logger, "propagate", library_logger.propagate)
    log.configure_logging()


def test_only_console_channel_reaches_terminal_and_other_logs_stay_in_files(tmp_path, monkeypatch, capsys):
    configure_test_logging(tmp_path, monkeypatch)
    link = "http://127.0.0.1:8765/?token=private-launch-token"
    log.console_logger.info(link)
    logger.debug("debug details")
    logger.info("ordinary log details")
    log.error_logger.error("application error")
    logging.getLogger("uvicorn.error").info("server started")
    logging.getLogger("uvicorn.error").error("server error")
    logging.getLogger("pywebview").info("native window message")
    logger.complete()
    captured = capsys.readouterr()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \| " + re.escape(link) + r"\n", captured.out)
    assert captured.err == ""
    errors = (tmp_path / "error.log").read_text(encoding="utf-8")
    other = (tmp_path / "other.log").read_text(encoding="utf-8")
    assert not (tmp_path / "access.log").exists()
    assert "application error" in errors and "server error" not in errors
    assert "native window message" in other and "server started" in other and "server error" in other
    assert all("private-launch-token" not in path.read_text(encoding="utf-8") for path in tmp_path.glob("*.log"))


def test_windowed_build_without_standard_streams_keeps_file_logging(tmp_path, monkeypatch, capsys):
    with monkeypatch.context() as streams:
        streams.setattr(log.sys, "stdout", None)
        streams.setattr(log.sys, "stderr", None)
        configure_test_logging(tmp_path, monkeypatch)
        log.console_logger.info("connection link")
        logging.getLogger("pywebview").info("windowed message")
        logger.complete()
    assert capsys.readouterr() == ("", "")
    assert "windowed message" in (tmp_path / "other.log").read_text(encoding="utf-8")


def test_windowed_gbk_nul_streams_are_skipped_without_changing_encoding(tmp_path, monkeypatch, capsys):
    # pywebview creates these streams when Python starts without a console.
    with (
        open(os.devnull, "w", encoding="gbk") as stdout,
        open(os.devnull, "w", encoding="gbk") as stderr,
        monkeypatch.context() as streams,
    ):
        streams.setattr(log.sys, "stdout", stdout)
        streams.setattr(log.sys, "stderr", stderr)
        configure_test_logging(tmp_path, monkeypatch)
        assert stdout.encoding == stderr.encoding == "gbk"
        assert stdout.errors == stderr.errors == "strict"
        # 即使控制台写入函数收到 NUL 流，也只转义当前日志，不修改流。
        log._write_console("Unicode output: 😊")
        log.console_logger.info("Xalling 😊")
        log.other_logger.info("history reply: 你好 😊")
        logging.getLogger("pywebview").info("Unicode status: ℹ 😊")
        logger.complete()
        assert stdout.errors == stderr.errors == "strict"
    assert capsys.readouterr() == ("", "")
    assert "你好 😊" in (tmp_path / "other.log").read_text(encoding="utf-8")
    assert "ℹ 😊" in (tmp_path / "other.log").read_text(encoding="utf-8")


def test_gbk_console_escapes_emoji_and_excludes_history(tmp_path, monkeypatch):
    with (
        (tmp_path / "terminal.log").open("w", encoding="gbk") as stdout,
        open(os.devnull, "w", encoding="gbk") as stderr,
        monkeypatch.context() as streams,
    ):
        streams.setattr(log.sys, "stdout", stdout)
        streams.setattr(log.sys, "stderr", stderr)
        configure_test_logging(tmp_path, monkeypatch)
        log.console_logger.info("Xalling 连接地址 😊")
        log.other_logger.info("history reply: 你好 😊")
        logger.complete()
        assert stdout.encoding == "gbk"
        assert stdout.errors == stderr.errors == "strict"
    assert (tmp_path / "terminal.log").read_text(encoding="gbk").strip().endswith("Xalling 连接地址 \\U0001f60a")
    assert "你好 😊" in (tmp_path / "other.log").read_text(encoding="utf-8")


def test_utf8_console_preserves_emoji_without_changing_stream(tmp_path, monkeypatch):
    with (tmp_path / "terminal.log").open("w", encoding="utf-8") as stdout, monkeypatch.context() as streams:
        streams.setattr(log.sys, "stdout", stdout)
        configure_test_logging(tmp_path, monkeypatch)
        log.console_logger.info("连接地址 😊")
        logger.complete()
        assert stdout.encoding == "utf-8"
        assert stdout.errors == "strict"
    assert (tmp_path / "terminal.log").read_text(encoding="utf-8").strip().endswith("连接地址 😊")


def test_frontend_errors_log_to_separate_browser_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser_log = tmp_path / "browser.log"
    error_log = tmp_path / "error.log"
    configure_test_logging(tmp_path, monkeypatch)

    LogService().report_frontend_error(
        "unhandledrejection",
        "frontend failed",
        "Error: frontend failed\n    at app.js:1:1",
    )

    logger.complete()
    browser_output = browser_log.read_text(encoding="utf-8")
    assert "Frontend unhandledrejection: frontend failed" in browser_output
    assert "at app.js:1:1" in browser_output
    assert "frontend failed" not in error_log.read_text(encoding="utf-8")


def test_launch_token_does_not_enter_business_log_files(tmp_path, monkeypatch):
    configure_test_logging(tmp_path, monkeypatch)
    origin = "http://127.0.0.1:8765"
    launch = "private-single-use-token"
    (tmp_path / "index.html").write_text("Xalling", encoding="utf-8")
    app = create_app(directory=tmp_path, token=launch)
    with TestClient(app, base_url=origin) as client:
        assert client.get("/", params={"token": launch}).status_code == 200
        assert client.get(
            "/api/window/home-folder",
            headers={"Authorization": f"Bearer {launch}", "origin": origin},
        ).status_code == 200
        assert client.get("/", params={"token": launch}).status_code == 401
    logger.complete()
    for filename in ("error.log", "browser.log", "claude-sdk.log"):
        content = (tmp_path / filename).read_text(encoding="utf-8")
        assert launch not in content
