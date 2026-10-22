"""Restore APScheduler jobs persisted with the original module path.

New application code uses backend.service.scheduling.service. Existing SQLite
jobs reference both this task class and callable, so keep these two names
available for deserialization.
"""

from backend.service.scheduling.service import ScheduledTask, _execute_scheduled_task

__all__ = ["ScheduledTask", "_execute_scheduled_task"]
