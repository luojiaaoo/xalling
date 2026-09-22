import asyncio
import inspect
from pathlib import Path

import pytest
from loguru import logger

from backend.router import log
from backend.router.log import LogRouter, capture_bridge_api_errors, capture_bridge_errors
from main import ApplicationBridge


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


def test_capture_bridge_errors_logs_to_console_and_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_directory = tmp_path / ".xalling" / "log"
    error_log = log_directory / "error.log"
    access_log = log_directory / "access.log"
    configure_test_logging(log_directory, monkeypatch)

    @capture_bridge_errors
    def fail() -> None:
        raise ValueError("bridge failed")

    with pytest.raises(ValueError, match="bridge failed"):
        fail()

    logger.complete()  # enqueue=True 时日志异步落盘，先等队列刷完
    console_output = capsys.readouterr().err
    file_output = error_log.read_text(encoding="utf-8")
    for output in (console_output, file_output):
        assert "JS-Python bridge call failed" in output
        assert "ValueError: bridge failed" in output
        assert "test_capture_bridge_errors_logs_to_console_and_file.<locals>.fail" in output
    assert "error=ValueError: bridge failed" in access_log.read_text(encoding="utf-8")


def test_capture_bridge_errors_supports_async_functions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error_log = tmp_path / "error.log"
    configure_test_logging(tmp_path, monkeypatch)

    @capture_bridge_errors
    async def fail() -> None:
        raise RuntimeError("async bridge failed")

    with pytest.raises(RuntimeError, match="async bridge failed"):
        asyncio.run(fail())

    logger.complete()
    assert "RuntimeError: async bridge failed" in error_log.read_text(encoding="utf-8")


def test_capture_bridge_errors_logs_redacted_inputs_and_outputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access_log = tmp_path / "access.log"
    configure_test_logging(tmp_path, monkeypatch)

    @capture_bridge_errors
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

    LogRouter().report_frontend_error(
        "unhandledrejection",
        "frontend failed",
        "Error: frontend failed\n    at app.js:1:1",
    )

    logger.complete()
    browser_output = browser_log.read_text(encoding="utf-8")
    assert "Frontend unhandledrejection: frontend failed" in browser_output
    assert "at app.js:1:1" in browser_output
    assert "frontend failed" not in error_log.read_text(encoding="utf-8")


def test_capture_bridge_api_errors_wraps_inherited_public_methods(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_test_logging(tmp_path, monkeypatch)

    class Router:
        def exposed(self) -> str:
            return "ok"

        @staticmethod
        def static_exposed() -> str:
            return "static"

        def _internal(self) -> None:
            raise RuntimeError

    @capture_bridge_api_errors
    class Bridge(Router):
        pass

    bridge = Bridge()

    assert bridge.exposed() == "ok"
    assert bridge.static_exposed() == "static"
    assert getattr(bridge.exposed, "__bridge_error_captured__", False)
    assert getattr(bridge.static_exposed, "__bridge_error_captured__", False)
    assert not getattr(bridge._internal, "__bridge_error_captured__", False)


def test_application_bridge_captures_every_public_method() -> None:
    public_methods = [
        name
        for name in dir(ApplicationBridge)
        if not name.startswith("_")
        and inspect.isroutine(inspect.getattr_static(ApplicationBridge, name))
    ]

    assert public_methods
    assert all(
        getattr(getattr(ApplicationBridge, name), "__bridge_error_captured__", False)
        for name in public_methods
    )
