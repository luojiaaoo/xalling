import asyncio
import inspect
from pathlib import Path

import pytest

from backend.router import log
from backend.router.log import capture_bridge_api_errors, capture_bridge_errors
from main import ApplicationBridge


def test_capture_bridge_errors_logs_to_console_and_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    log_directory = tmp_path / ".xalling" / "log"
    error_log = log_directory / "error.log"
    access_log = log_directory / "access.log"
    log.configure_logging(log_directory)

    @capture_bridge_errors
    def fail() -> None:
        raise ValueError("bridge failed")

    with pytest.raises(ValueError, match="bridge failed"):
        fail()

    console_output = capsys.readouterr().err
    file_output = error_log.read_text(encoding="utf-8")
    for output in (console_output, file_output):
        assert "JS-Python bridge call failed" in output
        assert "ValueError: bridge failed" in output
        assert "test_capture_bridge_errors_logs_to_console_and_file.<locals>.fail" in output
    assert "error=ValueError: bridge failed" in access_log.read_text(encoding="utf-8")


def test_capture_bridge_errors_supports_async_functions(
    tmp_path: Path,
) -> None:
    error_log = tmp_path / "error.log"
    log.configure_logging(tmp_path)

    @capture_bridge_errors
    async def fail() -> None:
        raise RuntimeError("async bridge failed")

    with pytest.raises(RuntimeError, match="async bridge failed"):
        asyncio.run(fail())

    assert "RuntimeError: async bridge failed" in error_log.read_text(encoding="utf-8")


def test_capture_bridge_errors_logs_redacted_inputs_and_outputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    access_log = tmp_path / "access.log"
    log.configure_logging(tmp_path)

    @capture_bridge_errors
    def exchange(prompt: str, api_key: str) -> dict[str, str]:
        return {"answer": prompt.upper(), "api_key": api_key}

    assert exchange("hello", "top-secret") == {
        "answer": "HELLO",
        "api_key": "top-secret",
    }

    console_output = capsys.readouterr().err
    file_output = access_log.read_text(encoding="utf-8")
    for output in (console_output, file_output):
        assert "input={'prompt': 'hello', 'api_key': '<redacted>'}" in output
        assert "output={'answer': 'HELLO', 'api_key': '<redacted>'}" in output
        assert "top-secret" not in output


def test_capture_bridge_api_errors_wraps_inherited_public_methods(
    tmp_path: Path,
) -> None:
    log.configure_logging(tmp_path)

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
