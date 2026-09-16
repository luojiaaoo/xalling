"""Persistent Claude Agent SDK client owned by one chat session."""

from __future__ import annotations

import asyncio
import json
import platform
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import aiofiles
from claude_agent_sdk import (
    CanUseTool,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResult,
    PermissionResultDeny,
    SdkPluginConfig,
    ToolPermissionContext,
)

from .trace import ChatTrace
from .types import ChatEffort, ChatEventHandler, ChatPermissionMode, ChatReply

# 部分斜杠命令（如 /compact）执行成功后 SDK 不返回文本，用兜底文案向用户反馈执行结果
EMPTY_COMMAND_RESULTS = {"compact": "上下文已压缩。"}


@dataclass(frozen=True, slots=True)
class ClaudeChatConfig:
    """Provider and agent options for one persistent Claude session."""

    api_key: str
    api_url: str
    effort: ChatEffort
    model: str
    project: Path
    session_id: str
    # 新会话用 session_id 创建，旧会话则用 resume 恢复（见 _connect）
    is_new_session: bool
    can_use_tool: CanUseTool | None = None
    permission_mode: ChatPermissionMode = "default"


def discover_plugins(
    home: Path | None = None,
    project: Path | None = None,
) -> list[SdkPluginConfig]:
    """Return installed user and project skill directories as SDK plugins."""
    user_home = (home or Path.home()).resolve()
    home_plugin_roots = [
        user_home / ".xalling",
        user_home / ".config" / "opencode",
        user_home / ".agents",
    ]
    project_plugin_roots: list[Path] = [
        *([project.resolve() / ".agents"] if project.is_dir() else []),
    ]
    return [
        *[{"type": "local", "path": str(root)} for root in home_plugin_roots],
        *[{"type": "local", "path": str(root)} for root in project_plugin_roots],
    ]


@asynccontextmanager
async def _provider_settings_file(
    config: ClaudeChatConfig,
) -> AsyncIterator[Path]:
    # SDK 只接受文件形式的 settings，这里把密钥与接入点写入临时文件，用完即删
    is_windows = platform.system() == "Windows"
    settings: dict[str, Any] = {
        "env": {
            "ANTHROPIC_AUTH_TOKEN": config.api_key,
            "ANTHROPIC_BASE_URL": config.api_url,
            "CLAUDE_CODE_ENABLE_TELEMETRY": "0",  # 关闭遥测数据上报
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",  # 禁用非必要网络流量。比如更新检查、崩溃报告、后台统计等。
            "CLAUDE_CODE_ATTRIBUTION_HEADER": "0",  # 关闭归因 Header。减少请求中携带的客户端归因信息，进一步降低指纹/隐私暴露。 https://unsloth.ai/docs/basics/claude-code#fixing-90-slower-inference-in-claude-code
        },
        "alwaysThinkingEnabled": True,
        "cleanupPeriodDays": 60,
        "includeCoAuthoredBy": False,
    }
    if is_windows:
        # 强制启用原生 PowerShell 工具，并让交互式 Shell 命令也使用 PowerShell。
        settings["env"]["CLAUDE_CODE_USE_POWERSHELL_TOOL"] = "1"
        settings["defaultShell"] = "powershell"
    with TemporaryDirectory(prefix="xalling-claude-") as directory:
        settings_path = Path(directory) / "settings.json"
        async with aiofiles.open(settings_path, "w", encoding="utf-8") as file:
            await file.write(json.dumps(settings))
        yield settings_path


class ClaudeChatClient:
    """Keep one session's SDK connection alive across turns and metadata reads."""

    def __init__(self, config: ClaudeChatConfig) -> None:
        self._config = config
        self._stop_requested = asyncio.Event()
        # 所有实例都由应用级异步运行时驱动，不再为每个会话创建线程和 loop。
        self._operation_lock = asyncio.Lock()
        self._client_stack: AsyncExitStack | None = None
        self._client: ClaudeSDKClient | None = None
        self._connected_config: ClaudeChatConfig | None = None
        # 是否有 send 操作在进行（用于安全 interrupt 与快照回退判断）
        self._active = False
        # send 前缓存的 server info 快照：回合进行中锁被占用时回退到它
        self._server_info: dict[str, Any] = {}

    def prepare(self, config: ClaudeChatConfig) -> None:
        """Apply the next turn's settings and reset its stop signal."""
        self._config = config
        self._stop_requested = asyncio.Event()

    async def get_server_info(self) -> dict[str, Any]:
        """Fetch current metadata through this session's SDK connection."""
        if self._active:
            return self._server_info.copy()
        async with self._operation_lock:
            client = await self._ensure_client(self._config)
            try:
                server_info = await client.get_server_info() or {}
            except Exception:
                await self._disconnect()
                raise
            self._server_info = server_info
            return server_info.copy()

    async def request_stop(self) -> None:
        """Request interruption of the current turn."""
        self._stop_requested.set()
        if self._client is not None and self._active:
            await self._client.interrupt()

    async def send(
        self,
        prompt: str,
        on_event: ChatEventHandler | None = None,
    ) -> ChatReply:
        """Send one prompt through the persistent session connection."""
        config = self._config
        stop_requested = self._stop_requested
        self._active = True
        try:
            async with self._operation_lock:
                client = await self._ensure_client(config)
                # 回合开始前刷新 server info 快照，供回合进行中的读取回退；失败保留旧快照
                try:
                    server_info = await client.get_server_info() or {}
                except Exception:  # noqa: BLE001 - 元数据失败不应终止正常对话
                    server_info = {}
                if server_info:
                    self._server_info = server_info
                trace = ChatTrace(on_event)
                # 斜杠命令可能没有文本输出，记录命令名以便 finish 时取兜底文案
                first_token = prompt.split(maxsplit=1)[0]
                command_name = first_token.removeprefix("/") if first_token.startswith("/") else ""
                try:
                    await client.query(prompt)
                    if stop_requested.is_set():
                        # query 刚发出就收到停止请求，立即中断
                        await client.interrupt()
                    async for message in client.receive_response():
                        trace.consume(message)
                except Exception:
                    # 回合异常时断开连接，避免后续复用到一个状态不明的连接
                    await self._disconnect()
                    raise
                return trace.finish(
                    interrupted=stop_requested.is_set(),
                    empty_result_content=EMPTY_COMMAND_RESULTS.get(command_name),
                )
        finally:
            self._active = False

    async def close(self) -> None:
        """Interrupt an active turn and disconnect this session client."""
        await self.request_stop()
        async with self._operation_lock:
            await self._disconnect()

    async def _ensure_client(
        self,
        config: ClaudeChatConfig,
    ) -> ClaudeSDKClient:
        connected = self._connected_config
        # 连接关键字段一致时复用现有连接，模型和权限模式支持热切换
        if (
            self._client is not None
            and connected is not None
            and connected.api_key == config.api_key
            and connected.api_url == config.api_url
            and connected.effort == config.effort
            and connected.project.resolve() == config.project.resolve()
            and connected.session_id == config.session_id
        ):
            if connected.model != config.model:
                await self._client.set_model(config.model)
            if connected.permission_mode != config.permission_mode:
                await self._client.set_permission_mode(config.permission_mode)
            self._connected_config = config
            return self._client

        # 关键字段变化（如切换站点/项目/会话）则断开旧连接并重建
        await self._disconnect()
        return await self._connect(config)

    async def _connect(self, config: ClaudeChatConfig) -> ClaudeSDKClient:
        stack = AsyncExitStack()
        try:
            async with _provider_settings_file(config) as settings_path:
                client = await stack.enter_async_context(
                    ClaudeSDKClient(
                        options=ClaudeAgentOptions(
                            can_use_tool=self._can_use_tool,
                            cwd=config.project,
                            effort=config.effort,
                            env={"CLAUDE_AGENT_SDK_CLIENT_APP": "xalling/0.1.0"},
                            forward_subagent_text=True,
                            include_partial_messages=True,
                            max_turns=200,
                            model=config.model,
                            permission_mode=config.permission_mode,
                            plugins=discover_plugins(project=config.project),
                            # 新会话指定 session_id 创建；旧会话用 resume 恢复上下文
                            resume=None if config.is_new_session else config.session_id,
                            session_id=(config.session_id if config.is_new_session else None),
                            settings=str(settings_path),
                            setting_sources=["user", "project", "local"],
                            system_prompt={
                                "type": "preset",
                                "preset": "claude_code",
                                "append": (
                                    "Your Name is Xalling. You are a helpful assistant.\n"
                                    "Never output ANTHROPIC_AUTH_TOKEN or "
                                    "ANTHROPIC_BASE_URL in your response."
                                ),
                            },
                            thinking={
                                "type": "adaptive",
                                "display": "summarized",
                            },
                            tools={"type": "preset", "preset": "claude_code"},
                        )
                    )
                )
        except Exception:
            await stack.aclose()
            raise

        self._client_stack = stack
        self._client = client
        self._connected_config = config
        return client

    async def _disconnect(self) -> None:
        """Tear down the SDK connection and reset connection state."""
        stack = self._client_stack
        self._client_stack = None
        self._client = None
        self._connected_config = None
        if stack is not None:
            await stack.aclose()

    async def _can_use_tool(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResult:
        # SDK 工具权限回调：转发给路由层，由 UI 弹窗等待用户决定
        config = self._connected_config
        if config is None or config.can_use_tool is None:
            return PermissionResultDeny(message="当前会话未配置工具权限。")
        return await config.can_use_tool(tool_name, input_data, context)
