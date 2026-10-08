import asyncio
from pathlib import Path

import pytest
from loguru import logger

from backend.router import routers
from backend.service import log
from backend.service.log import LogService, capture_api_errors


def configure_test_logging(
    log_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Point every application log path at one isolated test directory."""
    monkeypatch.setattr(log, "LOG_DIRECTORY", log_directory)
    monkeypatch.setattr(log, "ACCESS_LOG_FILEPATH", log_directory / "access.log")
    monkeypatch.setattr(log, "BROWSER_LOG_FILEPATH", log_directory / "browser.log")
    monkeypatch.setattr(log, "ERROR_LOG_FILEPATH", log_directory / "error.log")
    log.configure_logging()


def test_capture_api_errors_logs_to_console_and_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_directory = tmp_path / ".xalling" / "log"
    error_log = log_directory / "error.log"
    access_log = log_directory / "access.log"
    configure_test_logging(log_directory, monkeypatch)

    @capture_api_errors
    def fail() -> None:
        raise ValueError("API failed")

    with pytest.raises(ValueError, match="API failed"):
        fail()

    logger.complete()  # enqueue=True 时日志异步落盘，先等队列刷完
    console_output = capsys.readouterr().err
    file_output = error_log.read_text(encoding="utf-8")
    for output in (console_output, file_output):
        assert "FastAPI call failed" in output
        assert "ValueError: API failed" in output
        assert "test_capture_api_errors_logs_to_console_and_file.<locals>.fail" in output
    assert "error=ValueError: API failed" in access_log.read_text(encoding="utf-8")


def test_capture_api_errors_supports_async_functions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error_log = tmp_path / "error.log"
    configure_test_logging(tmp_path, monkeypatch)

    @capture_api_errors
    async def fail() -> None:
        raise RuntimeError("async API failed")

    with pytest.raises(RuntimeError, match="async API failed"):
        asyncio.run(fail())

    logger.complete()
    assert "RuntimeError: async API failed" in error_log.read_text(encoding="utf-8")


def test_capture_api_errors_logs_redacted_inputs_and_outputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access_log = tmp_path / "access.log"
    configure_test_logging(tmp_path, monkeypatch)

    @capture_api_errors
    def exchange(prompt: str, api_key: str) -> dict[str, str]:
        return {"answer": prompt.upper(), "api_key": api_key}

    assert exchange("hello", "top-secret") == {
        "answer": "HELLO",
        "api_key": "top-secret",
    }

    logger.complete()
    console_output = capsys.readouterr().err
    file_output = access_log.read_text(encoding="utf-8")
    for output in (console_output, file_output):
        assert "input={'prompt': 'hello', 'api_key': '**********'}" in output
        assert "output={'answer': 'HELLO', 'api_key': '**********'}" in output
        assert "top-secret" not in output


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


def test_every_http_endpoint_captures_errors() -> None:
    endpoints = [route.endpoint for router in routers for route in router.routes]
    assert endpoints
    assert all(getattr(endpoint, "__api_error_captured__", False) for endpoint in endpoints)
