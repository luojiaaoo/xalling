"""Client lifecycle for the event-oriented Claude Agent SDK wrapper."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, replace
from types import TracebackType
from typing import Any, Self, cast, get_args
from uuid import uuid4

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

from .message_adapter import (
    _EXIT_PLAN_MODE_TOOL_NAME,
    _EventFactory,
    _MessageAdapter,
    _permission_mode_from_result,
)
from .models import (
    ChatEvent,
    ChatResult,
    EventHandler,
    PermissionHandler,
    PermissionRequestedData,
    PermissionResolvedData,
    PlanApprovalMode,
    _jsonable,
)
from .usage import _turn_usage

_STREAM_END = object()


@dataclass(slots=True)
class _PendingPermission:
    tool_name: str
    input_data: dict[str, Any]
    future: asyncio.Future[PermissionResult]


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
        self._connect_lock = asyncio.Lock()
        self._turn_lock = asyncio.Lock()
        self._active_queue: asyncio.Queue[ChatEvent | object] | None = None
        self._active_factory: _EventFactory | None = None
        self._stop_requested: asyncio.Event | None = None
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
        if pending.future.done():
            raise RuntimeError(f"Permission request is already resolved: {request_id}")
        pending.future.set_result(result)

    def resolve_plan_approval(
        self,
        request_id: str,
        *,
        approved: bool,
        mode: PlanApprovalMode,
        message: str = "",
    ) -> None:
        """Resolve an ``ExitPlanMode`` request with an explicit mode choice.

        ``mode`` is intentionally a required keyword argument. Pass ``None``
        to let Claude Code restore the mode active before plan mode. Pass a
        concrete :class:`PermissionMode` to switch the session to that mode.
        ``mode`` has no effect when ``approved`` is false.
        """
        try:
            pending = self._pending_permissions[request_id]
        except KeyError as exc:
            raise KeyError(f"No pending permission request: {request_id}") from exc
        if pending.tool_name != _EXIT_PLAN_MODE_TOOL_NAME:
            raise ValueError(f"Permission request {request_id!r} is for {pending.tool_name!r}, not ExitPlanMode")
        if pending.future.done():
            raise RuntimeError(f"Permission request is already resolved: {request_id}")
        permission_modes = get_args(PermissionMode)
        if mode is not None and mode not in permission_modes:
            modes = ", ".join(permission_modes)
            raise ValueError(f"Unknown permission mode {mode!r}; expected one of: {modes}")

        if not approved:
            pending.future.set_result(PermissionResultDeny(message=message or "Plan was not approved"))
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
        pending.future.set_result(
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

    async def rewind_files(self, user_message_id: str) -> None:
        """Restore files to a checkpoint created for a user message."""
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
        empty_result_content: str | None = None,
    ) -> ChatResult:
        """Run one human turn, optionally forwarding each realtime event."""
        async for event in self.stream(
            prompt,
            session_id=session_id,
            empty_result_content=empty_result_content,
        ):
            if on_event is not None:
                handled = on_event(event)
                if inspect.isawaitable(handled):
                    await handled
        if self._last_result is None:
            raise RuntimeError("Claude turn ended without a result")
        return self._last_result

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
            queue: asyncio.Queue[ChatEvent | object] = asyncio.Queue()
            stop_requested = asyncio.Event()
            error: list[BaseException] = []
            self._active_queue = queue
            self._active_factory = factory
            self._stop_requested = stop_requested
            self._query_submitted = False

            await queue.put(
                factory.make(
                    "turn.started",
                    {
                        "user_turn": self._user_turns,
                        "session_id_requested": session_id,
                    },
                )
            )
            await queue.put(
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

            producer = asyncio.create_task(
                self._produce_turn(
                    prompt=prompt,
                    session_id=session_id,
                    factory=factory,
                    queue=queue,
                    error=error,
                    empty_result_content=empty_result_content,
                    stop_requested=stop_requested,
                )
            )
            try:
                while True:
                    item = await queue.get()
                    if item is _STREAM_END:
                        break
                    yield cast(ChatEvent, item)
                await producer
                if error:
                    raise error[0]
            finally:
                if not producer.done():
                    with suppress(Exception):
                        await self.interrupt()
                    try:
                        await asyncio.wait_for(asyncio.shield(producer), timeout=10)
                    except TimeoutError:
                        producer.cancel()
                        with suppress(asyncio.CancelledError):
                            await producer
                self._active_queue = None
                self._active_factory = None
                self._stop_requested = None
                self._query_submitted = False

    async def _produce_turn(
        self,
        *,
        prompt: str,
        session_id: str,
        factory: _EventFactory,
        queue: asyncio.Queue[ChatEvent | object],
        error: list[BaseException],
        empty_result_content: str | None,
        stop_requested: asyncio.Event,
    ) -> None:
        sdk = self._sdk
        if sdk is None:  # pragma: no cover - guarded by stream
            raise RuntimeError("Claude SDK client is not connected")
        adapter = _MessageAdapter(factory, self._plan_approval_modes)
        requested_result: ResultMessage | None = None
        deferred_human_result: ResultMessage | None = None
        active_task_ids: set[str] = set()
        pending_notification_turns = 0
        background_chain_started = False

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
                async for message in sdk.receive_response():
                    if isinstance(message, (TaskStartedMessage, TaskProgressMessage)):
                        active_task_ids.add(message.task_id)
                        background_chain_started = True
                    elif isinstance(message, TaskNotificationMessage):
                        active_task_ids.discard(message.task_id)
                        pending_notification_turns += 1
                        background_chain_started = True
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

                    is_submitted_echo = (
                        isinstance(message, UserMessage)
                        and message.uuid == factory.turn_id
                        and message.origin is not None
                        and message.origin.get("kind") == "human"
                    )
                    if not is_submitted_echo:
                        for event in adapter.adapt(message):
                            await queue.put(event)

                    if not isinstance(message, ResultMessage):
                        continue

                    received_result = True
                    origin = dict(message.origin) if message.origin else None
                    origin_kind = origin.get("kind") if origin else None
                    is_human_result = origin_kind in {None, "human"}
                    if origin_kind == "task-notification" and pending_notification_turns:
                        pending_notification_turns -= 1

                    waiting_for_background = bool(
                        active_task_ids or pending_notification_turns
                    )
                    if is_human_result and not waiting_for_background:
                        requested_result = message
                        continue

                    if is_human_result:
                        deferred_human_result = message

                    await queue.put(
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

                    is_background_continuation = origin_kind in {
                        "auto-continuation",
                        "task-notification",
                    }
                    if (
                        not is_human_result
                        and deferred_human_result is not None
                        and background_chain_started
                        and is_background_continuation
                        and not waiting_for_background
                    ):
                        requested_result = message

                if not received_result:
                    if (
                        deferred_human_result is not None
                        and not active_task_ids
                        and not pending_notification_turns
                    ):
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
                requested_result,
                primary_model,
                adapter.last_main_stop_reason,
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
            await queue.put(
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
            await self._discard_sdk(sdk)
            if isinstance(exc, asyncio.CancelledError):
                raise
            error.append(exc)
            await queue.put(
                factory.make(
                    "turn.failed",
                    {"error_type": type(exc).__name__, "message": str(exc)},
                )
            )
        finally:
            self._query_submitted = False
            self._plan_approval_modes.clear()
            await queue.put(_STREAM_END)

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
            future: asyncio.Future[PermissionResult] = asyncio.get_running_loop().create_future()
            pending = _PendingPermission(
                tool_name=tool_name,
                input_data=input_data,
                future=future,
            )
            self._pending_permissions[request_id] = pending
        if queue is not None and factory is not None:
            serialized_suggestions = cast(
                list[dict[str, Any]],
                _jsonable(context.suggestions),
            )
            await queue.put(
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
                result: PermissionResult = await pending.future
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
            await queue.put(
                factory.make(
                    "permission.resolved",
                    resolved_data,
                )
            )
        return result

    def _deny_pending_permissions(self, message: str) -> None:
        for pending in tuple(self._pending_permissions.values()):
            if not pending.future.done():
                pending.future.set_result(PermissionResultDeny(message=message, interrupt=True))
