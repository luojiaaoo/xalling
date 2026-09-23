"""暴露给大模型的定时任务工具（SDK 内置 MCP server）。"""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import McpSdkServerConfig, create_sdk_mcp_server, tool

from backend.scheduler import add_scheduled_task, update_scheduled_task
from backend.scheduler import delete_scheduled_task as remove_scheduled_task
from backend.scheduler import list_scheduled_tasks as get_scheduled_tasks

_TOOL_DESCRIPTION = (
    "创建一个定时任务，到点后系统会以给定的用户提示词自动发起一轮对话。"
    "工作区路径和思考等级沿用当前会话配置，执行时使用当前模型。"
    "创建前必须向用户确认执行模式（权限模式），不能直接沿用当前会话的选择。"
    "调度类型 type 三选一：interval（按周期重复，需提供 interval）、"
    "date（在指定时间执行一次，需提供 run_at）、cron（按 cron 表达式重复，需提供 cron）。"
)

_PERMISSION_MODES = ("default", "acceptEdits", "plan", "auto", "bypassPermissions")

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": ["interval", "date", "cron"],
            "description": "调度类型：interval=按周期重复；date=在指定时间执行一次；cron=按 cron 表达式重复",
        },
        "interval": {
            "type": "string",
            "description": "周期（type=interval 时必填），示例：30s、10m、2h、1d、1h30m",
        },
        "run_at": {
            "type": "string",
            "description": "定时时间（type=date 时必填），ISO 格式，示例：2026-09-22 15:30",
        },
        "cron": {
            "type": "string",
            "description": "cron 表达式（type=cron 时必填），5 段，示例：*/5 * * * * 表示每 5 分钟",
        },
        "prompt": {
            "type": "string",
            "description": "任务触发时执行的用户提示词",
        },
        "permission_mode": {
            "type": "string",
            "enum": list(_PERMISSION_MODES),
            "description": (
                "任务触发时使用的执行模式，必须由用户明确选择；"
                "default=变更前确认、acceptEdits=自动编辑、plan=计划模式、"
                "auto=帮我批准（模型API可能不支持）、bypassPermissions=完全访问"
            ),
        },
        "model": {
            "type": "string",
            "description": "任务触发时使用的模型名称，默认沿用当前会话模型",
        },
    },
    "required": ["type", "prompt", "permission_mode"],
}

_EMPTY_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
}

_DELETE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "要删除的定时任务 ID",
        },
    },
    "required": ["task_id"],
}

_UPDATE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "要修改的定时任务 ID",
        },
        "type": {
            "type": "string",
            "enum": ["interval", "date", "cron"],
            "description": "新的调度类型；不传则保留原类型，修改类型时必须传入",
        },
        "interval": {
            "type": "string",
            "description": "新的周期，type=interval 时使用",
        },
        "run_at": {
            "type": "string",
            "description": "新的定时时间，type=date 时使用",
        },
        "cron": {
            "type": "string",
            "description": "新的 cron 表达式，type=cron 时使用",
        },
        "prompt": {
            "type": "string",
            "description": "新的用户提示词；不传则保留原提示词",
        },
        "permission_mode": {
            "type": "string",
            "enum": list(_PERMISSION_MODES),
            "description": "新的执行模式；不传则保留原执行模式",
        },
        "model": {
            "type": "string",
            "description": "新的模型名称；不传则保留原模型",
        },
    },
    "required": ["task_id"],
}


def _text_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def build_scheduler_mcp_server(
    *,
    workspace_path: str,
    effort: str,
    model: str = "",
    model_site: str = "",
) -> McpSdkServerConfig:
    """构建绑定当前会话上下文的定时任务 MCP server。

    每个连接一份实例，这样工具创建任务时能沿用该会话的
    工作区路径和思考等级沿用当前会话配置，执行模式由创建任务时的用户选择决定。
    """

    @tool("create_scheduled_task", _TOOL_DESCRIPTION, _INPUT_SCHEMA)
    async def create_scheduled_task(args: dict[str, Any]) -> dict[str, Any]:
        try:
            selected_permission_mode = str(args.get("permission_mode") or "")
            if selected_permission_mode not in _PERMISSION_MODES:
                raise ValueError("必须先选择有效的执行模式")
            summary = await add_scheduled_task(
                schedule_type=str(args.get("type") or ""),
                prompt=str(args.get("prompt") or ""),
                interval=args.get("interval"),
                run_at=args.get("run_at"),
                cron=args.get("cron"),
                workspace_path=workspace_path,
                permission_mode=selected_permission_mode,
                effort=effort,
                model=str(args.get("model") or model),
                model_site=model_site,
            )
        except (ValueError, TypeError) as error:
            return _text_result(f"创建定时任务失败：{error}", is_error=True)
        return _text_result(
            "定时任务已创建：\n"
            f"- 任务ID：{summary['task_id']}\n"
            f"- 标题：{summary['title']}\n"
            f"- 类型：{summary['schedule_type']}（{summary['schedule_value']}）\n"
            f"- 执行模式：{summary['permission_mode']}\n"
            f"- 模型：{summary['model'] or '当前模型'}\n"
            f"- 下次执行：{summary['next_run_time']}"
        )

    @tool(
        "list_scheduled_tasks",
        "查询当前工作区内的定时任务及其下次执行时间。只能查看当前工作区的任务。",
        _EMPTY_INPUT_SCHEMA,
    )
    async def list_scheduled_tasks(_args: dict[str, Any]) -> dict[str, Any]:
        summaries = await get_scheduled_tasks(workspace_path=workspace_path)
        if not summaries:
            return _text_result("当前没有定时任务。")
        lines = ["当前定时任务："]
        for summary in summaries:
            lines.extend(
                [
                    f"- 任务ID：{summary['task_id']}",
                    f"  标题：{summary['title']}",
                    f"  类型：{summary['schedule_type']}（{summary['schedule_value']}）",
                    f"  执行模式：{summary['permission_mode']}",
                    f"  模型：{summary['model'] or '当前模型'}",
                    f"  下次执行：{summary['next_run_time']}",
                    f"  提示词：{summary['prompt']}",
                ]
            )
        return _text_result("\n".join(lines))

    @tool(
        "update_scheduled_task",
        "修改当前工作区内的定时任务；先查询任务 ID，再传入需要修改的字段。未传字段保持不变。",
        _UPDATE_INPUT_SCHEMA,
    )
    async def update_task(args: dict[str, Any]) -> dict[str, Any]:
        try:
            selected_permission_mode = args.get("permission_mode")
            if selected_permission_mode is not None:
                selected_permission_mode = str(selected_permission_mode)
                if selected_permission_mode not in _PERMISSION_MODES:
                    raise ValueError("必须选择有效的执行模式")
            summary = await update_scheduled_task(
                str(args.get("task_id") or ""),
                workspace_path=workspace_path,
                schedule_type=(
                    str(args["type"]) if args.get("type") is not None else None
                ),
                prompt=(
                    str(args["prompt"]) if args.get("prompt") is not None else None
                ),
                interval=(
                    str(args["interval"]) if args.get("interval") is not None else None
                ),
                run_at=(
                    str(args["run_at"]) if args.get("run_at") is not None else None
                ),
                cron=(
                    str(args["cron"]) if args.get("cron") is not None else None
                ),
                permission_mode=selected_permission_mode,
                model=(str(args["model"]) if args.get("model") is not None else None),
            )
        except (ValueError, TypeError) as error:
            return _text_result(f"修改定时任务失败：{error}", is_error=True)
        return _text_result(
            "定时任务已修改：\n"
            f"- 任务ID：{summary['task_id']}\n"
            f"- 标题：{summary['title']}\n"
            f"- 类型：{summary['schedule_type']}（{summary['schedule_value']}）\n"
            f"- 执行模式：{summary['permission_mode']}\n"
            f"- 模型：{summary['model'] or '当前模型'}\n"
            f"- 下次执行：{summary['next_run_time']}"
        )

    @tool(
        "delete_scheduled_task",
        "按任务 ID 删除当前工作区内的定时任务；只能删除当前工作区的任务。",
        _DELETE_INPUT_SCHEMA,
    )
    async def delete_scheduled_task(args: dict[str, Any]) -> dict[str, Any]:
        try:
            summary = await remove_scheduled_task(
                str(args.get("task_id") or ""),
                workspace_path=workspace_path,
            )
        except (ValueError, TypeError) as error:
            return _text_result(f"删除定时任务失败：{error}", is_error=True)
        return _text_result(
            "定时任务已删除：\n"
            f"- 任务ID：{summary['task_id']}\n"
            f"- 标题：{summary['title']}\n"
            f"- 类型：{summary['schedule_type']}（{summary['schedule_value']}）"
        )

    return create_sdk_mcp_server(
        name="xalling-scheduler",
        version="1.0.0",
        tools=[
            create_scheduled_task,
            list_scheduled_tasks,
            update_task,
            delete_scheduled_task,
        ],
    )
