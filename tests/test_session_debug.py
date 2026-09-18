import json

from backend.claude_chat_client import session_debug


def test_history_debug_log_replaces_previous_snapshot(tmp_path, monkeypatch) -> None:
    path = tmp_path / "history-session.jsonl"
    monkeypatch.setattr(
        session_debug,
        "session_debug_filepath",
        lambda _kind, _session_id: path,
    )

    session_debug.write_history_messages("session", [{"id": "first"}])
    session_debug.write_history_messages(
        "session",
        [{"id": "second"}, {"id": "third"}],
    )

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert records == [{"id": "second"}, {"id": "third"}]
