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
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionMode,
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
    PermissionUpdate,
    ResultMessage,
    ToolPermissionContext,
    Transport,
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
    ModelUsage,
    PermissionHandler,
    PermissionRequestedData,
    PermissionResolvedData,
    PlanApprovalMode,
    _jsonable,
)
from .usage import _UsageAccumulator

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
        self._pending_permissions: dict[str, _PendingPermission] = {}
        self._plan_approval_modes: dict[str, PlanApprovalMode] = {}
        self._user_turns = 0
        self._actual_turns = 0
        self._usage_baseline: dict[str, ModelUsage] = {}
        self._last_result: ChatResult | None = None

    @property
    def options(self) -> ClaudeAgentOptions:
        """The effective SDK options used by this wrapper."""
        return self._options

    @property
    def last_result(self) -> ChatResult | None:
        """The most recently completed human turn, if any."""
        return self._last_result

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
        sdk = self._sdk
        if sdk is not None and self._active_queue is not None:
            self._deny_pending_permissions("Claude client is closing")
            with suppress(Exception):
                await sdk.interrupt()
        async with self._turn_lock, self._connect_lock:
            sdk = self._sdk
            self._sdk = None
            if sdk is not None:
                await sdk.disconnect()

    async def interrupt(self) -> None:
        """Request cancellation of the current Claude turn."""
        sdk = self._sdk
        if sdk is not None and self._active_queue is not None:
            self._deny_pending_permissions("Claude turn was interrupted")
            await sdk.interrupt()

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

    async def send(
        self,
        prompt: str,
        *,
        session_id: str = "default",
        on_event: EventHandler | None = None,
    ) -> ChatResult:
        """Run one human turn, optionally forwarding each realtime event."""
        async for event in self.stream(prompt, session_id=session_id):
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
            error: list[BaseException] = []
            self._active_queue = queue
            self._active_factory = factory

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
                self._active_queue = None
                self._active_factory = None
                if not producer.done():
                    self._deny_pending_permissions("Event stream consumer disconnected")
                    with suppress(Exception):
                        await self._sdk.interrupt()
                    try:
                        await asyncio.wait_for(asyncio.shield(producer), timeout=10)
                    except TimeoutError:
                        producer.cancel()
                        with suppress(asyncio.CancelledError):
                            await producer

    async def _produce_turn(
        self,
        *,
        prompt: str,
        session_id: str,
        factory: _EventFactory,
        queue: asyncio.Queue[ChatEvent | object],
        error: list[BaseException],
    ) -> None:
        sdk = self._sdk
        if sdk is None:  # pragma: no cover - guarded by stream
            raise RuntimeError("Claude SDK client is not connected")
        adapter = _MessageAdapter(factory, self._plan_approval_modes)
        usage = _UsageAccumulator(self._usage_baseline)
        requested_result: ResultMessage | None = None

        async def submitted_message() -> AsyncIterator[dict[str, Any]]:
            yield {
                "type": "user",
                "message": {"role": "user", "content": prompt},
                "parent_tool_use_id": None,
                "session_id": session_id,
                "origin": {"kind": "human"},
            }

        try:
            await sdk.query(submitted_message(), session_id=session_id)
            async for message in sdk.receive_messages():
                for event in adapter.adapt(message):
                    await queue.put(event)

                if not isinstance(message, ResultMessage):
                    continue

                fallback_model = adapter.main_models[-1] if adapter.main_models else self._options.model
                usage.add(message, fallback_model)
                self._actual_turns += max(message.num_turns, 0)
                origin = dict(message.origin) if message.origin else None
                origin_kind = origin.get("kind") if origin else None
                if origin_kind not in {None, "human"}:
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
                    continue

                requested_result = message
                break

            if requested_result is None:
                raise RuntimeError("Claude SDK message stream ended without a result")

            primary_model = adapter.main_models[-1] if adapter.main_models else self._options.model
            final_usage = usage.finish(
                user_turns=self._user_turns,
                cumulative_actual_turns=self._actual_turns,
                primary_model=primary_model,
                result=requested_result,
                fallback_stop_reason=adapter.last_main_stop_reason,
            )
            cumulative_snapshot = usage.cumulative_snapshot
            if cumulative_snapshot is not None:
                self._usage_baseline = cumulative_snapshot
            content = requested_result.result
            if content is None:
                content = "\n\n".join(part for part in adapter.main_text if part)
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
            await queue.put(_STREAM_END)

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
                    parent_tool_use_id=context.agent_id,
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
                    parent_tool_use_id=context.agent_id,
                )
            )
        return result

    def _deny_pending_permissions(self, message: str) -> None:
        for pending in tuple(self._pending_permissions.values()):
            if not pending.future.done():
                pending.future.set_result(PermissionResultDeny(message=message, interrupt=True))
