"""Log methods exposed to the local Web UI."""

from backend.service.log import LogService


class LogRouter:
    """Receive error reports from the Web UI and write them to its own log."""

    def report_frontend_error(
        self,
        kind: str,
        message: str,
        stack: str | None = None,
    ) -> None:
        """Record a frontend console error, uncaught exception, or rejection."""
        LogService.report_frontend_error(kind, message, stack)
