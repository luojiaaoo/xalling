import json
from pathlib import Path
from typing import Any, Self
from unittest.mock import patch

import httpx
import pytest

from backend import proxy_claude as proxy_module
from backend.async_runtime import AsyncRuntime
from backend.proxy_claude import (
    _anthropic_responses_response,
    _convert_messages,
    _estimate_tokens,
    _open_upstream_stream,
    _openai_request,
    _resolve_api_mode,
    _responses_request,
    _responses_url,
    _stream_response,
    _stream_responses_response,
    _token_input,
)


def test_responses_mode_and_url_resolution() -> None:
    assert _resolve_api_mode("https://api.openai.com/v1", "auto") == "chat_completions"
    assert _resolve_api_mode("https://api.openai.com/v1/responses", "auto") == "responses"
    assert _resolve_api_mode("https://api.openai.com/v1", "responses") == "responses"
    assert _responses_url("https://api.openai.com/v1") == "https://api.openai.com/v1/responses"
    assert _responses_url("https://api.openai.com/v1/responses/") == "https://api.openai.com/v1/responses"

    with pytest.raises(ValueError, match="api_mode"):
        _resolve_api_mode("https://api.openai.com/v1", "invalid")  # type: ignore[arg-type]


def test_anthropic_request_converts_to_responses_api() -> None:
    body = {
        "model": "ignored-claude-model",
        "system": [{"type": "text", "text": "You are concise."}],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Inspect this:"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "AAAA",
                        },
                    },
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I will inspect it."},
                    {
                        "type": "tool_use",
                        "id": "call_123",
                        "name": "inspect_image",
                        "input": {"detail": "high"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_123",
                        "content": "done",
                    }
                ],
            },
        ],
        "max_tokens": 512,
        "temperature": 0.2,
        "tools": [
            {
                "name": "inspect_image",
                "description": "Inspect an image",
                "input_schema": {
                    "type": "object",
                    "properties": {"detail": {"type": "string"}},
                },
            }
        ],
        "tool_choice": {"type": "tool", "name": "inspect_image"},
        "stream": True,
    }

    result = _responses_request(body, "gpt-5")

    assert result["model"] == "gpt-5"
    assert result["instructions"] == "You are concise."
    assert result["max_output_tokens"] == 512
    assert result["temperature"] == 0.2
    assert result["stream"] is True
    assert result["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Inspect this:"},
                {"type": "input_image", "image_url": "data:image/png;base64,AAAA"},
            ],
        },
        {"role": "assistant", "content": "I will inspect it."},
        {
            "type": "function_call",
            "call_id": "call_123",
            "name": "inspect_image",
            "arguments": '{"detail": "high"}',
        },
        {"type": "function_call_output", "call_id": "call_123", "output": "done"},
    ]
    assert result["tools"] == [
        {
            "type": "function",
            "name": "inspect_image",
            "description": "Inspect an image",
            "parameters": {
                "type": "object",
                "properties": {"detail": {"type": "string"}},
            },
            "strict": False,
        }
    ]
    assert result["tool_choice"] == {"type": "function", "name": "inspect_image"}


def test_responses_result_converts_to_anthropic_message() -> None:
    upstream = {
        "id": "resp_123",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Checking.", "annotations": []}],
            },
            {
                "type": "function_call",
                "id": "fc_123",
                "call_id": "call_123",
                "name": "inspect_image",
                "arguments": '{"detail":"high"}',
            },
        ],
        "usage": {
            "input_tokens": 20,
            "output_tokens": 7,
            "input_tokens_details": {"cached_tokens": 4},
        },
    }

    assert _anthropic_responses_response(upstream, "claude-alias") == {
        "id": "resp_123",
        "type": "message",
        "role": "assistant",
        "model": "claude-alias",
        "content": [
            {"type": "text", "text": "Checking."},
            {
                "type": "tool_use",
                "id": "call_123",
                "name": "inspect_image",
                "input": {"detail": "high"},
            },
        ],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 16,
            "output_tokens": 7,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 4,
        },
    }


class _FakeResponse:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events
        self.closed = False

    def iter_lines(self) -> list[str]:
        return [f"data: {json.dumps(event)}" for event in self.events]

    def close(self) -> None:
        self.closed = True


class _FakeClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _decode_anthropic_events(chunks: list[bytes]) -> list[dict[str, Any]]:
    events = []
    for chunk in chunks:
        data_line = next(line for line in chunk.decode().splitlines() if line.startswith("data: "))
        events.append(json.loads(data_line.removeprefix("data: ")))
    return events


def test_responses_stream_converts_text_tools_and_usage() -> None:
    upstream = _FakeResponse(
        [
            {"type": "response.created", "response": {"id": "resp_123"}},
            {
                "type": "response.output_text.delta",
                "item_id": "msg_123",
                "content_index": 0,
                "delta": "Hello",
            },
            {
                "type": "response.output_item.added",
                "output_index": 1,
                "item": {
                    "type": "function_call",
                    "id": "fc_123",
                    "call_id": "call_123",
                    "name": "get_weather",
                },
            },
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_123",
                "output_index": 1,
                "delta": '{"city":',
            },
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_123",
                "output_index": 1,
                "delta": '"Paris"}',
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_123",
                    "status": "completed",
                    "usage": {"input_tokens": 12, "output_tokens": 5},
                },
            },
        ]
    )
    client = _FakeClient()

    events = _decode_anthropic_events(
        list(_stream_responses_response(client, upstream, "claude-alias", input_tokens=3))
    )

    assert [event["type"] for event in events] == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_start",
        "content_block_delta",
        "content_block_delta",
        "content_block_stop",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    assert events[2]["delta"] == {"type": "text_delta", "text": "Hello"}
    assert events[3]["content_block"] == {
        "type": "tool_use",
        "id": "call_123",
        "name": "get_weather",
        "input": {},
    }
    assert events[4]["delta"]["partial_json"] + events[5]["delta"]["partial_json"] == '{"city":"Paris"}'
    assert events[-2] == {
        "type": "message_delta",
        "delta": {"stop_reason": "tool_use", "stop_sequence": None},
        "usage": {
            "input_tokens": 12,
            "output_tokens": 5,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    }
    assert upstream.closed is True
    assert client.closed is True


@pytest.mark.parametrize("converter", [_stream_response, _stream_responses_response])
def test_stream_ended_without_completion_emits_error(converter: Any) -> None:
    upstream = _FakeResponse([])
    client = _FakeClient()

    events = _decode_anthropic_events(list(converter(client, upstream, "claude-alias", input_tokens=3)))

    assert events[-1]["type"] == "error"
    assert "ended before" in events[-1]["error"]["message"]
    assert all(event["type"] != "message_stop" for event in events)
    assert upstream.closed is True
    assert client.closed is True


def test_chat_stream_forwards_upstream_error_event() -> None:
    upstream = _FakeResponse([{"error": {"message": "quota exceeded"}}])

    events = _decode_anthropic_events(
        list(_stream_response(_FakeClient(), upstream, "claude-alias", input_tokens=3))
    )

    assert events[-1] == {
        "type": "error",
        "error": {"type": "api_error", "message": "quota exceeded"},
    }
    assert all(event["type"] != "message_stop" for event in events)


def test_incomplete_response_does_not_expose_partial_tool_call() -> None:
    result = _anthropic_responses_response(
        {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_123",
                    "name": "write_file",
                    "arguments": '{"path":',
                }
            ],
        },
        "claude-alias",
    )

    assert result["stop_reason"] == "max_tokens"
    assert result["content"] == [{"type": "text", "text": ""}]


def test_completed_response_rejects_malformed_tool_arguments() -> None:
    with pytest.raises(RuntimeError, match="malformed JSON tool arguments"):
        _anthropic_responses_response(
            {
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_123",
                        "name": "write_file",
                        "arguments": '{"path":',
                    }
                ],
            },
            "claude-alias",
        )


def test_tool_result_images_remain_multimodal() -> None:
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_123",
                        "content": [
                            {"type": "text", "text": "Screenshot:"},
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": "AAAA",
                                },
                            },
                        ],
                    }
                ],
            }
        ]
    }

    assert _convert_messages(body)[0]["content"] == [
        {"type": "text", "text": "Screenshot:"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]
    assert _responses_request(body, "gpt-5")["input"][0]["output"] == [
        {"type": "input_text", "text": "Screenshot:"},
        {"type": "input_image", "image_url": "data:image/png;base64,AAAA"},
    ]


@pytest.mark.parametrize("api_mode", ["chat_completions", "responses"])
def test_token_estimate_includes_instructions_and_tools(api_mode: str) -> None:
    body = {
        "system": "System instructions",
        "messages": [{"role": "user", "content": "Hello"}],
        "tools": [
            {
                "name": "lookup",
                "description": "Look something up",
                "input_schema": {"type": "object"},
            }
        ],
    }
    openai_body = (
        _responses_request(body, "gpt-5")
        if api_mode == "responses"
        else _openai_request(body, "gpt-5")
    )
    token_input = _token_input(openai_body, api_mode)

    assert "tools" in token_input
    assert "instructions" in token_input if api_mode == "responses" else "messages" in token_input
    bare_input = openai_body["input"] if api_mode == "responses" else openai_body["messages"]
    assert _estimate_tokens(token_input) > _estimate_tokens(bare_input)


def test_stream_client_is_closed_when_send_fails() -> None:
    class FailingClient:
        instance: "FailingClient | None" = None

        def __init__(self, **_: Any) -> None:
            self.closed = False
            FailingClient.instance = self

        def build_request(self, *_: Any, **__: Any) -> httpx.Request:
            return httpx.Request("POST", "https://example.invalid")

        def send(self, request: httpx.Request, **_: Any) -> httpx.Response:
            raise httpx.ConnectError("simulated failure", request=request)

        def close(self) -> None:
            self.closed = True

    timeout = httpx.Timeout(1.0)
    with (
        patch("backend.proxy_claude.httpx.Client", FailingClient),
        pytest.raises(httpx.ConnectError, match="simulated failure"),
    ):
        _open_upstream_stream("https://example.invalid", {}, {}, timeout)

    assert FailingClient.instance is not None
    assert FailingClient.instance.closed is True


def test_proxy_start_and_stop_are_async(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processes = []

    class FakeProcess:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.alive = False
            self.join_timeouts: list[float] = []
            processes.append(self)

        def start(self) -> None:
            self.alive = True

        def is_alive(self) -> bool:
            return self.alive

        def terminate(self) -> None:
            self.alive = False

        def kill(self) -> None:
            self.alive = False

        def join(self, timeout: float) -> None:
            self.join_timeouts.append(timeout)

    class FakeAsyncClient:
        def __init__(self, **_: Any) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, url: str) -> httpx.Response:
            return httpx.Response(200, request=httpx.Request("GET", url))

    monkeypatch.setattr(proxy_module, "_process", None)
    monkeypatch.setattr(proxy_module, "_proxy_info", None)
    monkeypatch.setattr(proxy_module.multiprocessing, "Process", FakeProcess)
    monkeypatch.setattr(proxy_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(proxy_module, "_free_local_port", lambda: 43123)

    with AsyncRuntime() as runtime:
        info = runtime.call(
            proxy_module.start_proxy,
            "https://api.example.com/v1",
            "secret",
            "gpt-test",
            str(tmp_path / "proxy.log"),
        )
        runtime.call(proxy_module.close_proxy, 0.2)
        runtime.call(proxy_module.stop_proxy)

    assert info.base_url == "http://127.0.0.1:43123"
    assert len(processes) == 1
    assert processes[0].kwargs["daemon"] is True
    assert processes[0].join_timeouts == [0.2, 0]
    assert proxy_module._process is None
