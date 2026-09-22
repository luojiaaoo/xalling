"""Application logging channels, file sinks, and bridge-call capture."""

import inspect
import sys
from collections.abc import Callable
from functools import wraps
from typing import Any, cast

from loguru import logger

from backend.config.setting import (
    ACCESS_LOG_FILEPATH,
    BROWSER_LOG_FILEPATH,
    ERROR_LOG_FILEPATH,
    CLAUDE_SDK_FILEPATH,
    LOG_DIRECTORY,
)

LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
SENSITIVE_KEY_PARTS = ("api_key", "authorization", "password", "secret", "token")

# 高频调用、刷日志没意义的桥接方法：不打 call/result 访问日志，但异常仍记录
SILENT_ACCESS_LOG_CALLS = frozenset(
    {
        "WindowRouter.resize_window",   # 无意义
        "ChatRouter.list_chat_sessions",   # 高频
        "ChatRouter.get_context_usage",   # 高频
        "FileRouter.save_attachment",   # 文件保存
        "ChatRouter.get_active_chat",  # 包含大量工具信息
    }
)

_logging_configured = False
access_logger = logger.bind(channel="access")
browser_logger = logger.bind(channel="browser")
error_logger = logger.bind(channel="error")
session_debug_logger = logger.bind(channel="session_debug")
claude_sdk_logger = logger.bind(channel="claude_sdk")


def configure_logging() -> None:
    """Clear Loguru's defaults and add console and file log channels."""
    global _logging_configured

    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format=LOG_FORMAT,
        backtrace=True,
        diagnose=False,
        enqueue=True,
    )
    logger.add(
        ACCESS_LOG_FILEPATH,
        level="INFO",
        format=LOG_FORMAT,
        encoding="utf-8",
        rotation="30 MB",
        retention=4,
        backtrace=True,
        diagnose=False,
        enqueue=True,
        filter=lambda record: record["extra"].get("channel") == "access",
    )
    logger.add(
        ERROR_LOG_FILEPATH,
        level="ERROR",
        format=LOG_FORMAT,
        encoding="utf-8",
        rotation="10 MB",
        retention="180 days",
        backtrace=True,
        diagnose=False,
        enqueue=True,
        filter=lambda record: record["extra"].get("channel") == "error",
    )
    logger.add(
        CLAUDE_SDK_FILEPATH,
        level="INFO",
        format=LOG_FORMAT,
        encoding="utf-8",
        rotation="10 MB",
        retention="14 days",
        backtrace=True,
        diagnose=False,
        enqueue=True,
        filter=lambda record: record["extra"].get("channel") == "claude_sdk",
    )
    logger.add(
        BROWSER_LOG_FILEPATH,
        level="ERROR",
        format=LOG_FORMAT,
        encoding="utf-8",
        rotation="10 MB",
        retention="14 days",
        backtrace=True,
        diagnose=False,
        enqueue=True,
        filter=lambda record: record["extra"].get("channel") == "browser",
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


def _mask(value: Any) -> Any:
    """Mask a sensitive value with asterisks, preserving its length."""
    if value is None:
        return None
    return "*" * len(str(value))


def _redact(value: Any, key: object = None) -> Any:
    if _is_sensitive_key(key):
        return _mask(value)
    if isinstance(value, dict):
        return {item_key: _redact(item_value, item_key) for item_key, item_value in value.items()}
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

    log_access = func.__qualname__ not in SILENT_ACCESS_LOG_CALLS

    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            _ensure_logging_configured()
            if log_access:
                access_logger.info(f"JS-Python call: {func.__qualname__} | input={_call_input(func, args, kwargs)!r}")
            try:
                result = await func(*args, **kwargs)
            except Exception as error:
                access_logger.info(f"JS-Python result: {func.__qualname__} | error={type(error).__name__}: {error}")
                error_logger.exception(f"JS-Python bridge call failed: {func.__qualname__}")
                raise
            if log_access:
                access_logger.info(f"JS-Python result: {func.__qualname__} | output={_redact(result)!r}")
            return result

        async_wrapper.__bridge_error_captured__ = True
        return cast(Callable[P, R], async_wrapper)

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        _ensure_logging_configured()
        if log_access:
            access_logger.info(f"JS-Python call: {func.__qualname__} | input={_call_input(func, args, kwargs)!r}")
        try:
            result = func(*args, **kwargs)
        except Exception as error:
            access_logger.info(f"JS-Python result: {func.__qualname__} | error={type(error).__name__}: {error}")
            error_logger.exception(f"JS-Python bridge call failed: {func.__qualname__}")
            raise
        if log_access:
            access_logger.info(f"JS-Python result: {func.__qualname__} | output={_redact(result)!r}")
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


class LogService:
    """Record frontend error reports in their own log channel."""

    @staticmethod
    def report_frontend_error(
        kind: str,
        message: str,
        stack: str | None = None,
    ) -> None:
        """Record a frontend console error, uncaught exception, or rejection."""
        if not isinstance(kind, str) or not isinstance(message, str):
            raise TypeError("错误类型与信息必须是字符串")
        if stack is not None and not isinstance(stack, str):
            raise TypeError("错误堆栈必须是字符串或 null")

        _ensure_logging_configured()
        text = f"Frontend {kind}: {message}"
        if stack:
            text += f"\n{stack}"
        browser_logger.error(text)
