"""Access and error logging for the JavaScript-Python bridge."""

import inspect
import sys
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any, cast

from loguru import logger

LOG_DIRECTORY = Path.home() / ".xalling" / "log"
LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
SENSITIVE_KEY_PARTS = ("api_key", "authorization", "password", "secret", "token")

_logging_configured = False
_access_logger = logger.bind(channel="access")
_error_logger = logger.bind(channel="error")


def configure_logging(log_directory: Path = LOG_DIRECTORY) -> None:
    """Clear Loguru's defaults and add console, access, and error channels."""
    global _logging_configured

    log_directory.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format=LOG_FORMAT,
        backtrace=True,
        diagnose=False,
    )
    logger.add(
        log_directory / "access.log",
        level="INFO",
        format=LOG_FORMAT,
        encoding="utf-8",
        backtrace=True,
        diagnose=False,
        filter=lambda record: record["extra"].get("channel") == "access",
    )
    logger.add(
        log_directory / "error.log",
        level="ERROR",
        format=LOG_FORMAT,
        encoding="utf-8",
        backtrace=True,
        diagnose=False,
        filter=lambda record: record["extra"].get("channel") == "error",
    )
    _logging_configured = True


def _ensure_logging_configured() -> None:
    if not _logging_configured:
        configure_logging()


def _is_sensitive_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.casefold().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _redact(value: Any, key: object = None) -> Any:
    if _is_sensitive_key(key):
        return "<redacted>"
    if isinstance(value, dict):
        return {
            item_key: _redact(item_value, item_key)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


def _call_input(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    arguments = dict(inspect.signature(func).bind_partial(*args, **kwargs).arguments)
    arguments.pop("self", None)
    arguments.pop("cls", None)
    return _redact(arguments)


def capture_bridge_errors[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Log a bridge function's input, output, and exceptions."""
    if getattr(func, "__bridge_error_captured__", False):
        return func

    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            _ensure_logging_configured()
            _access_logger.info(
                f"JS-Python call: {func.__qualname__} | "
                f"input={_call_input(func, args, kwargs)!r}"
            )
            try:
                result = await func(*args, **kwargs)
            except Exception as error:
                _access_logger.info(
                    f"JS-Python result: {func.__qualname__} | "
                    f"error={type(error).__name__}: {error}"
                )
                _error_logger.exception(
                    f"JS-Python bridge call failed: {func.__qualname__}"
                )
                raise
            _access_logger.info(
                f"JS-Python result: {func.__qualname__} | "
                f"output={_redact(result)!r}"
            )
            return result

        async_wrapper.__bridge_error_captured__ = True
        return cast(Callable[P, R], async_wrapper)

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        _ensure_logging_configured()
        _access_logger.info(
            f"JS-Python call: {func.__qualname__} | "
            f"input={_call_input(func, args, kwargs)!r}"
        )
        try:
            result = func(*args, **kwargs)
        except Exception as error:
            _access_logger.info(
                f"JS-Python result: {func.__qualname__} | "
                f"error={type(error).__name__}: {error}"
            )
            _error_logger.exception(
                f"JS-Python bridge call failed: {func.__qualname__}"
            )
            raise
        _access_logger.info(
            f"JS-Python result: {func.__qualname__} | "
            f"output={_redact(result)!r}"
        )
        return result

    wrapper.__bridge_error_captured__ = True
    return wrapper


def capture_bridge_api_errors[T: type[Any]](cls: T) -> T:
    """Apply bridge logging to every public method on an API class."""
    for name in dir(cls):
        if name.startswith("_"):
            continue

        descriptor = inspect.getattr_static(cls, name)
        if isinstance(descriptor, staticmethod):
            wrapped = staticmethod(capture_bridge_errors(descriptor.__func__))
        elif isinstance(descriptor, classmethod):
            wrapped = classmethod(capture_bridge_errors(descriptor.__func__))
        elif inspect.isfunction(descriptor):
            wrapped = capture_bridge_errors(descriptor)
        else:
            continue
        setattr(cls, name, wrapped)

    return cls
