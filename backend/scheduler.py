"""基于 APScheduler 的定时任务调度（应用内单例，随共享事件循环运行）。"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.config.setting import SCHEDULER_DATABASE_FILEPATH
from backend.service.log import claude_sdk_logger

type ScheduleType = Literal["interval", "date", "cron"]
SCHEDULE_TYPES: tuple[ScheduleType, ...] = ("interval", "date", "cron")

# 周期解析：支持 "30s"、"10m"、"2h"、"1d" 及组合如 "1h30m"，纯数字按秒处理
_INTERVAL_PART = re.compile(r"(\d+)\s*([smhd])", re.IGNORECASE)
_INTERVAL_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

# 调度器单例，任务数据持久化在 APScheduler 的 SQLite JobStore 中
_scheduler: AsyncIOScheduler | None = None
_task_executor: Callable[[ScheduledTask], Awaitable[None]] | None = None


@dataclass(slots=True)
class ScheduledTask:
    """定时任务的完整参数。

    大模型只提供调度参数和提示词；标题、工作区路径、权限模式、
    思考等级取自创建任务时的会话上下文，模型使用任务触发时的当前模型。
    """

    task_id: str
    session_id: str
    title: str
    prompt: str
    workspace_path: str
    permission_mode: str
    effort: str
    schedule_type: ScheduleType
    schedule_value: str  # 原始输入：周期 / 定时时间 / cron 表达式
    model: str = ""
    model_site: str = ""
    created_at: datetime = field(default_factory=datetime.now)


def set_scheduled_task_executor(
    executor: Callable[[ScheduledTask], Awaitable[None]] | None,
) -> None:
    """Set the application callback used when a scheduled task fires."""
    global _task_executor
    _task_executor = executor


def _parse_interval_seconds(text: str) -> float:
    """把 "10m"、"1h30m"、"90" 这类周期文本解析成秒数。"""
    normalized = text.strip()
    if normalized.isdigit():
        seconds = int(normalized)
    else:
        parts = _INTERVAL_PART.findall(normalized)
        if not parts or "".join(f"{n}{u}" for n, u in parts) != re.sub(
            r"\s+", "", normalized
        ).lower():
            raise ValueError(f"周期格式无效：{text}，示例：30s、10m、2h、1d、1h30m")
        seconds = sum(int(n) * _INTERVAL_UNITS[u.lower()] for n, u in parts)
    if seconds <= 0:
        raise ValueError("周期必须大于 0")
    return float(seconds)


def _build_trigger(
    schedule_type: ScheduleType,
    *,
    interval: str | None,
    run_at: str | None,
    cron: str | None,
) -> BaseTrigger:
    """按调度类型构建 APScheduler 触发器，参数缺失或非法时抛出 ValueError。"""
    if schedule_type == "interval":
        if not interval:
            raise ValueError("类型为 interval 时必须提供周期")
        return IntervalTrigger(seconds=_parse_interval_seconds(interval))
    if schedule_type == "date":
        if not run_at:
            raise ValueError("类型为 date 时必须提供定时时间")
        try:
            run_time = datetime.fromisoformat(run_at.strip())
        except ValueError as error:
            raise ValueError(
                f"定时时间格式无效：{run_at}，示例：2026-09-22 15:30"
            ) from error
        if run_time <= datetime.now(tz=run_time.tzinfo):
            raise ValueError("定时时间必须晚于当前时间")
        return DateTrigger(run_date=run_time)
    if schedule_type == "cron":
        if not cron:
            raise ValueError("类型为 cron 时必须提供 cron 表达式")
        try:
            return CronTrigger.from_crontab(cron.strip())
        except ValueError as error:
            raise ValueError(
                f"cron 表达式无效：{cron}，应为 5 段，示例：*/5 * * * *"
            ) from error
    raise ValueError(f"不支持的调度类型：{schedule_type}")


def _get_scheduler() -> AsyncIOScheduler:
    """惰性创建并启动调度器（必须在运行中的事件循环里首次调用）。"""
    global _scheduler
    if _scheduler is None:
        SCHEDULER_DATABASE_FILEPATH.parent.mkdir(parents=True, exist_ok=True)
        jobstore = SQLAlchemyJobStore(
            url=f"sqlite:///{SCHEDULER_DATABASE_FILEPATH.resolve().as_posix()}"
        )
        _scheduler = AsyncIOScheduler(
            jobstores={"default": jobstore},
            job_defaults={
                "coalesce": True,
                "max_instances": 2,
                "misfire_grace_time": 1,
            },
        )
        _scheduler.start()
    return _scheduler


def _get_persisted_tasks() -> list[ScheduledTask]:
    """Read task arguments directly from the configured persistent job store."""
    if _scheduler is None:
        return []
    return [
        job.args[0]
        for job in _scheduler.get_jobs()
        if len(job.args) == 1 and isinstance(job.args[0], ScheduledTask)
    ]


def _task_summary(task: ScheduledTask) -> dict[str, Any]:
    job = _scheduler.get_job(task.task_id) if _scheduler is not None else None
    return {
        "task_id": task.task_id,
        "session_id": task.session_id,
        "title": task.title,
        "prompt": task.prompt,
        "workspace_path": task.workspace_path,
        "permission_mode": task.permission_mode,
        "effort": task.effort,
        "model": task.model,
        "model_site": task.model_site,
        "schedule_type": task.schedule_type,
        "schedule_value": task.schedule_value,
        "created_at": task.created_at.isoformat(),
        "next_run_time": job.next_run_time.isoformat() if job and job.next_run_time else None,
    }


def _normalize_workspace_path(workspace_path: str) -> str:
    if not isinstance(workspace_path, str) or not workspace_path.strip():
        raise TypeError("工作区路径必须是非空字符串")
    return str(Path(workspace_path).expanduser().resolve())


def _task_belongs_to_workspace(task: ScheduledTask, workspace_path: str) -> bool:
    return _normalize_workspace_path(task.workspace_path).casefold() == workspace_path.casefold()


async def _execute_scheduled_task(task: ScheduledTask) -> None:
    """定时任务触发入口。"""
    claude_sdk_logger.info(
        "定时任务触发 | task_id={} session_id={} title={} type={} "
        "workspace={} permission_mode={} effort={} prompt={}",
        task.task_id,
        task.session_id,
        task.title,
        task.schedule_type,
        task.workspace_path,
        task.permission_mode,
        task.effort,
        task.prompt,
    )
    executor = _task_executor
    if executor is None:
        claude_sdk_logger.error(
            "定时任务未执行：应用尚未配置任务执行器 | task_id={}",
            task.task_id,
        )
        return
    await executor(task)


async def add_scheduled_task(
    *,
    schedule_type: str,
    prompt: str,
    interval: str | None = None,
    run_at: str | None = None,
    cron: str | None = None,
    workspace_path: str,
    permission_mode: str,
    effort: str,
    model: str = "",
    model_site: str = "",
) -> dict[str, Any]:
    """创建并注册一个定时任务，返回给调用方的任务摘要。"""
    if schedule_type not in SCHEDULE_TYPES:
        raise ValueError(f"调度类型无效：{schedule_type}，可选：{'、'.join(SCHEDULE_TYPES)}")
    normalized_prompt = " ".join(prompt.split())
    if not normalized_prompt:
        raise ValueError("用户提示词不能为空")

    trigger = _build_trigger(
        schedule_type,  # type: ignore[arg-type]
        interval=interval,
        run_at=run_at,
        cron=cron,
    )
    schedule_value = {"interval": interval, "date": run_at, "cron": cron}[schedule_type]
    task = ScheduledTask(
        task_id=str(uuid4()),
        session_id=str(uuid4()),
        title=normalized_prompt[:30],
        prompt=normalized_prompt,
        workspace_path=_normalize_workspace_path(workspace_path),
        permission_mode=permission_mode,
        effort=effort,
        model=model,
        model_site=model_site,
        schedule_type=schedule_type,  # type: ignore[arg-type]
        schedule_value=schedule_value or "",
    )
    _get_scheduler().add_job(
        _execute_scheduled_task,
        trigger=trigger,
        args=[task],
        id=task.task_id,
        name=task.title,
    )
    claude_sdk_logger.info(
        "定时任务已创建 | task_id={} title={} type={} value={}",
        task.task_id,
        task.title,
        task.schedule_type,
        task.schedule_value,
    )
    return _task_summary(task)


async def list_scheduled_tasks(*, workspace_path: str) -> list[dict[str, Any]]:
    """Return scheduled tasks belonging to the requested workspace."""
    _get_scheduler()
    normalized_workspace_path = _normalize_workspace_path(workspace_path)
    return _task_summaries(
        task
        for task in _get_persisted_tasks()
        if _task_belongs_to_workspace(task, normalized_workspace_path)
    )


def _task_summaries(tasks: Iterable[ScheduledTask]) -> list[dict[str, Any]]:
    return [
        _task_summary(task)
        for task in sorted(
            tasks,
            key=lambda item: item.created_at,
            reverse=True,
        )
    ]


async def list_all_scheduled_tasks() -> list[dict[str, Any]]:
    """Return all scheduled tasks for the local application UI."""
    _get_scheduler()
    return _task_summaries(_get_persisted_tasks())


async def delete_scheduled_task(
    task_id: str,
    *,
    workspace_path: str,
) -> dict[str, Any]:
    """Delete one task only when it belongs to the requested workspace."""
    _get_scheduler()
    if not isinstance(task_id, str) or not task_id.strip():
        raise TypeError("任务 ID 必须是非空字符串")
    normalized_task_id = task_id.strip()
    normalized_workspace_path = _normalize_workspace_path(workspace_path)
    task = next(
        (
            persisted_task
            for persisted_task in _get_persisted_tasks()
            if persisted_task.task_id == normalized_task_id
        ),
        None,
    )
    if task is None or not _task_belongs_to_workspace(task, normalized_workspace_path):
        raise ValueError(f"找不到定时任务：{normalized_task_id}")
    if _scheduler is not None:
        job = _scheduler.get_job(normalized_task_id)
        if job is not None:
            _scheduler.remove_job(normalized_task_id)
    return _task_summary(task)


def shutdown_scheduler() -> None:
    """Stop the process-local scheduler during application shutdown."""
    global _scheduler, _task_executor
    _task_executor = None
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except RuntimeError:
            # 测试或宿主退出时，调度器绑定的事件循环可能已经关闭。
            _scheduler = None
            return
        _scheduler = None
