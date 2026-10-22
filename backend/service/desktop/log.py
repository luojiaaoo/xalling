"""Application logging channels and file sinks."""

import logging
import os
import sys

from loguru import logger

from backend.config.setting import (
    BROWSER_LOG_FILEPATH,
    CLAUDE_SDK_FILEPATH,
    ERROR_LOG_FILEPATH,
    LOG_DIRECTORY,
    OTHER_LOG_FILEPATH,
)

LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"

browser_logger = logger.bind(channel="browser")
error_logger = logger.bind(channel="error")
session_debug_logger = logger.bind(channel="session_debug")
claude_sdk_logger = logger.bind(channel="claude_sdk")
other_logger = logger.bind(channel="other")
console_logger = logger.bind(channel="console")

# 把标准 logging 的日志统一转发给 Loguru。
class _LoguruHandler(logging.Handler):
    """Route library/server messages through the application's Loguru sinks."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        other_logger.opt(exception=record.exc_info).log(level, record.getMessage())


def configure_logging() -> None:
    """Write application logs to files and explicit console messages to stdout."""
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    logger.remove()
    # 无控制台时，就不输出标准输出日志了
    if sys.stdout is not None and getattr(sys.stdout, "name", None) != os.devnull:
        logger.add(
            _write_console,
            level="INFO",
            format="{time:YYYY-MM-DD HH:mm:ss} | {message}",
            filter=lambda record: record["extra"].get("channel") == "console",
            colorize=False,
            backtrace=False,
            diagnose=False,
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
    logger.add(
        OTHER_LOG_FILEPATH,
        level="INFO",
        format=LOG_FORMAT,
        encoding="utf-8",
        rotation="10 MB",
        retention="14 days",
        backtrace=True,
        diagnose=False,
        enqueue=True,
        filter=lambda record: record["extra"].get("channel") == "other",
    )
    logging.basicConfig(handlers=[_LoguruHandler()], level=logging.INFO, force=True)
    for name in ("uvicorn", "pywebview"):
        library_logger = logging.getLogger(name)
        library_logger.handlers.clear()
        library_logger.propagate = True


def _write_console(message: str) -> None:
    """仅对控制台日志处理编码错误，不修改全局标准输出流。"""
    stream = sys.stdout
    if stream is None:
        return
    try:
        stream.write(message)
    except UnicodeEncodeError as error:
        # GBK 等编码无法表示 emoji 时，转义当前日志后再写入。
        stream.write(message.encode(error.encoding, errors="backslashreplace").decode(error.encoding))
    stream.flush()


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

        text = f"Frontend {kind}: {message}"
        if stack:
            text += f"\n{stack}"
        browser_logger.error(text)
