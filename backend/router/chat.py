"""Claude Agent SDK methods exposed to the local Web UI."""

import asyncio
from pathlib import Path
from typing import TypedDict
from uuid import UUID

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKError,
    ResultMessage,
    TextBlock,
    query,
)

from backend.config.current import CurrentConfig
from backend.config.setting import ModelSiteConfig, Settings


class ChatReply(TypedDict):
    """The final Claude response and its resumable session identifier."""

    content: str
    session_id: str


class ChatRouter:
    """Run coding-agent turns through the currently selected Claude provider."""

    def send_chat_message(
        self,
        prompt: str,
        project_path: str | None = None,
        session_id: str | None = None,
        effort: str = "high",
    ) -> ChatReply:
        """Run one turn and return the final text response."""
        normalized_prompt = self._validate_prompt(prompt)
        project = self._validate_project_path(project_path)
        resume = self._validate_session_id(session_id)
        normalized_effort = self._validate_effort(effort)
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
            max_turns=30,
            model=model_name,
            permission_mode="default",
            resume=resume,
            setting_sources=["user", "project", "local"],
            system_prompt={"type": "preset", "preset": "claude_code"},
            tools={"type": "preset", "preset": "claude_code"},
        )
        text_parts: list[str] = []
        result: ResultMessage | None = None

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage) and message.parent_tool_use_id is None:
                text_parts.extend(
                    block.text for block in message.content if isinstance(block, TextBlock)
                )
            elif isinstance(message, ResultMessage):
                result = message

        if result is None:
            raise RuntimeError("Claude SDK 未返回任务结果")
        if result.is_error:
            details = result.result or "；".join(result.errors or []) or result.subtype
            raise RuntimeError(f"Claude 执行失败：{details}")

        content = (result.result or "\n\n".join(text_parts)).strip()
        if not content:
            raise RuntimeError("Claude 没有返回文字内容")
        return {"content": content, "session_id": result.session_id}

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
