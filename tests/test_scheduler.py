from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import anyio


def test_scheduled_task_executor_is_called() -> None:
    from backend import scheduler

    async def scenario() -> None:
        calls: list[scheduler.ScheduledTask] = []

        async def execute(task: scheduler.ScheduledTask) -> None:
            calls.append(task)

        task = scheduler.ScheduledTask(
            task_id="task-id",
            session_id="session-id",
            title="scheduled task",
            prompt="run checks",
            workspace_path=".",
            permission_mode="default",
            effort="high",
            schedule_type="interval",
            schedule_value="1m",
        )
        scheduler.set_scheduled_task_executor(execute)
        try:
            await scheduler._execute_scheduled_task(task)
        finally:
            scheduler.set_scheduled_task_executor(None)

        assert calls == [task]

    anyio.run(scenario)


def test_add_scheduled_task_returns_dedicated_session() -> None:
    from backend import scheduler

    async def scenario() -> None:
        try:
            summary = await scheduler.add_scheduled_task(
                schedule_type="date",
                prompt="run checks",
                run_at=(datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
                workspace_path=".",
                permission_mode="default",
                effort="high",
            )
            listed = await scheduler.list_scheduled_tasks(workspace_path=".")
            queried = await scheduler.list_scheduled_tasks(workspace_path=".")
            assert scheduler._scheduler is not None
            assert scheduler._scheduler._job_defaults["max_instances"] == 2
            assert type(scheduler._scheduler._jobstores["default"]).__name__ == (
                "SQLAlchemyJobStore"
            )
            scheduler.shutdown_scheduler()
            restored = await scheduler.list_scheduled_tasks(workspace_path=".")
            deleted = await scheduler.delete_scheduled_task(
                summary["task_id"],
                workspace_path=".",
            )
        finally:
            scheduler.shutdown_scheduler()

        UUID(summary["task_id"])
        UUID(summary["session_id"])
        assert summary["schedule_type"] == "date"
        assert summary["next_run_time"] is not None
        assert [item["task_id"] for item in listed] == [summary["task_id"]]
        assert [item["task_id"] for item in queried] == [summary["task_id"]]
        assert [item["task_id"] for item in restored] == [summary["task_id"]]
        assert deleted["task_id"] == summary["task_id"]
        assert await scheduler.list_scheduled_tasks(workspace_path=".") == []

    anyio.run(scenario)


def test_scheduled_tasks_are_scoped_to_workspace() -> None:
    from backend import scheduler

    async def scenario() -> None:
        scheduler.shutdown_scheduler()
        created: list[dict[str, object]] = []
        workspace_paths = (f"workspace-a-{uuid4()}", f"workspace-b-{uuid4()}")
        try:
            for workspace_path in workspace_paths:
                created.append(
                    await scheduler.add_scheduled_task(
                        schedule_type="date",
                        prompt=f"run checks in {workspace_path}",
                        run_at=(datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
                        workspace_path=workspace_path,
                        permission_mode="default",
                        effort="high",
                    )
                )

            own_tasks = await scheduler.list_scheduled_tasks(
                workspace_path=workspace_paths[0]
            )
            other_tasks = await scheduler.list_scheduled_tasks(
                workspace_path=workspace_paths[1]
            )
            all_tasks = await scheduler.list_all_scheduled_tasks()
            assert [task["task_id"] for task in own_tasks] == [created[0]["task_id"]]
            assert [task["task_id"] for task in other_tasks] == [created[1]["task_id"]]
            assert {task["task_id"] for task in all_tasks} >= {
                created[0]["task_id"],
                created[1]["task_id"],
            }

            try:
                await scheduler.delete_scheduled_task(
                    str(created[0]["task_id"]),
                    workspace_path=workspace_paths[1],
                )
            except ValueError:
                pass
            else:
                raise AssertionError("跨工作区删除应该失败")

            await scheduler.delete_scheduled_task(
                str(created[0]["task_id"]),
                workspace_path=workspace_paths[0],
            )
            await scheduler.delete_scheduled_task(
                str(created[1]["task_id"]),
                workspace_path=workspace_paths[1],
            )
        finally:
            scheduler.shutdown_scheduler()

    anyio.run(scenario)


def test_application_bridge_runs_scheduled_task_as_async() -> None:
    from backend.scheduler import ScheduledTask
    from main import ApplicationBridge

    bridge = ApplicationBridge()
    calls: list[tuple[str, dict[str, str]]] = []

    async def fake_send(prompt: str, **kwargs: str) -> None:
        calls.append((prompt, kwargs))

    bridge._chat_service.send_chat_message = fake_send
    task = ScheduledTask(
        task_id="task-id",
        session_id="session-id",
        title="scheduled task",
        prompt="给用户发一句“你好”",
        workspace_path=".",
        permission_mode="default",
        effort="high",
        schedule_type="date",
        schedule_value="2026-09-22 11:38",
    )
    try:
        bridge._async_runtime.call(bridge._chat_service._run_scheduled_task, task)
    finally:
        bridge._close_bridge()

    assert len(calls) == 1
    prompt, kwargs = calls[0]
    assert prompt.startswith("给用户发一句“你好”\n\n")
    assert "任务创建者就是当前对话的用户本人" in prompt
    assert "当前会话中完成原始请求" in prompt
    assert "不要再次创建定时任务" in prompt
    assert kwargs == {
        "project_path": ".",
        "session_id": "session-id",
        "effort": "high",
        "permission_mode": "default",
    }
