"""Claude Agent SDK methods exposed to the local Web UI."""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict
from uuid import UUID

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    ResultMessage,
    ServerToolResultBlock,
    ServerToolUseBlock,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from webview.errors import JavascriptException, WebViewException

from backend.config.current import CurrentConfig
from backend.config.setting import ModelSiteConfig, Settings


class ChatReply(TypedDict):
    """The final Claude response and its resumable session identifier."""

    content: str
    final_output_block_id: str | None
    session_id: str


class ChatRouter:
    """Run coding-agent turns through the currently selected Claude provider."""

    _window: Any | None = None

    def send_chat_message(
        self,
        prompt: str,
        project_path: str | None = None,
        session_id: str | None = None,
        effort: str = "high",
        request_id: str | None = None,
    ) -> ChatReply:
        """Run one turn, stream text events, and return the final response."""
        normalized_prompt = self._validate_prompt(prompt)
        project = self._validate_project_path(project_path)
        resume = self._validate_session_id(session_id)
        normalized_effort = self._validate_effort(effort)
        stream_request_id = self._validate_request_id(request_id)
        site, model_name = self._get_current_provider()

        try:
            return asyncio.run(
                self._run_turn(
                    prompt=normalized_prompt,
                    project=project,
                    resume=resume,
                    effort=normalized_effort,
                    site=site,
                    model_name=model_name,
                    on_event=(
                        lambda event: self._emit_chat_event(stream_request_id, event)
                    )
                    if stream_request_id is not None
                    else None,
                )
            )
        except ClaudeSDKError as error:
            raise RuntimeError(f"Claude SDK 请求失败：{error}") from error

    @staticmethod
    async def _run_turn(
        *,
        prompt: str,
        project: Path,
        resume: str | None,
        effort: str,
        site: ModelSiteConfig,
        model_name: str,
        on_event: Callable[[dict[str, object]], None] | None = None,
    ) -> ChatReply:
        options = ClaudeAgentOptions(
            allowed_tools=["Read", "Glob", "Grep"],
            cwd=project,
            effort=effort,
            env={
                "ANTHROPIC_AUTH_TOKEN": site.api_key,
                "ANTHROPIC_BASE_URL": site.api_url,
                "ANTHROPIC_MODEL": model_name,
                "CLAUDE_AGENT_SDK_CLIENT_APP": "xalling/0.1.0",
            },
            include_partial_messages=True,
            max_turns=30,
            model=model_name,
            permission_mode="default",
            resume=resume,
            setting_sources=["user", "project", "local"],
            system_prompt={"type": "preset", "preset": "claude_code"},
            thinking={"type": "adaptive", "display": "summarized"},
            tools={"type": "preset", "preset": "claude_code"},
        )
        assistant_text_parts: list[str] = []
        block_contents: dict[str, str] = {}
        block_kinds: dict[str, str] = {}
        completed_blocks: set[str] = set()
        stream_message_number = 0
        assistant_message_number = 0
        current_stream_message_id: str | None = None
        latest_output_block_id: str | None = None
        result: ResultMessage | None = None

        def emit(event: dict[str, object]) -> None:
            if on_event is not None:
                on_event(event)

        def start_block(block_id: str, kind: str) -> None:
            nonlocal latest_output_block_id
            if block_id in block_kinds:
                return
            block_kinds[block_id] = kind
            block_contents[block_id] = ""
            if kind == "output":
                latest_output_block_id = block_id
            emit({"type": f"{kind}_start", "block_id": block_id})

        def append_block(block_id: str, kind: str, text: str) -> None:
            start_block(block_id, kind)
            block_contents[block_id] = f"{block_contents[block_id]}{text}"
            emit({"type": f"{kind}_delta", "block_id": block_id, "text": text})

        def complete_block(block_id: str, kind: str, content: str = "") -> None:
            start_block(block_id, kind)
            streamed_content = block_contents[block_id]
            if content.startswith(streamed_content):
                missing_content = content[len(streamed_content) :]
                if missing_content:
                    append_block(block_id, kind, missing_content)
            elif content and not streamed_content:
                append_block(block_id, kind, content)
            if block_id not in completed_blocks:
                completed_blocks.add(block_id)
                emit({"type": f"{kind}_complete", "block_id": block_id})

        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            async for message in client.receive_response():
                if isinstance(message, StreamEvent):
                    event = message.event
                    event_type = event.get("type")
                    if event_type == "message_start":
                        stream_message_number += 1
                        stream_message = event.get("message")
                        current_stream_message_id = (
                            stream_message.get("id")
                            if isinstance(stream_message, dict)
                            and isinstance(stream_message.get("id"), str)
                            else f"message-{stream_message_number}"
                        )
                    elif event_type == "content_block_start":
                        block_index = ChatRouter._stream_block_index(event)
                        content_block = event.get("content_block")
                        if block_index is not None and isinstance(content_block, dict):
                            kind = ChatRouter._trace_block_kind(content_block.get("type"))
                            if kind is not None:
                                block_id = (
                                    f"{current_stream_message_id or 'message-1'}"
                                    f"-block-{block_index}"
                                )
                                start_block(block_id, kind)
                    elif event_type == "content_block_delta":
                        block_index = ChatRouter._stream_block_index(event)
                        delta = event.get("delta")
                        if block_index is not None and isinstance(delta, dict):
                            kind, text = ChatRouter._stream_content_delta(delta)
                            if kind is not None and text:
                                block_id = (
                                    f"{current_stream_message_id or 'message-1'}"
                                    f"-block-{block_index}"
                                )
                                append_block(block_id, kind, text)
                    elif event_type == "content_block_stop":
                        block_index = ChatRouter._stream_block_index(event)
                        if block_index is not None:
                            block_id = (
                                f"{current_stream_message_id or 'message-1'}"
                                f"-block-{block_index}"
                            )
                            kind = block_kinds.get(block_id)
                            if kind is not None:
                                complete_block(block_id, kind)
                elif (
                    isinstance(message, AssistantMessage)
                    and message.parent_tool_use_id is None
                ):
                    assistant_message_number += 1
                    message_id = (
                        message.message_id
                        or current_stream_message_id
                        or f"message-{assistant_message_number}"
                    )
                    current_stream_message_id = message_id
                    tool_group_id = f"tools-{message_id}"
                    for block_index, block in enumerate(message.content):
                        block_id = f"{message_id}-block-{block_index}"
                        if isinstance(block, TextBlock):
                            assistant_text_parts.append(block.text)
                            complete_block(block_id, "output", block.text)
                        elif isinstance(block, ThinkingBlock):
                            complete_block(block_id, "thinking", block.thinking)
                        elif isinstance(block, (ToolUseBlock, ServerToolUseBlock)):
                            emit(
                                {
                                    "type": "tool_start",
                                    "group_id": tool_group_id,
                                    "tool_id": block.id,
                                    "name": block.name,
                                    "summary": ChatRouter._summarize_tool_input(
                                        block.input
                                    ),
                                }
                            )
                        elif isinstance(block, ToolResultBlock):
                            emit(
                                {
                                    "type": "tool_complete",
                                    "tool_id": block.tool_use_id,
                                    "status": "error" if block.is_error else "success",
                                }
                            )
                        elif isinstance(block, ServerToolResultBlock):
                            emit(
                                {
                                    "type": "tool_complete",
                                    "tool_id": block.tool_use_id,
                                    "status": "success",
                                }
                            )
                elif isinstance(message, UserMessage):
                    completed_tool_ids: set[str] = set()
                    if isinstance(message.content, list):
                        for block in message.content:
                            if isinstance(block, ToolResultBlock):
                                completed_tool_ids.add(block.tool_use_id)
                                emit(
                                    {
                                        "type": "tool_complete",
                                        "tool_id": block.tool_use_id,
                                        "status": (
                                            "error" if block.is_error else "success"
                                        ),
                                    }
                                )
                    if (
                        message.parent_tool_use_id is not None
                        and message.parent_tool_use_id not in completed_tool_ids
                    ):
                        is_error = bool(
                            message.tool_use_result
                            and message.tool_use_result.get("is_error") is True
                        )
                        emit(
                            {
                                "type": "tool_complete",
                                "tool_id": message.parent_tool_use_id,
                                "status": "error" if is_error else "success",
                            }
                        )
                elif isinstance(message, ResultMessage):
                    result = message

        for block_id, kind in block_kinds.items():
            complete_block(block_id, kind)

        if result is None:
            raise RuntimeError("Claude SDK 未返回任务结果")
        if result.is_error:
            details = result.result or "；".join(result.errors or []) or result.subtype
            raise RuntimeError(f"Claude 执行失败：{details}")

        content = (result.result or "\n\n".join(assistant_text_parts)).strip()
        if not content:
            raise RuntimeError("Claude 没有返回文字内容")
        final_output_block_id = (
            latest_output_block_id
            if latest_output_block_id is not None
            and block_contents[latest_output_block_id].strip() == content
            else None
        )
        return {
            "content": content,
            "final_output_block_id": final_output_block_id,
            "session_id": result.session_id,
        }

    def _emit_chat_event(self, request_id: str, event: dict[str, object]) -> None:
        """Dispatch one structured progress event to the matching Web UI request."""
        if self._window is None:
            return

        event_detail = {"request_id": request_id, **event}
        detail = json.dumps(
            event_detail,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        script = (
            "window.dispatchEvent(new CustomEvent('xalling:chat-event',"
            f"{{detail:{detail}}}));"
        )
        try:
            self._window.evaluate_js(script)
        except (JavascriptException, WebViewException):
            # The native window may be closing while the SDK finishes a turn.
            return

    @staticmethod
    def _stream_block_index(event: dict[str, Any]) -> int | None:
        block_index = event.get("index")
        return block_index if type(block_index) is int else None

    @staticmethod
    def _trace_block_kind(block_type: object) -> str | None:
        if block_type == "thinking":
            return "thinking"
        if block_type == "text":
            return "output"
        return None

    @staticmethod
    def _stream_content_delta(delta: dict[str, Any]) -> tuple[str | None, str]:
        delta_type = delta.get("type")
        if delta_type == "thinking_delta":
            thinking = delta.get("thinking")
            return "thinking", thinking if isinstance(thinking, str) else ""
        if delta_type == "text_delta":
            text = delta.get("text")
            return "output", text if isinstance(text, str) else ""
        return None, ""

    @staticmethod
    def _summarize_tool_input(tool_input: dict[str, Any]) -> str:
        """Return a short, non-sensitive description of a tool invocation."""
        preferred_keys = (
            "file_path",
            "path",
            "pattern",
            "query",
            "url",
            "command",
            "description",
        )
        summary_parts: list[str] = []
        for key in preferred_keys:
            if key not in tool_input:
                continue
            value = tool_input[key]
            if not isinstance(value, (str, int, float, bool)):
                continue
            normalized = " ".join(str(value).split())
            if normalized:
                summary_parts.append(f"{key}: {normalized[:180]}")
            if len(summary_parts) == 2:
                break
        return " · ".join(summary_parts)

    @staticmethod
    def _get_current_provider() -> tuple[ModelSiteConfig, str]:
        current = CurrentConfig().model
        if not current.site or not current.name:
            raise ValueError("请先在模型管理中配置并选择模型")

        site = next((item for item in Settings().model if item.name == current.site), None)
        if site is None or not any(model.name == current.name for model in site.models):
            raise ValueError("当前选择的模型已不存在，请重新选择")
        if not site.api_url.strip():
            raise ValueError("当前供应商尚未填写 API 地址")
        if not site.api_key.strip():
            raise ValueError("当前供应商尚未填写 API Key")
        return site, current.name

    @staticmethod
    def _validate_prompt(value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("消息内容必须是字符串")
        normalized = value.strip()
        if not normalized:
            raise ValueError("消息内容不能为空")
        if len(normalized) > 500_000:
            raise ValueError("消息内容过长")
        return normalized

    @staticmethod
    def _validate_project_path(value: object) -> Path:
        if value is None or value == "":
            return Path.home().resolve()
        if not isinstance(value, str):
            raise TypeError("项目路径必须是字符串")
        project = Path(value).resolve()
        if not project.is_dir():
            raise ValueError("选择的项目文件夹已不存在")
        return project

    @staticmethod
    def _validate_session_id(value: object) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise TypeError("会话标识必须是字符串")
        try:
            return str(UUID(value))
        except ValueError as error:
            raise ValueError("会话标识无效") from error

    @staticmethod
    def _validate_effort(value: object) -> str:
        if not isinstance(value, str) or value not in {"low", "medium", "high", "max"}:
            raise ValueError("推理强度无效")
        return value

    @staticmethod
    def _validate_request_id(value: object) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise TypeError("请求标识必须是字符串")
        normalized = value.strip()
        if not normalized or len(normalized) > 128:
            raise ValueError("请求标识无效")
        return normalized
