"""Exercise SDK normalization, public history APIs and the actual UI reducer."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, SessionMessage, StreamEvent, TextBlock, ThinkingBlock

from backend.claude_chat_client.history import ClaudeChatHistory, assemble_session_messages
from backend.claude_chat_client.message_adapter import _EventFactory, _MessageAdapter
from backend.claude_chat_client.models import ChatEvent, render_event


def render_in_ui(*streams):
    root = Path(__file__).resolve().parents[1]
    node = shutil.which("node")
    if node is None or not (root / "frontend/node_modules/typescript").is_dir():
        pytest.skip("UI integration requires Node and installed frontend dependencies")
    command = [node, str(root / "frontend/tests/helpers/chat-replay.mjs")]
    result = subprocess.run(
        command, input=json.dumps(streams), encoding="utf-8", capture_output=True, check=True, timeout=30
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("texts", [["hello"], ["hello", "hello"]])
def test_split_sdk_packets_live_and_history_have_one_copy_per_block(texts):
    factory = _EventFactory("user", session_id="session")
    adapter = _MessageAdapter(factory, {})
    live = [factory.make("turn.started"), factory.make("user.message", {"content": "hello"})]

    def consume(message):
        live.extend(adapter.adapt(message))

    def stream(raw):
        consume(StreamEvent(uuid="frame", session_id="session", event=raw))

    stream({"type": "message_start", "message": {"id": "model"}})
    blocks = [ThinkingBlock(thinking="plan", signature="s"), *(TextBlock(text=text) for text in texts)]
    for index, block in enumerate(blocks):
        thinking = isinstance(block, ThinkingBlock)
        content = block.thinking if thinking else block.text
        stream(
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {"type": "thinking" if thinking else "text"},
            }
        )
        stream(
            {
                "type": "content_block_delta",
                "index": index,
                "delta": {
                    "type": "thinking_delta" if thinking else "text_delta",
                    "thinking" if thinking else "text": content,
                },
            }
        )
        stream({"type": "content_block_stop", "index": index})
        packet = AssistantMessage(
            content=[block], model="claude", message_id="model", uuid=f"packet-{index}", session_id="session"
        )
        consume(packet)
        consume(packet)
    assert adapter.main_text == texts
    live.append(factory.make("turn.completed", {"content": "\n\n".join(texts)}))
    history = assemble_session_messages(
        [
            SessionMessage("user", "user", "session", {"content": "hello"}),
            *(
                SessionMessage(
                    "assistant",
                    f"packet-{index}",
                    "session",
                    {
                        "id": "model",
                        "model": "claude",
                        "content": [
                            {"type": "thinking", "thinking": "plan", "signature": "s"}
                            if index == 0
                            else {"type": "text", "text": texts[index - 1]},
                        ],
                    },
                )
                for index in range(len(blocks))
            ),
        ]
    )
    rendered = render_in_ui([render_event(event) for event in live], [render_event(event) for event in history])
    for messages in rendered:
        assert [message["role"] for message in messages] == ["user", "ai"]
        assert messages[-1]["content"] == "\n\n".join(texts)
        assert [item["content"] for item in messages[-1]["trace"]] == ["plan", *texts]
        assert len(messages[-1]["finalOutputKeys"]) == len(texts)


def test_history_uses_sdk_messages_without_reading_storage(monkeypatch):
    session = "11111111-1111-1111-1111-111111111111"
    messages = [
        SessionMessage("user", "user", session, {"content": "hello"}),
        SessionMessage(
            "assistant",
            "assistant",
            session,
            {
                "id": "model",
                "model": "claude",
                "content": [
                    {"type": "text", "text": "done"},
                    {"type": "tool_use", "id": "read", "name": "Read", "input": {"file_path": "one.py"}},
                ],
            },
        ),
        SessionMessage(
            "user",
            "result",
            session,
            {"content": [{"type": "tool_result", "tool_use_id": "read", "content": "source"}]},
        ),
    ]

    def forbid_storage_access(*_args, **_kwargs):
        pytest.fail("History must access SDK storage through public SDK APIs only")

    with monkeypatch.context() as patch:
        patch.setattr("backend.claude_chat_client.history.get_session_messages", lambda _session: messages)
        patch.setattr("backend.claude_chat_client.history.list_subagents", lambda _session: [])
        # The app's own diagnostic log is independent of SDK storage.
        patch.setattr("backend.claude_chat_client.history.write_history_messages", lambda *_args: None)
        patch.setattr(Path, "glob", forbid_storage_access)
        patch.setattr(Path, "open", forbid_storage_access)
        patch.setattr(Path, "read_text", forbid_storage_access)
        events = ClaudeChatHistory().get_session_events(session)

    completed = next(event for event in events if event.event == "tool.completed")
    assert completed.data["content"] == "source"
    assert events[-1].data["content"] == "done"
    assert events[-1].data["duration_ms"] == 0
    rendered = render_in_ui([render_event(event) for event in events])[0]
    assert rendered[-1]["content"] == "done"


def test_render_contract_carries_tool_outputs_and_background_ownership():
    tool = render_event(
        ChatEvent(
            "1",
            "tool.completed",
            "turn",
            data={
                "tool_id": "read",
                "content": [{"type": "text", "text": "source"}],
            },
        )
    )
    assert tool["data"]["output"] == [{"type": "text", "text": "source"}]
    task = render_event(
        ChatEvent(
            "2",
            "task.started",
            "turn",
            data={
                "task_id": "task",
                "tool_use_id": "agent",
            },
        )
    )
    assert task["data"]["tool_use_id"] == "agent"
