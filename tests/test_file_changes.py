"""Net turn diffs, incomplete SDK results, and live/history normalization."""

from claude_agent_sdk import AssistantMessage, SessionMessage, ToolResultBlock, ToolUseBlock, UserMessage

from backend.claude_chat_client.file_changes import TurnFileChanges
from backend.claude_chat_client.history import assemble_session_messages
from backend.claude_chat_client.message_adapter import _EventFactory, _MessageAdapter
from backend.claude_chat_client.models import render_event


def write(tracker, tool_id, before, after, *, create=False, restorable=True):
    return tracker.apply("Write", {"file_path": "/workspace/file.txt", "content": after},
                         {"filePath": "/workspace/file.txt", "originalFile": before,
                          "content": after, "type": "create" if create else "update"},
                         tool_id, restorable=restorable)


def test_multiple_edits_are_net_changes_and_reverted_files_disappear():
    tracker = TurnFileChanges()
    write(tracker, "first", "original\nkeep\n", "intermediate\nkeep\n")
    write(tracker, "second", "intermediate\nkeep\n", "final\nkeep\n")
    change, = tracker.snapshot()
    assert (change["additions"], change["deletions"]) == (1, 1)
    assert "-original\n+final\n" in change["patch"]
    assert "intermediate" not in change["patch"]
    write(tracker, "revert", "final\nkeep\n", "original\nkeep\n")
    assert tracker.snapshot() == []
    assert not write(tracker, "revert", "original\nkeep\n", "other\n")


def test_creation_empty_files_missing_newline_and_diff_prefix_content():
    tracker = TurnFileChanges()
    write(tracker, "create", None, "++literal", create=True)
    change, = tracker.snapshot()
    assert change["status"] == "added"
    assert (change["additions"], change["deletions"]) == (1, 0)
    assert "+++literal\n\\ No newline at end of file\n" in change["patch"]
    assert "--- /dev/null" in change["patch"]
    empty = TurnFileChanges()
    write(empty, "empty", None, "", create=True)
    assert empty.snapshot()[0]["additions"] == 0


def test_edit_uses_accepted_result_and_replace_all():
    tracker = TurnFileChanges()
    tracker.apply("Edit", {"file_path": "file", "old_string": "old", "new_string": "proposed"},
                  {"originalFile": "old\nold\n", "oldString": "old", "newString": "accepted",
                   "replaceAll": True, "userModified": True}, "edit", restorable=True)
    change, = tracker.snapshot()
    assert (change["additions"], change["deletions"]) == (2, 2)
    assert "accepted" in change["patch"] and "proposed" not in change["patch"]


def test_unknown_and_discontinuous_contents_do_not_invent_net_statistics():
    tracker = TurnFileChanges()
    patch = [{"oldStart": 8, "oldLines": 1, "newStart": 8, "newLines": 1, "lines": ["-old", "+new"]}]
    tracker.apply("Edit", {"file_path": "file", "old_string": "old", "new_string": "new"},
                  {"structuredPatch": patch}, "partial", restorable=True)
    change, = tracker.snapshot()
    assert change["partial"] and change["additions"] is None and change["deletions"] is None
    assert "@@ -8,1 +8,1 @@" in change["patch"]
    other = TurnFileChanges()
    write(other, "one", "original\n", "ours\n")
    write(other, "two", "someone else's edit\n", "final\n")
    change, = other.snapshot()
    assert change["partial"] and change["additions"] is None


def test_limits_bound_previews_and_do_not_treat_large_missing_original_as_new():
    tracker = TurnFileChanges()
    write(tracker, "large", "a" * 210_000, "b" * 210_000)
    change, = tracker.snapshot()
    assert change["truncated"] and len(change["patch"]) == 200_000
    unknown = TurnFileChanges()
    write(unknown, "unknown", None, "existing file update")
    change, = unknown.snapshot()
    assert change["status"] == "modified" and change["partial"]


def test_subagent_edits_are_visible_and_marked_outside_main_checkpoint_scope():
    tracker = TurnFileChanges()
    write(tracker, "main", "before\n", "main\n")
    write(tracker, "child", "main\n", "child\n", restorable=False)
    assert tracker.snapshot()[0]["restorable"] is False
    assert not tracker.apply("Read", {"file_path": "read"}, {}, "read", restorable=True)
    assert not tracker.apply("Bash", {"command": "echo test"}, {}, "bash", restorable=True)


def test_live_and_public_history_share_file_change_projection_and_skip_failures():
    tool_input = {"file_path": "/workspace/file.txt", "content": "new\n"}
    result = {"filePath": "/workspace/file.txt", "type": "update", "content": "new\n", "originalFile": "old\n"}
    adapter = _MessageAdapter(_EventFactory("turn", session_id="session"), {})
    adapter.adapt(AssistantMessage(content=[ToolUseBlock(id="write", name="Write", input=tool_input)], model="model"))
    live = adapter.adapt(UserMessage(content=[ToolResultBlock(tool_use_id="write", content="done")], tool_use_result=result))
    history = assemble_session_messages([
        SessionMessage("user", "turn", "session", {"content": "edit"}),
        SessionMessage("assistant", "assistant", "session", {"model": "model", "content": [
            {"type": "tool_use", "id": "write", "name": "Write", "input": tool_input}]}),
        SessionMessage("user", "result", "session", {"content": [
            {"type": "tool_result", "tool_use_id": "write", "content": "done"}], "tool_use_result": result}),
    ])
    live_changes = next(event for event in live if event.event == "files.changed")
    history_changes = next(event for event in history if event.event == "files.changed")
    assert render_event(live_changes)["data"] == render_event(history_changes)["data"]
    assert live_changes.parent_tool_use_id is None
    adapter.adapt(AssistantMessage(content=[ToolUseBlock(id="failed", name="Write", input=tool_input)], model="model"))
    failed = adapter.adapt(UserMessage(content=[ToolResultBlock(tool_use_id="failed", content="denied", is_error=True)]))
    assert not any(event.event == "files.changed" for event in failed)
