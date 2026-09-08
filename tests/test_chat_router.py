from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage

from backend.config.current import CurrentConfig
from backend.config.setting import Settings
from backend.router.chat import ChatRouter


def configure_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_path = tmp_path / "setting.toml"
    settings_path.write_text(
        '[[model]]\nname = "Claude"\napi_key = "secret"\n'
        'api_url = "https://api.example.com"\n'
        '[[model.models]]\nname = "claude-sonnet"\n',
        encoding="utf-8",
    )
    current_path = tmp_path / "current.toml"
    current_path.write_text(
        '[model]\nsite = "Claude"\nname = "claude-sonnet"\n',
        encoding="utf-8",
    )
    monkeypatch.setitem(Settings.model_config, "toml_file", settings_path)
    monkeypatch.setitem(CurrentConfig.model_config, "toml_file", current_path)


def test_chat_router_uses_claude_agent_sdk_and_returns_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_model(tmp_path, monkeypatch)
    session_id = str(uuid4())
    captured: dict[str, object] = {}

    async def fake_query(
        *, prompt: str, options: ClaudeAgentOptions
    ) -> AsyncIterator[ResultMessage]:
        captured.update(prompt=prompt, options=options)
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id=session_id,
            result="完成了",
        )

    monkeypatch.setattr("backend.router.chat.query", fake_query)

    reply = ChatRouter().send_chat_message(
        "检查项目", str(tmp_path), None, "high"
    )

    assert reply == {"content": "完成了", "session_id": session_id}
    assert captured["prompt"] == "检查项目"
    options = captured["options"]
    assert isinstance(options, ClaudeAgentOptions)
    assert options.cwd == tmp_path.resolve()
    assert options.model == "claude-sonnet"
    assert options.env["ANTHROPIC_BASE_URL"] == "https://api.example.com"
    assert options.env["ANTHROPIC_AUTH_TOKEN"] == "secret"


def test_chat_router_passes_resume_session_to_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_model(tmp_path, monkeypatch)
    session_id = str(uuid4())
    captured: dict[str, object] = {}

    async def fake_query(
        *, prompt: str, options: ClaudeAgentOptions
    ) -> AsyncIterator[ResultMessage]:
        captured["resume"] = options.resume
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id=session_id,
            result=prompt,
        )

    monkeypatch.setattr("backend.router.chat.query", fake_query)

    ChatRouter().send_chat_message("继续", str(tmp_path), session_id, "medium")

    assert captured["resume"] == session_id


@pytest.mark.parametrize("effort", ["", "最高", "ultra"])
def test_chat_router_rejects_invalid_effort(effort: str) -> None:
    with pytest.raises(ValueError, match="推理强度无效"):
        ChatRouter._validate_effort(effort)


def test_chat_router_defaults_to_home_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert ChatRouter._validate_project_path(None) == tmp_path.resolve()
