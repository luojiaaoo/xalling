"""Client lifecycle for the event-oriented Claude Agent SDK wrapper."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from contextlib import aclosing, suppress
from dataclasses import dataclass, field, replace
from types import TracebackType
from typing import Any, Self, cast
from uuid import uuid4

import anyio
from anyio.streams.memory import MemoryObjectSendStream
from claude_agent_sdk import (
    TERMINAL_TASK_STATUSES,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ContextUsageResponse,
    McpStatusResponse,
    PermissionMode,
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
    PermissionUpdate,
    ResultMessage,
    TaskNotificationMessage,
    TaskProgressMessage,
    TaskStartedMessage,
    TaskUpdatedMessage,
    ToolPermissionContext,
    Transport,
    UserMessage,
)

from backend.service.desktop.log import claude_sdk_logger

from .message_adapter import (
    _EXIT_PLAN_MODE_TOOL_NAME,
    _EventFactory,
    _MessageAdapter,
    _permission_mode_from_result,
)
from .models import (
    ChatEvent,
    ChatResult,
    CompletionHandler,
    EventHandler,
    FileRewindPreview,
    PermissionHandler,
    PermissionRequestedData,
    PermissionResolvedData,
    PlanApprovalMode,
    _jsonable,
)
from .session_debug import logged_realtime_messages
from .usage import _subagent_usage, _turn_usage

_STREAM_END = object()
_EXIT_PLAN_EXECUTION_MODES = ("default", "acceptEdits", "auto")
_TERMINAL_EVENTS = frozenset({"turn.completed", "turn.failed"})


def _unhandled_event_log_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Keep unknown-event diagnostics useful without logging raw payloads."""
    fields = {
        key: data.get(key)
        for key in ("message_type", "content_block_type", "raw_type")
        if data.get(key) is not None
    }
    payload = data.get("payload")
    if isinstance(payload, dict):
        fields["payload_keys"] = sorted(str(key) for key in payload)
        if payload.get("type") is not None:
            fields["payload_type"] = payload.get("type")
        delta = payload.get("delta")
        if isinstance(delta, dict) and delta.get("type") is not None:
            fields["delta_type"] = delta.get("type")
    return fields


@dataclass(slots=True)
class _PendingPermission:
    tool_name: str
    input_data: dict[str, Any]
    ready: anyio.Event = field(default_factory=anyio.Event)
    result: PermissionResult | None = None

    def resolve(self, result: PermissionResult) -> None:
        self.result = result
        self.ready.set()


class ClaudeChatClient:
    """Persistent, single-conversation Claude client with a stable event API.

    One instance intentionally serializes human turns.  Permission callbacks
    run concurrently with SDK message reception; their events are merged into
    the same ordered stream through an internal queue.
    """

    def __init__(
        self,
        options: ClaudeAgentOptions | None = None,
        *,
        permission_handler: PermissionHandler | None = None,
        transport: Transport | None = None,
    ) -> None:
        base_options = options or ClaudeAgentOptions()
        if base_options.permission_prompt_tool_name is not None:
            raise ValueError(
                "permission_prompt_tool_name cannot be combined with the ClaudeChatClient permission event wrapper"
            )

        self._permission_handler = permission_handler or base_options.can_use_tool
        self._options = replace(
            base_options,
            can_use_tool=self._can_use_tool,
            forward_subagent_text=True,
            include_hook_events=True,
            include_partial_messages=True,
        )
        self._transport = transport
        self._sdk: ClaudeSDKClient | None = None
        self._connect_lock = anyio.Lock()
        self._turn_lock = anyio.Lock()
        self._active_queue: MemoryObjectSendStream[ChatEvent | object] | None = None
        self._active_factory: _EventFactory | None = None
        self._stop_requested: anyio.Event | None = None
        self._query_submitted = False
        self._pending_permissions: dict[str, _PendingPermission] = {}
        self._plan_approval_modes: dict[str, PlanApprovalMode] = {}
        self._user_turns = 0
        self._last_result: ChatResult | None = None

    @property
    def options(self) -> ClaudeAgentOptions:
        """The effective SDK options used by this wrapper."""
        return self._options

    @property
    def last_result(self) -> ChatResult | None:
        """The most recently completed human turn, if any."""
        return self._last_result

    @property
    def connected(self) -> bool:
        """Whether the underlying SDK connection is currently open."""
        return self._sdk is not None

    @property
    def active(self) -> bool:
        """Whether a human turn is currently being produced."""
        return self._active_queue is not None

    @property
    def pending_permission_ids(self) -> tuple[str, ...]:
        """Permission request IDs still waiting for a caller decision."""
        return tuple(self._pending_permissions)

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def connect(self) -> None:
        """Open the persistent SDK connection if it is not already open."""
        async with self._connect_lock:
            if self._sdk is not None:
                return
            sdk = ClaudeSDKClient(options=self._options, transport=self._transport)
            try:
                await sdk.connect()
            except BaseException:
                with suppress(Exception):
                    await sdk.disconnect()
                raise
            self._sdk = sdk
            # 强制触发一次异常，如果不支持这个就会报错
            await self._sdk.set_permission_mode(self._options.permission_mode)

    async def close(self) -> None:
        """Interrupt an active turn, then close the persistent connection."""
        if self._active_queue is not None:
            with suppress(Exception):
                await self.interrupt()
        async with self._turn_lock, self._connect_lock:
            sdk = self._sdk
            self._sdk = None
            if sdk is not None:
                await sdk.disconnect()

    async def interrupt(self) -> None:
        """Request cancellation of the current Claude turn."""
        sdk = self._sdk
        if sdk is not None and self._active_queue is not None:
            if self._stop_requested is not None:
                self._stop_requested.set()
            self._deny_pending_permissions("Claude turn was interrupted")
            if self._query_submitted:
                await sdk.interrupt()

    async def request_stop(self) -> None:
        """Compatibility alias for :meth:`interrupt`."""
        await self.interrupt()

    def resolve_permission(
        self,
        request_id: str,
        result: PermissionResult,
    ) -> None:
        """Resolve a pending ``permission.requested`` event.

        This is the event-driven alternative to supplying ``permission_handler``.
        For ``AskUserQuestion``, return ``PermissionResultAllow`` with the
        question's ``answers`` added to ``updated_input``.
        """
        if not isinstance(result, PermissionResultAllow | PermissionResultDeny):
            raise TypeError("result must be PermissionResultAllow or PermissionResultDeny")
        try:
            pending = self._pending_permissions[request_id]
        except KeyError as exc:
            raise KeyError(f"No pending permission request: {request_id}") from exc
        if pending.tool_name == _EXIT_PLAN_MODE_TOOL_NAME:
            raise ValueError(
                "ExitPlanMode must be resolved with resolve_plan_approval() so mode is supplied explicitly"
            )
        if pending.ready.is_set():
            raise RuntimeError(f"Permission request is already resolved: {request_id}")
        pending.resolve(result)

    def resolve_plan_approval(
        self,
        request_id: str,
        *,
        approved: bool,
        mode: PlanApprovalMode,
        message: str = "",
    ) -> None:
        """Resolve an ``ExitPlanMode`` request with an explicit mode choice.

        The selected mode is sent to Claude Code as a session permission
        update. The resulting SDK ``system/status`` event is the authoritative
        effective mode and is surfaced as ``permission.mode.changed``. A
        ``None`` mode sends no explicit update and is retained only for
        low-level SDK compatibility; it has no effect when ``approved`` is
        false.
        """
        try:
            pending = self._pending_permissions[request_id]
        except KeyError as exc:
            raise KeyError(f"No pending permission request: {request_id}") from exc
        if pending.tool_name != _EXIT_PLAN_MODE_TOOL_NAME:
            raise ValueError(f"Permission request {request_id!r} is for {pending.tool_name!r}, not ExitPlanMode")
        if pending.ready.is_set():
            raise RuntimeError(f"Permission request is already resolved: {request_id}")
        if approved and mode is None:
            raise ValueError("Approved ExitPlanMode requires an explicit permission mode")
        if mode is not None and mode not in _EXIT_PLAN_EXECUTION_MODES:
            modes = ", ".join(_EXIT_PLAN_EXECUTION_MODES)
            raise ValueError(f"Unknown permission mode {mode!r}; expected one of: {modes}")

        if not approved:
            pending.resolve(PermissionResultDeny(message=message or "Plan was not approved"))
            return

        updated_permissions = None
        if mode is not None:
            updated_permissions = [
                PermissionUpdate(
                    type="setMode",
                    mode=mode,
                    destination="session",
                )
            ]
        pending.resolve(
            PermissionResultAllow(
                updated_input=pending.input_data,
                updated_permissions=updated_permissions,
            )
        )

    async def set_permission_mode(self, mode: PermissionMode) -> None:
        """Change the SDK permission mode on the live connection."""
        await self.connect()
        if self._sdk is None:  # pragma: no cover - guarded by connect
            raise RuntimeError("Claude SDK client is not connected")
        await self._sdk.set_permission_mode(mode)
        # Keep the wrapper's effective options in sync with the live SDK
        # session so a later retained turn does not revert this change.
        self._options = replace(self._options, permission_mode=mode)

    async def set_model(self, model: str | None) -> None:
        """Change the model used by the live connection."""
        await self.connect()
        if self._sdk is None:  # pragma: no cover - guarded by connect
            raise RuntimeError("Claude SDK client is not connected")
        await self._sdk.set_model(model)

    async def get_server_info(self) -> dict[str, Any] | None:
        """Return initialized Claude Code server metadata."""
        await self.connect()
        if self._sdk is None:  # pragma: no cover - guarded by connect
            raise RuntimeError("Claude SDK client is not connected")
        return await self._sdk.get_server_info()

    async def get_mcp_status(self) -> McpStatusResponse:
        """Return the status of configured MCP servers."""
        sdk = await self._connected_sdk()
        return await sdk.get_mcp_status()

    async def get_context_usage(self) -> ContextUsageResponse:
        """Return the current context-window usage breakdown."""
        sdk = await self._connected_sdk()
        return await sdk.get_context_usage()

    async def reconnect_mcp_server(self, server_name: str) -> None:
        """Reconnect one failed or disconnected MCP server."""
        sdk = await self._connected_sdk()
        await sdk.reconnect_mcp_server(server_name)

    async def toggle_mcp_server(self, server_name: str, *, enabled: bool) -> None:
        """Enable or disable one MCP server for this connection."""
        sdk = await self._connected_sdk()
        await sdk.toggle_mcp_server(server_name, enabled)

    async def stop_task(self, task_id: str) -> None:
        """Stop one background task running in this session."""
        sdk = await self._connected_sdk()
        await sdk.stop_task(task_id)

    async def preview_file_rewind(self, user_message_id: str) -> FileRewindPreview:
        """Inspect a checkpoint without sending a prompt or modifying files.

        Python SDK 0.2.157 omits the CLI's dry_run parameter and response.
        Keep this version-dependent control-protocol bridge isolated here.
        """
        if self.active:
            raise ValueError("会话正在生成，请稍后查询文件检查点")
        async with self._turn_lock:
            sdk = await self._connected_sdk()
            query = sdk._query
            if query is None:
                raise RuntimeError("SDK 未连接，无法查询文件检查点")
            try:
                with anyio.fail_after(5):
                    result = await query._send_control_request({
                        "subtype": "rewind_files", "user_message_id": user_message_id, "dry_run": True,
                    })
            except Exception as error:
                # SDK control errors are plain Exception in the installed version.
                raise RuntimeError("SDK 文件检查点预览不可用") from error
            if not isinstance(result, dict) or type(result.get("canRewind")) is not bool:
                raise RuntimeError("SDK 返回了无效的文件检查点预览")
            return FileRewindPreview.from_sdk(result)

    async def rewind_files(self, user_message_id: str) -> None:
        """Restore files to a checkpoint created for a user message."""
        if self.active:
            raise ValueError("会话正在生成，请先停止后再恢复文件")
        async with self._turn_lock:
            sdk = await self._connected_sdk()
            await sdk.rewind_files(user_message_id)

    async def _connected_sdk(self) -> ClaudeSDKClient:
        await self.connect()
        if self._sdk is None:  # pragma: no cover - guarded by connect
            raise RuntimeError("Claude SDK client is not connected")
        return self._sdk

    async def send(
        self,
        prompt: str,
        *,
        session_id: str = "default",
        on_event: EventHandler | None = None,
        on_complete: CompletionHandler | None = None,
        empty_result_content: str | None = None,
    ) -> ChatResult:
        """Run one human turn and invoke completion before its terminal event."""
        terminal_event: ChatEvent | None = None

        async def forward(event: ChatEvent) -> None:
            if on_event is None:
                return
            handled = on_event(event)
            if inspect.isawaitable(handled):
                await handled

        try:
            async with aclosing(self.stream(
                prompt,
                session_id=session_id,
                empty_result_content=empty_result_content,
            )) as events:
                async for event in events:
                    if event.event in _TERMINAL_EVENTS:
                        terminal_event = event
                    else:
                        await forward(event)
            if self._last_result is None:
                raise RuntimeError("Claude turn ended without a result")
            return self._last_result
        finally:
            try:
                if on_complete is not None:
                    handled = on_complete()
                    if inspect.isawaitable(handled):
                        await handled
            finally:
                if terminal_event is not None:
                    await forward(terminal_event)

    async def stream(
        self,
        prompt: str,
        *,
        session_id: str = "default",
        empty_result_content: str | None = None,
    ) -> AsyncIterator[ChatEvent]:
        """Yield one complete realtime event stream for a human prompt.

        The submitted input is stamped with ``origin.kind == 'human'``.  This
        lets the client keep consuming past Claude Code injected turns until
        the result belonging to this prompt arrives.
        """
        if not prompt:
            raise ValueError("prompt must not be empty")

        async with self._turn_lock:
            await self.connect()
            if self._sdk is None:  # pragma: no cover - guarded by connect
                raise RuntimeError("Claude SDK client is not connected")

            self._user_turns += 1
            self._last_result = None
            turn_id = str(uuid4())
            factory = _EventFactory(turn_id)
            queue, receiver = anyio.create_memory_object_stream[ChatEvent | object](float("inf"))
            stop_requested = anyio.Event()
            error: list[BaseException] = []
            self._active_queue = queue
            self._active_factory = factory
            self._stop_requested = stop_requested
            self._query_submitted = False

            queue.send_nowait(
                factory.make(
                    "turn.started",
                    {
                        "user_turn": self._user_turns,
                        "session_id_requested": session_id,
                    },
                )
            )
            queue.send_nowait(
                factory.make(
                    "user.message",
                    {
                        "content": prompt,
                        "message_uuid": turn_id,
                        "origin": {"kind": "human"},
                        "source": "human",
                        "submitted": True,
                    },
                )
            )

            consumer_error: BaseException | None = None
            async with anyio.create_task_group() as group:
                producer = group.create_task(self._produce_turn(
                    prompt=prompt,
                    session_id=session_id,
                    factory=factory,
                    queue=queue,
                    error=error,
                    empty_result_content=empty_result_content,
                    stop_requested=stop_requested,
                ))
                try:
                    # Publish the input before SDK reception can echo it back.
                    for _ in range(2):
                        yield cast(ChatEvent, receiver.receive_nowait())
                    while True:
                        item = await receiver.receive()
                        if item is _STREAM_END:
                            break
                        yield cast(ChatEvent, item)
                    await producer.wait()
                except BaseException as exc:  # noqa: BLE001 - re-raise after the task group closes
                    consumer_error = exc
                finally:
                    with anyio.CancelScope(shield=True):
                        if producer.status in {anyio.TaskHandle.Status.PENDING, anyio.TaskHandle.Status.CANCELLING}:
                            with anyio.move_on_after(10):
                                with suppress(Exception):
                                    await self.interrupt()
                                await producer.wait()
                            producer.cancel()
                            await producer.wait()
                        await queue.aclose()
                        await receiver.aclose()
                    self._active_queue = None
                    self._active_factory = None
                    self._stop_requested = None
                    self._query_submitted = False
            if consumer_error is not None:
                raise consumer_error
            if error:
                raise error[0]

    async def _produce_turn(
        self,
        *,
        prompt: str,
        session_id: str,
        factory: _EventFactory,
        queue: MemoryObjectSendStream[ChatEvent | object],
        error: list[BaseException],
        empty_result_content: str | None,
        stop_requested: anyio.Event,
    ) -> None:
        sdk = self._sdk
        if sdk is None:  # pragma: no cover - guarded by stream
            raise RuntimeError("Claude SDK client is not connected")
        adapter = _MessageAdapter(factory, self._plan_approval_modes)
        requested_result: ResultMessage | None = None
        deferred_human_result: ResultMessage | None = None
        logical_results: list[ResultMessage] = []
        turn_events: list[ChatEvent] = []
        active_task_ids: set[str] = set()
        background_chain_started = False
        checkpoint_ids: set[str] = set()

        async def submitted_message() -> AsyncIterator[dict[str, Any]]:
            yield {
                "type": "user",
                "message": {"role": "user", "content": prompt},
                "parent_tool_use_id": None,
                "session_id": session_id,
                "uuid": factory.turn_id,
                "origin": {"kind": "human"},
            }

        try:
            await sdk.query(submitted_message(), session_id=session_id)
            self._query_submitted = True
            if stop_requested.is_set():
                await sdk.interrupt()
            while requested_result is None:
                received_result = False
                async for message in logged_realtime_messages(
                    sdk.receive_response(),
                    session_id=session_id,
                ):
                    if isinstance(message, (TaskStartedMessage, TaskProgressMessage)):
                        active_task_ids.add(message.task_id)
                        background_chain_started = True
                        claude_sdk_logger.info(
                            "Claude SDK task lifecycle | kind={} task_id={} "
                            "active_tasks={}",
                            type(message).__name__,
                            message.task_id,
                            sorted(active_task_ids),
                        )
                    elif isinstance(message, TaskNotificationMessage):
                        active_task_ids.discard(message.task_id)
                        if stop_requested.is_set() and message.status == "stopped":
                            # An interrupted task will not produce the
                            # continuation ResultMessage that a normal
                            # task-notification produces. Reuse the deferred
                            # human result so the stopped turn can terminate.
                            if (
                                not active_task_ids
                                and deferred_human_result is not None
                            ):
                                requested_result = deferred_human_result
                                claude_sdk_logger.info(
                                    "Claude SDK stopped task selected deferred result | "
                                    "task_id={} active_tasks={}",
                                    message.task_id,
                                    sorted(active_task_ids),
                                )
                        else:
                            background_chain_started = True
                        claude_sdk_logger.info(
                            "Claude SDK task lifecycle | kind={} task_id={} "
                            "status={} stop_requested={} active_tasks={}",
                            type(message).__name__,
                            message.task_id,
                            message.status,
                            stop_requested.is_set(),
                            sorted(active_task_ids),
                        )
                    elif isinstance(message, TaskUpdatedMessage):
                        status = message.status
                        if status is None:
                            raw_status = message.patch.get("status")
                            status = raw_status if isinstance(raw_status, str) else None
                        if status in TERMINAL_TASK_STATUSES:
                            active_task_ids.discard(message.task_id)
                        elif status is not None:
                            active_task_ids.add(message.task_id)
                            background_chain_started = True
                        claude_sdk_logger.info(
                            "Claude SDK task lifecycle | kind={} task_id={} "
                            "status={} active_tasks={}",
                            type(message).__name__,
                            message.task_id,
                            status,
                            sorted(active_task_ids),
                        )

                    if self._options.enable_file_checkpointing and isinstance(message, UserMessage):
                        checkpoint = adapter.file_checkpoint(message)
                        if checkpoint is not None and message.uuid not in checkpoint_ids:
                            checkpoint_ids.add(message.uuid)
                            await queue.send(checkpoint)

                    is_submitted_echo = (
                        isinstance(message, UserMessage)
                        and message.uuid == factory.turn_id
                        and message.origin is not None
                        and message.origin.get("kind") == "human"
                    )
                    if not is_submitted_echo:
                        adapted_events = adapter.adapt(message)
                        turn_events.extend(adapted_events)
                        for event in adapted_events:
                            if event.event == "sdk.unhandled":
                                claude_sdk_logger.warning(
                                    "Claude SDK unhandled event | turn_id={} "
                                    "model_turn_id={} fields={}",
                                    event.turn_id,
                                    event.model_turn_id,
                                    _unhandled_event_log_fields(event.data),
                                )
                            if event.event == "permission.mode.changed":
                                mode = event.data.get("mode")
                                if isinstance(mode, str):
                                    self._options = replace(
                                        self._options,
                                        permission_mode=mode,
                                    )
                            await queue.send(event)

                    if not isinstance(message, ResultMessage):
                        continue

                    received_result = True
                    origin = dict(message.origin) if message.origin else None
                    origin_kind = origin.get("kind") if origin else None
                    claude_sdk_logger.info(
                        "Claude SDK ResultMessage | origin_kind={} subtype={} "
                        "is_error={} stop_reason={} terminal_reason={} "
                        "active_tasks={} background_chain={}",
                        origin_kind,
                        message.subtype,
                        message.is_error,
                        message.stop_reason,
                        message.terminal_reason,
                        sorted(active_task_ids),
                        background_chain_started,
                    )
                    is_human_result = origin_kind in {None, "human"}
                    is_background_continuation = origin_kind in {
                        "auto-continuation",
                        "task-notification",
                    }
                    if is_human_result or (
                        deferred_human_result is not None
                        and background_chain_started
                        and is_background_continuation
                    ):
                        logical_results.append(message)
                    waiting_for_background = bool(active_task_ids)
                    if (
                        requested_result is None
                        and is_human_result
                        and not waiting_for_background
                    ):
                        requested_result = message
                        claude_sdk_logger.info(
                            "Claude SDK ResultMessage selected as requested result | "
                            "origin_kind={} active_tasks={}",
                            origin_kind,
                            sorted(active_task_ids),
                        )
                        continue

                    if is_human_result:
                        deferred_human_result = message

                    await queue.send(
                        factory.make(
                            "turn.proxy.completed",
                            {
                                "origin": origin,
                                "subtype": message.subtype,
                                "is_error": message.is_error,
                                "num_turns": message.num_turns,
                                "stop_reason": message.stop_reason,
                                "terminal_reason": message.terminal_reason,
                            },
                            session_id=message.session_id,
                        )
                    )

                    if (
                        not is_human_result
                        and deferred_human_result is not None
                        and background_chain_started
                        and is_background_continuation
                        and not waiting_for_background
                    ):
                        requested_result = message
                        claude_sdk_logger.info(
                            "Claude SDK continuation ResultMessage selected | "
                            "origin_kind={} active_tasks={}",
                            origin_kind,
                            sorted(active_task_ids),
                        )

                if not received_result:
                    claude_sdk_logger.warning(
                        "Claude SDK receive_response ended without ResultMessage | "
                        "active_tasks={} deferred_human_result={} "
                        "background_chain={}",
                        sorted(active_task_ids),
                        deferred_human_result is not None,
                        background_chain_started,
                    )
                    if deferred_human_result is not None and not active_task_ids:
                        requested_result = deferred_human_result
                    break

            if requested_result is None:
                raise RuntimeError("Claude SDK message stream ended without a result")

            primary_model = (
                adapter.main_models[-1]
                if adapter.main_models
                else self._options.model
            )
            final_usage = _turn_usage(
                logical_results,
                primary_model,
                adapter.last_main_stop_reason,
                _subagent_usage(turn_events),
            )
            content = requested_result.result
            if content is None:
                content = "\n\n".join(part for part in adapter.main_text if part)
            if not content.strip() and empty_result_content is not None:
                content = empty_result_content.strip()
            result = ChatResult(
                content=content,
                session_id=requested_result.session_id,
                usage=final_usage,
                is_error=requested_result.is_error,
                subtype=requested_result.subtype,
                errors=tuple(requested_result.errors or ()),
                structured_output=requested_result.structured_output,
                permission_denials=tuple(requested_result.permission_denials or ()),
                deferred_tool_use=requested_result.deferred_tool_use,
                api_error_status=requested_result.api_error_status,
                duration_ms=requested_result.duration_ms,
                duration_api_ms=requested_result.duration_api_ms,
            )
            self._last_result = result
            await queue.send(
                factory.make(
                    "turn.completed",
                    {
                        "content": result.content,
                        "is_error": result.is_error,
                        "subtype": result.subtype,
                        "errors": result.errors,
                        "structured_output": result.structured_output,
                        "permission_denials": result.permission_denials,
                        "deferred_tool_use": result.deferred_tool_use,
                        "api_error_status": result.api_error_status,
                        "duration_ms": result.duration_ms,
                        "duration_api_ms": result.duration_api_ms,
                        "origin": requested_result.origin,
                        "result_uuid": requested_result.uuid,
                        "usage": result.usage.to_dict(),
                    },
                    session_id=result.session_id,
                )
            )
        except BaseException as exc:
            self._deny_pending_permissions("Claude turn failed")
            with anyio.CancelScope(shield=True):
                await self._discard_sdk(sdk)
            if isinstance(exc, anyio.get_cancelled_exc_class()):
                raise
            error.append(exc)
            await queue.send(
                factory.make(
                    "turn.failed",
                    {"error_type": type(exc).__name__, "message": str(exc)},
                )
            )
        finally:
            self._query_submitted = False
            self._plan_approval_modes.clear()
            queue.send_nowait(_STREAM_END)

    async def _discard_sdk(self, sdk: ClaudeSDKClient) -> None:
        """Disconnect a connection whose stream state is no longer reliable."""
        async with self._connect_lock:
            if self._sdk is not sdk:
                return
            self._sdk = None
            with suppress(Exception):
                await sdk.disconnect()

    async def _can_use_tool(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResult:
        """Wrap SDK permission requests and their concrete result objects."""
        queue = self._active_queue
        factory = self._active_factory
        request_id = context.tool_use_id or str(uuid4())
        if request_id in self._pending_permissions:
            request_id = str(uuid4())
        pending: _PendingPermission | None = None
        if self._permission_handler is None and (queue is None or factory is None):
            return PermissionResultDeny(message="Permission request arrived outside an active event stream")
        if self._permission_handler is None:
            pending = _PendingPermission(
                tool_name=tool_name,
                input_data=input_data,
            )
            self._pending_permissions[request_id] = pending
        if queue is not None and factory is not None:
            serialized_suggestions = cast(
                list[dict[str, Any]],
                _jsonable(context.suggestions),
            )
            await queue.send(
                factory.make(
                    "permission.requested",
                    PermissionRequestedData(
                        request_id=request_id,
                        tool_id=context.tool_use_id,
                        tool_name=tool_name,
                        tool_input=input_data,
                        agent_id=context.agent_id,
                        blocked_path=context.blocked_path,
                        decision_reason=context.decision_reason,
                        title=context.title,
                        display_name=context.display_name,
                        description=context.description,
                        suggestions=serialized_suggestions,
                    ),
                )
            )

        if self._permission_handler is None:
            if pending is None:  # pragma: no cover - initialized above
                raise RuntimeError("Permission future was not initialized")
            try:
                await pending.ready.wait()
                if pending.result is None:  # pragma: no cover - resolve sets the result first
                    raise RuntimeError("Permission result was not initialized")
                result: PermissionResult = pending.result
            finally:
                self._pending_permissions.pop(request_id, None)
        else:
            result = await self._permission_handler(tool_name, input_data, context)

        if not isinstance(result, PermissionResultAllow | PermissionResultDeny):
            raise TypeError("permission_handler must return PermissionResultAllow or PermissionResultDeny")

        if tool_name == _EXIT_PLAN_MODE_TOOL_NAME and context.tool_use_id is not None:
            self._plan_approval_modes[context.tool_use_id] = _permission_mode_from_result(result)

        if queue is not None and factory is not None:
            if isinstance(result, PermissionResultAllow):
                updated_permissions = (
                    cast(
                        list[dict[str, Any]],
                        _jsonable(result.updated_permissions),
                    )
                    if result.updated_permissions is not None
                    else None
                )
                resolved_data = PermissionResolvedData(
                    request_id=request_id,
                    tool_id=context.tool_use_id,
                    tool_name=tool_name,
                    behavior="allow",
                    updated_input=result.updated_input,
                    updated_permissions=updated_permissions,
                    denial_message=None,
                    interrupt=False,
                )
            else:
                resolved_data = PermissionResolvedData(
                    request_id=request_id,
                    tool_id=context.tool_use_id,
                    tool_name=tool_name,
                    behavior="deny",
                    updated_input=None,
                    updated_permissions=None,
                    denial_message=result.message,
                    interrupt=result.interrupt,
                )
            await queue.send(
                factory.make(
                    "permission.resolved",
                    resolved_data,
                )
            )
        return result

    def _deny_pending_permissions(self, message: str) -> None:
        for pending in tuple(self._pending_permissions.values()):
            if not pending.ready.is_set():
                pending.resolve(PermissionResultDeny(message=message, interrupt=True))
