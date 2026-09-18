from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, ClassVar

import anyio
import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    PermissionResult,
    PermissionResultAllow,
    ResultMessage,
    StreamEvent,
    TaskNotificationMessage,
    TaskStartedMessage,
    TextBlock,
    ToolPermissionContext,
    ToolUseBlock,
    UserMessage,
)

from backend.claude_chat_client import ClaudeChatClient


class _FakeSDK:
    batches: ClassVar[list[list[object]]] = []
    instances: ClassVar[list[_FakeSDK]] = []

    def __init__(
        self,
        options: ClaudeAgentOptions,
        transport: object | None = None,
    ) -> None:
        self.options = options
        self.transport = transport
        self.connected = False
        self.disconnected = False
        self.interrupted = False
        self.queries: list[dict[str, Any]] = []
        self.permission_result: PermissionResult | None = None
        self.__class__.instances.append(self)

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def interrupt(self) -> None:
        self.interrupted = True

    async def query(
        self,
        prompt: AsyncIterator[dict[str, Any]],
        session_id: str = "default",
    ) -> None:
        self.queries.extend([message async for message in prompt])

    async def receive_response(self) -> AsyncIterator[object]:
        if not self.__class__.batches:
            return
        batch = self.__class__.batches.pop(0)
        for item in batch:
            if isinstance(item, BaseException):
                raise item
            if item == "permission":
                if self.options.can_use_tool is None:  # pragma: no cover
                    raise AssertionError("permission callback missing")
                self.permission_result = await self.options.can_use_tool(
                    "Write",
                    {"file_path": "unsafe.txt"},
                    ToolPermissionContext(tool_use_id="tool-1", agent_id="agent-1"),
                )
                continue
            yield item

    async def set_permission_mode(self, mode: str) -> None:
        self.permission_mode = mode

    async def set_model(self, model: str | None) -> None:
        self.model = model

    async def get_server_info(self) -> dict[str, Any]:
        return {"session_id": "session-1"}

    async def get_mcp_status(self) -> dict[str, Any]:
        return {"mcpServers": []}

    async def get_context_usage(self) -> dict[str, Any]:
        return {"totalTokens": 12, "maxTokens": 100, "percentage": 12.0}

    async def reconnect_mcp_server(self, server_name: str) -> None:
        self.reconnected_server = server_name

    async def toggle_mcp_server(self, server_name: str, enabled: bool) -> None:
        self.toggled_server = (server_name, enabled)

    async def stop_task(self, task_id: str) -> None:
        self.stopped_task = task_id

    async def rewind_files(self, user_message_id: str) -> None:
        self.rewound_message = user_message_id


@pytest.fixture(autouse=True)
def _reset_fake_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeSDK.batches = []
    _FakeSDK.instances = []
    monkeypatch.setattr(
        "backend.claude_chat_client.client.ClaudeSDKClient",
        _FakeSDK,
    )


def test_client_consumes_proxy_results_and_correlates_user_turn() -> None:
    anyio.run(_client_consumes_proxy_results_and_correlates_user_turn)


async def _client_consumes_proxy_results_and_correlates_user_turn() -> None:
    _FakeSDK.batches = [
        [
            UserMessage(
                content="Inspect the project",
                uuid="replaced-below",
                origin={"kind": "human"},
            ),
            AssistantMessage(
                content=[TextBlock(text="Background update")],
                model="test-model",
            ),
            _result(
                origin={"kind": "task-notification"},
                num_turns=1,
                input_tokens=10,
                output_tokens=5,
            ),
        ],
        [
            AssistantMessage(
                content=[TextBlock(text="Final answer")],
                model="test-model",
                stop_reason="end_turn",
            ),
            _result(
                origin={"kind": "human"},
                num_turns=2,
                input_tokens=30,
                output_tokens=12,
            ),
        ],
    ]
    client = ClaudeChatClient(ClaudeAgentOptions(model="test-model"))
    events = []

    async for event in client.stream("Inspect the project"):
        events.append(event)
        if event.event == "turn.started":
            _FakeSDK.batches[0][0].uuid = event.turn_id

    result = client.last_result
    assert result is not None
    assert result.content == "Final answer"
    assert result.usage.input_tokens == 30
    assert result.usage.output_tokens == 12
    assert [event.event for event in events].count("user.message") == 1
    assert any(event.event == "turn.proxy.completed" for event in events)
    model_turn_ids = [
        event.model_turn_id
        for event in events
        if event.event == "assistant.message.completed"
    ]
    assert len(model_turn_ids) == 2
    assert all(model_turn_ids)
    assert len(set(model_turn_ids)) == 2
    assert len({event.turn_id for event in events}) == 1
    assert events[-1].event == "turn.completed"
    submitted = _FakeSDK.instances[0].queries[0]
    assert submitted["uuid"] == events[0].turn_id
    assert submitted["origin"] == {"kind": "human"}


def test_client_waits_for_chained_background_agents_before_completing() -> None:
    anyio.run(_client_waits_for_chained_background_agents_before_completing)


async def _client_waits_for_chained_background_agents_before_completing() -> None:
    _FakeSDK.batches = [
        [
            _task_started("explore", "Explore the project"),
            AssistantMessage(
                content=[TextBlock(text="Explore agent is running")],
                model="test-model",
            ),
            _result(
                origin={"kind": "human"},
                input_tokens=10,
                output_tokens=5,
            ),
        ],
        [
            _task_completed("explore", "Exploration complete"),
            UserMessage(
                content="Explore agent completed",
                uuid="explore-notification",
                origin={"kind": "task-notification"},
            ),
            AssistantMessage(
                content=[TextBlock(text="Starting Plan agent")],
                model="test-model",
            ),
            _task_started("plan", "Create the final plan"),
            _result(
                origin={"kind": "task-notification"},
                input_tokens=20,
                output_tokens=8,
            ),
        ],
        [
            _task_completed("plan", "Planning complete"),
            UserMessage(
                content="Plan agent completed",
                uuid="plan-notification",
                origin={"kind": "task-notification"},
            ),
            AssistantMessage(
                content=[TextBlock(text="Final implementation plan")],
                model="test-model",
                stop_reason="end_turn",
            ),
            _result(
                origin={"kind": "task-notification"},
                input_tokens=40,
                output_tokens=16,
            ),
        ],
    ]
    client = ClaudeChatClient(ClaudeAgentOptions(model="test-model"))
    events = [event async for event in client.stream("Explore, then plan")]

    result = client.last_result
    assert result is not None
    assert result.content == "Final implementation plan"
    assert result.usage.input_tokens == 70
    assert result.usage.output_tokens == 29
    assert result.usage.subagent_usage is not None
    assert result.usage.subagent_usage.count == 2
    assert result.usage.subagent_usage.total_tokens == 200
    assert [event.event for event in events].count("turn.completed") == 1
    assert [event.event for event in events].count("turn.proxy.completed") == 3
    assert [event.event for event in events].count("user.message") == 1
    assert [event.event for event in events].count("user.proxy.message") == 2
    assert [event.data.get("task_id") for event in events if event.event == "task.completed"] == [
        "explore",
        "plan",
    ]
    assert events[-1].event == "turn.completed"
    assert events[-1].data["content"] == "Final implementation plan"
    assert events[-1].data["usage"]["subagent_usage"] == {
        "count": 2,
        "total_tokens": 200,
    }


def test_client_aggregates_foreground_subagent_usage() -> None:
    anyio.run(_client_aggregates_foreground_subagent_usage)


async def _client_aggregates_foreground_subagent_usage() -> None:
    _FakeSDK.batches = [
        [
            AssistantMessage(
                content=[
                    ToolUseBlock(
                        id="agent-tool",
                        name="Agent",
                        input={"prompt": "Inspect the tests"},
                    )
                ],
                model="test-model",
            ),
            AssistantMessage(
                content=[TextBlock(text="Tests look good")],
                model="subagent-model",
                parent_tool_use_id="agent-tool",
                message_id="subagent-message",
                usage={
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 2,
                    "cache_creation_input_tokens": 3,
                },
            ),
            AssistantMessage(
                content=[TextBlock(text="Final answer")],
                model="test-model",
                stop_reason="end_turn",
            ),
            _result(origin={"kind": "human"}),
        ]
    ]
    client = ClaudeChatClient(ClaudeAgentOptions(model="test-model"))
    events = [event async for event in client.stream("Inspect the tests")]

    result = client.last_result
    assert result is not None
    assert result.usage.subagent_usage is not None
    assert result.usage.subagent_usage.count == 1
    assert result.usage.subagent_usage.total_tokens == 20
    assert events[-1].data["usage"]["subagent_usage"] == {
        "count": 1,
        "total_tokens": 20,
    }


def test_client_emits_permission_events_and_accepts_resolution() -> None:
    anyio.run(_client_emits_permission_events_and_accepts_resolution)


async def _client_emits_permission_events_and_accepts_resolution() -> None:
    _FakeSDK.batches = [["permission", _result(origin={"kind": "human"})]]
    client = ClaudeChatClient()
    events = []

    async for event in client.stream("Write the file"):
        events.append(event)
        if event.event == "permission.requested":
            assert event.parent_tool_use_id is None
            assert event.data["agent_id"] == "agent-1"
            client.resolve_permission(
                event.data["request_id"],
                PermissionResultAllow(updated_input={"file_path": "safe.txt"}),
            )

    sdk = _FakeSDK.instances[0]
    assert isinstance(sdk.permission_result, PermissionResultAllow)
    assert sdk.permission_result.updated_input == {"file_path": "safe.txt"}
    assert [event.event for event in events if event.event.startswith("permission.")] == [
        "permission.requested",
        "permission.resolved",
    ]
    assert client.pending_permission_ids == ()


def test_client_discards_broken_connection_after_stream_error() -> None:
    anyio.run(_client_discards_broken_connection_after_stream_error)


async def _client_discards_broken_connection_after_stream_error() -> None:
    _FakeSDK.batches = [[RuntimeError("transport broke")]]
    client = ClaudeChatClient()
    events = []

    with pytest.raises(RuntimeError, match="transport broke"):
        async for event in client.stream("Hello"):
            events.append(event)

    assert events[-1].event == "turn.failed"
    assert client.connected is False
    assert _FakeSDK.instances[0].disconnected is True


def test_client_forwards_connection_controls() -> None:
    anyio.run(_client_forwards_connection_controls)


async def _client_forwards_connection_controls() -> None:
    client = ClaudeChatClient()

    assert await client.get_server_info() == {"session_id": "session-1"}
    assert await client.get_mcp_status() == {"mcpServers": []}
    assert (await client.get_context_usage())["totalTokens"] == 12
    await client.set_model("next-model")
    await client.set_permission_mode("acceptEdits")
    await client.reconnect_mcp_server("memory")
    await client.toggle_mcp_server("memory", enabled=False)
    await client.stop_task("task-1")
    await client.rewind_files("user-1")
    await client.request_stop()

    sdk = _FakeSDK.instances[0]
    assert sdk.model == "next-model"
    assert sdk.permission_mode == "acceptEdits"
    assert sdk.reconnected_server == "memory"
    assert sdk.toggled_server == ("memory", False)
    assert sdk.stopped_task == "task-1"
    assert sdk.rewound_message == "user-1"


def test_client_supports_empty_command_fallback_content() -> None:
    anyio.run(_client_supports_empty_command_fallback_content)


async def _client_supports_empty_command_fallback_content() -> None:
    _FakeSDK.batches = [[_result(origin={"kind": "human"})]]
    client = ClaudeChatClient()

    result = await client.send(
        "/compact",
        empty_result_content="Context compacted.",
    )

    assert result.content == "Context compacted."
    assert result.to_dict()["content"] == "Context compacted."


def test_client_remembers_stop_requested_before_query_submission() -> None:
    anyio.run(_client_remembers_stop_requested_before_query_submission)


async def _client_remembers_stop_requested_before_query_submission() -> None:
    _FakeSDK.batches = [[_result(origin={"kind": "human"})]]
    client = ClaudeChatClient()

    async for event in client.stream("Start a long task"):
        if event.event == "turn.started":
            await client.request_stop()

    assert _FakeSDK.instances[0].interrupted is True


def test_client_finishes_when_a_subagent_is_stopped() -> None:
    anyio.run(_client_finishes_when_a_subagent_is_stopped)


async def _client_finishes_when_a_subagent_is_stopped() -> None:
    _FakeSDK.batches = [
        [
            _task_started("plan", "Create the final plan"),
            _result(origin={"kind": "human"}),
        ],
        [_task_stopped("plan", "Plan stopped")],
    ]
    client = ClaudeChatClient(ClaudeAgentOptions(model="test-model"))
    events = []

    async for event in client.stream("Start a plan"):
        events.append(event)
        if event.event == "turn.started":
            await client.request_stop()

    assert _FakeSDK.instances[0].interrupted is True
    assert events[-1].event == "turn.completed"
    assert not any(event.event == "turn.failed" for event in events)


def test_client_normalizes_changing_stream_event_uuids() -> None:
    anyio.run(_client_normalizes_changing_stream_event_uuids)


async def _client_normalizes_changing_stream_event_uuids() -> None:
    _FakeSDK.batches = [
        [
            UserMessage(
                content="Say hello",
                uuid="replaced-below",
                origin={"kind": "human"},
            ),
            StreamEvent(
                uuid="frame-1",
                session_id="session-1",
                event={
                    "type": "message_start",
                    "message": {
                        "id": "api-message-1",
                        "model": "test-model",
                        "usage": {},
                    },
                },
            ),
            StreamEvent(
                uuid="frame-2",
                session_id="session-1",
                event={
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            StreamEvent(
                uuid="frame-3",
                session_id="session-1",
                event={
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Hello "},
                },
            ),
            StreamEvent(
                uuid="frame-4",
                session_id="session-1",
                event={
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "world"},
                },
            ),
            StreamEvent(
                uuid="frame-5",
                session_id="session-1",
                event={"type": "content_block_stop", "index": 0},
            ),
            StreamEvent(
                uuid="frame-6",
                session_id="session-1",
                event={"type": "message_stop"},
            ),
            AssistantMessage(
                content=[TextBlock(text="Hello world")],
                model="test-model",
                message_id="api-message-1",
                session_id="session-1",
                uuid="assistant-envelope-1",
                stop_reason="end_turn",
            ),
            _result(origin={"kind": "human"}),
        ]
    ]
    client = ClaudeChatClient(ClaudeAgentOptions(model="test-model"))
    events = []

    async for event in client.stream("Say hello"):
        events.append(event)
        if event.event == "turn.started":
            _FakeSDK.batches[0][0].uuid = event.turn_id

    block_events = [
        event
        for event in events
        if event.event
        in {
            "assistant.reply.started",
            "assistant.reply.delta",
            "assistant.reply.stopped",
        }
    ]
    assert len(block_events) == 4
    assert {event.data["stream_uuid"] for event in block_events} == {"frame-1"}
    assert {event.data["message_id"] for event in block_events} == {"api-message-1"}
    assert {event.data["block_id"] for event in block_events} == {"api-message-1:0"}
    assert [
        event.data["text"]
        for event in block_events
        if event.event == "assistant.reply.delta"
    ] == ["Hello ", "world"]


def _result(
    *,
    origin: dict[str, Any],
    num_turns: int = 1,
    input_tokens: int = 1,
    output_tokens: int = 1,
) -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=10,
        duration_api_ms=8,
        is_error=False,
        num_turns=num_turns,
        session_id="session-1",
        stop_reason="end_turn",
        usage={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
        model_usage={
            "test-model": {
                "inputTokens": input_tokens + 100,
                "outputTokens": output_tokens + 100,
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 0,
                "webSearchRequests": 0,
                "costUSD": 0.01,
                "contextWindow": 200_000,
                "maxOutputTokens": 32_000,
            }
        },
        origin=origin,
    )


def _task_started(task_id: str, description: str) -> TaskStartedMessage:
    return TaskStartedMessage(
        subtype="task_started",
        data={},
        task_id=task_id,
        description=description,
        uuid=f"{task_id}-started",
        session_id="session-1",
        task_type="local_agent",
    )


def _task_completed(task_id: str, summary: str) -> TaskNotificationMessage:
    return TaskNotificationMessage(
        subtype="task_notification",
        data={},
        task_id=task_id,
        status="completed",
        output_file=f"{task_id}.txt",
        summary=summary,
        uuid=f"{task_id}-completed",
        session_id="session-1",
        usage={"total_tokens": 100, "tool_uses": 1, "duration_ms": 1_000},
    )


def _task_stopped(task_id: str, summary: str) -> TaskNotificationMessage:
    return TaskNotificationMessage(
        subtype="task_notification",
        data={},
        task_id=task_id,
        status="stopped",
        output_file=f"{task_id}.txt",
        summary=summary,
        uuid=f"{task_id}-stopped",
        session_id="session-1",
        usage={"total_tokens": 100, "tool_uses": 1, "duration_ms": 1_000},
    )
