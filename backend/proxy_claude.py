"""A small Anthropic Messages API -> OpenAI API proxy.

The public API of this module is intentionally tiny::

    base_url, api_key, model = await start_proxy(
        openai_base_url="https://api.openai.com/v1",
        openai_api_key="sk-...",
        model_name="gpt-4.1",
        log_file_path="proxy.log",
        api_mode="responses",
    )

    # Point Claude Code at ``base_url`` and ``api_key``.
    await stop_proxy()

Only one proxy process is supported at a time.  The key returned by
``start_proxy`` is a short-lived local proxy key; the upstream OpenAI key is
kept inside the child process and is never returned or written to the log.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import multiprocessing
import secrets
import socket
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any, Literal, NamedTuple
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

import bottle
import httpx
from loguru import logger


class ClaudeProxyInfo(NamedTuple):
    """Connection information returned by :func:`start_proxy`."""

    base_url: str
    api_key: str
    model_name: str


_process: multiprocessing.Process | None = None
_proxy_info: ClaudeProxyInfo | None = None
_lifecycle_lock = threading.Lock()

OpenAIApiMode = Literal["auto", "chat_completions", "responses"]


class _UpstreamProtocolError(RuntimeError):
    """Raised when an upstream response cannot be represented safely."""


def _chat_completions_url(base_url: str) -> str:
    url = base_url.strip().rstrip("/")
    if not url:
        raise ValueError("openai_base_url cannot be empty")
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions"


def _responses_url(base_url: str) -> str:
    url = base_url.strip().rstrip("/")
    if not url:
        raise ValueError("openai_base_url cannot be empty")
    if url.endswith("/responses"):
        return url
    return f"{url}/responses"


def _resolve_api_mode(base_url: str, api_mode: OpenAIApiMode) -> Literal["chat_completions", "responses"]:
    if api_mode not in {"auto", "chat_completions", "responses"}:
        raise ValueError("api_mode must be 'auto', 'chat_completions', or 'responses'")
    if api_mode == "auto":
        return "responses" if base_url.strip().rstrip("/").endswith("/responses") else "chat_completions"
    return api_mode


def _text_from_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict) and "text" in value:
        return str(value["text"])
    return json.dumps(value, ensure_ascii=False)


def _system_text(system: Any) -> str:
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "\n\n".join(
            str(block.get("text", "")) for block in system if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _openai_content(blocks: list[dict[str, Any]]) -> Any:
    converted: list[dict[str, Any]] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type == "text":
            converted.append({"type": "text", "text": str(block.get("text", ""))})
        elif block_type == "image":
            source = block.get("source") or {}
            if source.get("type") == "base64":
                media_type = source.get("media_type", "image/png")
                image_url = f"data:{media_type};base64,{source.get('data', '')}"
            else:
                image_url = source.get("url", "")
            if image_url:
                converted.append({"type": "image_url", "image_url": {"url": image_url}})

    if not converted:
        return ""
    if all(item["type"] == "text" for item in converted):
        return "".join(item["text"] for item in converted)
    return converted


def _content_blocks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [
            item if isinstance(item, dict) else {"type": "text", "text": str(item)}
            for item in value
        ]
    if isinstance(value, str):
        return [{"type": "text", "text": value}]
    return [{"type": "text", "text": _text_from_content(value)}]


def _prepend_error(content: Any, text_type: str) -> Any:
    if isinstance(content, str):
        return f"Error: {content}"
    if isinstance(content, list):
        return [{"type": text_type, "text": "Error: "}, *content]
    return "Error:"


def _convert_messages(body: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    system = _system_text(body.get("system"))
    if system:
        messages.append({"role": "system", "content": system})

    for source_message in body.get("messages") or []:
        role = source_message.get("role")
        content = source_message.get("content", "")
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            messages.append({"role": role, "content": _text_from_content(content)})
            continue

        if role == "assistant":
            normal_blocks = [
                block for block in content if isinstance(block, dict) and block.get("type") in {"text", "image"}
            ]
            tool_calls = []
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                tool_calls.append(
                    {
                        "id": block.get("id") or f"call_{uuid.uuid4().hex}",
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                        },
                    }
                )
            converted_message: dict[str, Any] = {
                "role": "assistant",
                "content": _openai_content(normal_blocks) or None,
            }
            if tool_calls:
                converted_message["tool_calls"] = tool_calls
            messages.append(converted_message)
            continue

        # Anthropic places tool results among user content blocks. OpenAI needs
        # each result as a standalone role=tool message, so preserve their order.
        pending_blocks: list[dict[str, Any]] = []

        def flush_pending(blocks: list[dict[str, Any]]) -> None:
            if blocks:
                messages.append({"role": "user", "content": _openai_content(blocks)})
                blocks.clear()

        for block in content:
            if not isinstance(block, dict):
                pending_blocks.append({"type": "text", "text": str(block)})
            elif block.get("type") == "tool_result":
                flush_pending(pending_blocks)
                result = _openai_content(_content_blocks(block.get("content")))
                if block.get("is_error"):
                    result = _prepend_error(result, "text")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": result,
                    }
                )
            elif block.get("type") in {"text", "image"}:
                pending_blocks.append(block)
        flush_pending(pending_blocks)

    return messages


def _convert_tools(tools: Any) -> list[dict[str, Any]]:
    result = []
    for tool in tools or []:
        if not isinstance(tool, dict) or not tool.get("name"):
            continue
        result.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema") or {"type": "object"},
                },
            }
        )
    return result


def _convert_tool_choice(choice: Any) -> Any:
    if not isinstance(choice, dict):
        return None
    choice_type = choice.get("type")
    if choice_type == "auto":
        return "auto"
    if choice_type == "any":
        return "required"
    if choice_type == "none":
        return "none"
    if choice_type == "tool" and choice.get("name"):
        return {"type": "function", "function": {"name": choice["name"]}}
    return None


def _openai_request(body: dict[str, Any], model_name: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "model": model_name,
        "messages": _convert_messages(body),
        "stream": bool(body.get("stream", False)),
    }
    if body.get("max_tokens") is not None:
        result["max_tokens"] = int(body["max_tokens"])
    for source, target in (
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("stop_sequences", "stop"),
    ):
        if body.get(source) is not None:
            result[target] = body[source]

    tools = _convert_tools(body.get("tools"))
    if tools:
        result["tools"] = tools
        tool_choice = _convert_tool_choice(body.get("tool_choice"))
        if tool_choice is not None:
            result["tool_choice"] = tool_choice
    return result


def _responses_content(blocks: list[dict[str, Any]]) -> Any:
    converted: list[dict[str, Any]] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type == "text":
            converted.append({"type": "input_text", "text": str(block.get("text", ""))})
        elif block_type == "image":
            source = block.get("source") or {}
            if source.get("type") == "base64":
                media_type = source.get("media_type", "image/png")
                image_url = f"data:{media_type};base64,{source.get('data', '')}"
            else:
                image_url = source.get("url", "")
            if image_url:
                converted.append({"type": "input_image", "image_url": image_url})

    if not converted:
        return ""
    if all(item["type"] == "input_text" for item in converted):
        return "".join(item["text"] for item in converted)
    return converted


def _responses_input(body: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for source_message in body.get("messages") or []:
        role = source_message.get("role")
        content = source_message.get("content", "")
        if isinstance(content, str):
            items.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            items.append({"role": role, "content": _text_from_content(content)})
            continue

        pending_blocks: list[dict[str, Any]] = []

        def flush_pending(blocks: list[dict[str, Any]], message_role: Any) -> None:
            if blocks:
                items.append({"role": message_role, "content": _responses_content(blocks)})
                blocks.clear()

        for block in content:
            if not isinstance(block, dict):
                pending_blocks.append({"type": "text", "text": str(block)})
                continue
            block_type = block.get("type")
            if role == "assistant" and block_type == "tool_use":
                flush_pending(pending_blocks, role)
                items.append(
                    {
                        "type": "function_call",
                        "call_id": block.get("id") or f"call_{uuid.uuid4().hex}",
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                    }
                )
            elif block_type == "tool_result":
                flush_pending(pending_blocks, role)
                result = _responses_content(_content_blocks(block.get("content")))
                if block.get("is_error"):
                    result = _prepend_error(result, "input_text")
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": block.get("tool_use_id", ""),
                        "output": result,
                    }
                )
            elif block_type in {"text", "image"}:
                pending_blocks.append(block)
        flush_pending(pending_blocks, role)
    return items


def _responses_tools(tools: Any) -> list[dict[str, Any]]:
    result = []
    for tool in tools or []:
        if not isinstance(tool, dict) or not tool.get("name"):
            continue
        result.append(
            {
                "type": "function",
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema") or {"type": "object"},
                "strict": False,
            }
        )
    return result


def _responses_tool_choice(choice: Any) -> Any:
    converted = _convert_tool_choice(choice)
    if not isinstance(converted, dict):
        return converted
    return {"type": "function", "name": converted["function"]["name"]}


def _responses_request(body: dict[str, Any], model_name: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "model": model_name,
        "input": _responses_input(body),
        "stream": bool(body.get("stream", False)),
    }
    instructions = _system_text(body.get("system"))
    if instructions:
        result["instructions"] = instructions
    if body.get("max_tokens") is not None:
        result["max_output_tokens"] = int(body["max_tokens"])
    for name in ("temperature", "top_p"):
        if body.get(name) is not None:
            result[name] = body[name]

    tools = _responses_tools(body.get("tools"))
    if tools:
        result["tools"] = tools
        tool_choice = _responses_tool_choice(body.get("tool_choice"))
        if tool_choice is not None:
            result["tool_choice"] = tool_choice
    return result


def _estimate_tokens(value: Any) -> int:
    # This endpoint is primarily used by Claude Code for context management.
    # Without imposing a tokenizer dependency, a conservative UTF-8 estimate
    # is more useful than returning a constant zero.
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return max(1, (len(encoded) + 3) // 4)


def _token_input(openai_body: dict[str, Any], api_mode: str) -> dict[str, Any]:
    names = ("input", "instructions", "tools", "tool_choice") if api_mode == "responses" else (
        "messages",
        "tools",
        "tool_choice",
    )
    return {name: openai_body[name] for name in names if name in openai_body}


def _anthropic_usage(
    input_tokens: Any,
    output_tokens: Any,
    cached_tokens: Any = 0,
) -> dict[str, int]:
    total_input = max(0, int(input_tokens or 0))
    cache_read = max(0, min(total_input, int(cached_tokens or 0)))
    return {
        "input_tokens": total_input - cache_read,
        "output_tokens": max(0, int(output_tokens or 0)),
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": cache_read,
    }


def _stop_reason(finish_reason: str | None, has_tools: bool = False) -> str:
    if finish_reason == "length":
        return "max_tokens"
    if finish_reason in {"tool_calls", "function_call"} or has_tools:
        return "tool_use"
    return "end_turn"


def _arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        if not isinstance(parsed, dict):
            raise _UpstreamProtocolError("Upstream tool arguments must decode to a JSON object")
        return parsed
    except (TypeError, json.JSONDecodeError):
        raise _UpstreamProtocolError("Upstream returned malformed JSON tool arguments") from None


def _anthropic_response(upstream: dict[str, Any], requested_model: str) -> dict[str, Any]:
    choices = upstream.get("choices") or []
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}
    content: list[dict[str, Any]] = []
    text = _text_from_content(message.get("content"))
    if text:
        content.append({"type": "text", "text": text})

    truncated = choice.get("finish_reason") == "length"
    for call in [] if truncated else message.get("tool_calls") or []:
        function = call.get("function") or {}
        content.append(
            {
                "type": "tool_use",
                "id": call.get("id") or f"toolu_{uuid.uuid4().hex[:24]}",
                "name": function.get("name", ""),
                "input": _arguments(function.get("arguments")),
            }
        )
    if not content:
        content.append({"type": "text", "text": ""})

    usage = upstream.get("usage") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    has_tools = any(block["type"] == "tool_use" for block in content)
    return {
        "id": upstream.get("id") or f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "model": requested_model,
        "content": content,
        "stop_reason": _stop_reason(choice.get("finish_reason"), has_tools),
        "stop_sequence": None,
        "usage": _anthropic_usage(
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            prompt_details.get("cached_tokens", 0),
        ),
    }


def _responses_stop_reason(upstream: dict[str, Any], has_tools: bool) -> str:
    incomplete = upstream.get("incomplete_details") or {}
    if upstream.get("status") == "incomplete" and incomplete.get("reason") == "max_output_tokens":
        return "max_tokens"
    if has_tools:
        return "tool_use"
    return "end_turn"


def _anthropic_responses_response(upstream: dict[str, Any], requested_model: str) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    truncated = _responses_stop_reason(upstream, has_tools=False) == "max_tokens"
    for item in upstream.get("output") or []:
        item_type = item.get("type")
        if item_type == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text":
                    content.append({"type": "text", "text": str(part.get("text", ""))})
                elif part.get("type") == "refusal":
                    content.append({"type": "text", "text": str(part.get("refusal", ""))})
        elif item_type == "function_call" and not truncated:
            content.append(
                {
                    "type": "tool_use",
                    "id": item.get("call_id") or item.get("id") or f"toolu_{uuid.uuid4().hex[:24]}",
                    "name": item.get("name", ""),
                    "input": _arguments(item.get("arguments")),
                }
            )
    if not content:
        content.append({"type": "text", "text": ""})

    usage = upstream.get("usage") or {}
    has_tools = any(block["type"] == "tool_use" for block in content)
    input_details = usage.get("input_tokens_details") or {}
    return {
        "id": upstream.get("id") or f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "model": requested_model,
        "content": content,
        "stop_reason": _responses_stop_reason(upstream, has_tools),
        "stop_sequence": None,
        "usage": _anthropic_usage(
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
            input_details.get("cached_tokens", 0),
        ),
    }


def _event(event_type: str, data: dict[str, Any]) -> bytes:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_type}\ndata: {payload}\n\n".encode()


def _stream_response(
    client: httpx.Client,
    upstream: httpx.Response,
    requested_model: str,
    input_tokens: int,
) -> Iterator[bytes]:
    message_id = f"msg_{uuid.uuid4().hex}"
    started_blocks: dict[str, int] = {}
    open_blocks: list[int] = []
    next_block_index = 0
    finish_reason: str | None = None
    output_tokens = 0
    upstream_usage: dict[str, Any] = {}
    has_tools = False
    stream_finished = False

    try:
        yield _event(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": message_id,
                    "type": "message",
                    "role": "assistant",
                    "model": requested_model,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": input_tokens, "output_tokens": 0},
                },
            },
        )

        for line in upstream.iter_lines():
            if not line or line.startswith(":") or not line.startswith("data:"):
                continue
            raw_data = line[5:].strip()
            if raw_data == "[DONE]":
                stream_finished = True
                break
            try:
                chunk = json.loads(raw_data)
            except json.JSONDecodeError:
                logger.warning("Ignored malformed upstream SSE line")
                continue

            if chunk.get("id"):
                message_id = chunk["id"]
            if chunk.get("error"):
                error = chunk["error"]
                message = error.get("message") if isinstance(error, dict) else str(error)
                raise RuntimeError(message or "OpenAI Chat Completions stream failed")
            if chunk.get("usage"):
                upstream_usage = chunk["usage"]
            choices = chunk.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            finish_reason = choice.get("finish_reason") or finish_reason
            if choice.get("finish_reason") is not None:
                stream_finished = True
            delta = choice.get("delta") or {}

            text = _text_from_content(delta.get("content"))
            if text:
                key = "text"
                if key not in started_blocks:
                    started_blocks[key] = next_block_index
                    open_blocks.append(next_block_index)
                    yield _event(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": next_block_index,
                            "content_block": {"type": "text", "text": ""},
                        },
                    )
                    next_block_index += 1
                output_tokens += max(1, len(text.encode("utf-8")) // 4)
                yield _event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": started_blocks[key],
                        "delta": {"type": "text_delta", "text": text},
                    },
                )

            for position, call in enumerate(delta.get("tool_calls") or []):
                has_tools = True
                call_key = f"tool:{call.get('index', position)}"
                function = call.get("function") or {}
                if call_key not in started_blocks:
                    block_index = next_block_index
                    next_block_index += 1
                    started_blocks[call_key] = block_index
                    open_blocks.append(block_index)
                    yield _event(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": block_index,
                            "content_block": {
                                "type": "tool_use",
                                "id": call.get("id") or f"toolu_{uuid.uuid4().hex[:24]}",
                                "name": function.get("name", ""),
                                "input": {},
                            },
                        },
                    )
                arguments = function.get("arguments")
                if arguments:
                    yield _event(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": started_blocks[call_key],
                            "delta": {
                                "type": "input_json_delta",
                                "partial_json": arguments,
                            },
                        },
                    )

        if not stream_finished:
            raise RuntimeError("OpenAI Chat Completions stream ended before its completion event")

        # An empty text block is valid and avoids surprising clients when an
        # OpenAI-compatible backend returns no content.
        if not started_blocks:
            started_blocks["text"] = next_block_index
            open_blocks.append(next_block_index)
            yield _event(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": next_block_index,
                    "content_block": {"type": "text", "text": ""},
                },
            )

        for block_index in open_blocks:
            yield _event(
                "content_block_stop",
                {"type": "content_block_stop", "index": block_index},
            )

        prompt_details = upstream_usage.get("prompt_tokens_details") or {}
        anthropic_usage = _anthropic_usage(
            upstream_usage.get("prompt_tokens", input_tokens),
            upstream_usage.get("completion_tokens", output_tokens),
            prompt_details.get("cached_tokens", 0),
        )
        yield _event(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {
                    "stop_reason": _stop_reason(finish_reason, has_tools),
                    "stop_sequence": None,
                },
                "usage": anthropic_usage,
            },
        )
        yield _event("message_stop", {"type": "message_stop"})
    except Exception as exc:  # noqa: BLE001 - stream errors must become Anthropic SSE errors
        logger.exception("Streaming conversion failed: {}", exc)
        yield _event(
            "error",
            {
                "type": "error",
                "error": {"type": "api_error", "message": str(exc)},
            },
        )
    finally:
        upstream.close()
        client.close()


def _stream_responses_response(
    client: httpx.Client,
    upstream: httpx.Response,
    requested_model: str,
    input_tokens: int,
) -> Iterator[bytes]:
    message_id = f"msg_{uuid.uuid4().hex}"
    started_blocks: dict[str, int] = {}
    open_blocks: list[int] = []
    tool_items: dict[str, dict[str, Any]] = {}
    blocks_with_deltas: set[str] = set()
    next_block_index = 0
    output_tokens = 0
    completed_response: dict[str, Any] = {}
    has_tools = False
    stream_finished = False

    def start_text_block(key: str) -> Iterator[bytes]:
        nonlocal next_block_index
        if key in started_blocks:
            return
        started_blocks[key] = next_block_index
        open_blocks.append(next_block_index)
        next_block_index += 1
        yield _event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": started_blocks[key],
                "content_block": {"type": "text", "text": ""},
            },
        )

    def start_tool_block(key: str, item: dict[str, Any]) -> Iterator[bytes]:
        nonlocal has_tools, next_block_index
        has_tools = True
        tool_items[key] = {**tool_items.get(key, {}), **item}
        if key in started_blocks:
            return
        started_blocks[key] = next_block_index
        open_blocks.append(next_block_index)
        next_block_index += 1
        yield _event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": started_blocks[key],
                "content_block": {
                    "type": "tool_use",
                    "id": item.get("call_id") or item.get("id") or f"toolu_{uuid.uuid4().hex[:24]}",
                    "name": item.get("name", ""),
                    "input": {},
                },
            },
        )

    try:
        yield _event(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": message_id,
                    "type": "message",
                    "role": "assistant",
                    "model": requested_model,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": input_tokens, "output_tokens": 0},
                },
            },
        )

        for line in upstream.iter_lines():
            if not line or line.startswith(":") or not line.startswith("data:"):
                continue
            raw_data = line[5:].strip()
            if raw_data == "[DONE]":
                break
            try:
                event = json.loads(raw_data)
            except json.JSONDecodeError:
                logger.warning("Ignored malformed upstream Responses SSE line")
                continue

            event_type = event.get("type")
            response = event.get("response") or {}
            if response.get("id"):
                message_id = response["id"]

            if event_type == "response.output_item.added":
                item = event.get("item") or {}
                if item.get("type") == "function_call":
                    key = str(item.get("id") or event.get("output_index", len(tool_items)))
                    yield from start_tool_block(key, item)
                continue

            if event_type in {"response.output_text.delta", "response.refusal.delta"}:
                key = f"text:{event.get('item_id', 'response')}:{event.get('content_index', 0)}"
                yield from start_text_block(key)
                text = str(event.get("delta", ""))
                if text:
                    blocks_with_deltas.add(key)
                    output_tokens += max(1, len(text.encode("utf-8")) // 4)
                    yield _event(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": started_blocks[key],
                            "delta": {"type": "text_delta", "text": text},
                        },
                    )
                continue

            if event_type == "response.function_call_arguments.delta":
                key = str(event.get("item_id") or event.get("output_index", len(tool_items)))
                yield from start_tool_block(key, tool_items.get(key, {}))
                arguments = str(event.get("delta", ""))
                if arguments:
                    blocks_with_deltas.add(key)
                    yield _event(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": started_blocks[key],
                            "delta": {"type": "input_json_delta", "partial_json": arguments},
                        },
                    )
                continue

            if event_type == "response.output_item.done":
                item = event.get("item") or {}
                item_id = str(item.get("id") or event.get("output_index", "response"))
                if item.get("type") == "function_call":
                    yield from start_tool_block(item_id, item)
                    arguments = str(item.get("arguments", ""))
                    if arguments and item_id not in blocks_with_deltas:
                        yield _event(
                            "content_block_delta",
                            {
                                "type": "content_block_delta",
                                "index": started_blocks[item_id],
                                "delta": {"type": "input_json_delta", "partial_json": arguments},
                            },
                        )
                elif item.get("type") == "message":
                    for content_index, part in enumerate(item.get("content") or []):
                        if part.get("type") not in {"output_text", "refusal"}:
                            continue
                        key = f"text:{item_id}:{content_index}"
                        yield from start_text_block(key)
                        if key in blocks_with_deltas:
                            continue
                        text = str(part.get("text") or part.get("refusal") or "")
                        if text:
                            output_tokens += max(1, len(text.encode("utf-8")) // 4)
                            yield _event(
                                "content_block_delta",
                                {
                                    "type": "content_block_delta",
                                    "index": started_blocks[key],
                                    "delta": {"type": "text_delta", "text": text},
                                },
                            )
                continue

            if event_type in {"response.completed", "response.incomplete"}:
                completed_response = response
                stream_finished = True
                continue
            if event_type in {"error", "response.failed"}:
                error = event.get("error") or response.get("error") or {}
                raise RuntimeError(error.get("message") or "OpenAI Responses stream failed")

        if not stream_finished:
            raise RuntimeError("OpenAI Responses stream ended before its completion event")

        if not started_blocks:
            yield from start_text_block("text")

        for block_index in open_blocks:
            yield _event(
                "content_block_stop",
                {"type": "content_block_stop", "index": block_index},
            )

        usage = completed_response.get("usage") or {}
        input_details = usage.get("input_tokens_details") or {}
        anthropic_usage = _anthropic_usage(
            usage.get("input_tokens", input_tokens),
            usage.get("output_tokens", output_tokens),
            input_details.get("cached_tokens", 0),
        )
        yield _event(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {
                    "stop_reason": _responses_stop_reason(completed_response, has_tools),
                    "stop_sequence": None,
                },
                "usage": anthropic_usage,
            },
        )
        yield _event("message_stop", {"type": "message_stop"})
    except Exception as exc:  # noqa: BLE001 - stream errors must become Anthropic SSE errors
        logger.exception("Responses streaming conversion failed: {}", exc)
        yield _event(
            "error",
            {
                "type": "error",
                "error": {"type": "api_error", "message": str(exc)},
            },
        )
    finally:
        upstream.close()
        client.close()


def _error_response(status: int, error_type: str, message: str) -> bottle.HTTPResponse:
    return bottle.HTTPResponse(
        status=status,
        body=json.dumps(
            {"type": "error", "error": {"type": error_type, "message": message}},
            ensure_ascii=False,
        ),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )


def _upstream_error(upstream: httpx.Response) -> bottle.HTTPResponse:
    # A streaming error response has not had its body consumed yet.
    if not upstream.is_closed:
        upstream.read()
    try:
        body = upstream.json()
        message = (body.get("error") or {}).get("message") or upstream.text
    except (ValueError, AttributeError):
        message = upstream.text
    message = message or f"OpenAI upstream returned HTTP {upstream.status_code}"
    logger.error("Upstream error status={} message={}", upstream.status_code, message)
    error_type = "authentication_error" if upstream.status_code in {401, 403} else "api_error"
    return _error_response(upstream.status_code, error_type, message)


def _read_json_body() -> dict[str, Any]:
    raw = bottle.request.body.read()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise TypeError("JSON body must be an object")
    return value


def _open_upstream_stream(
    upstream_url: str,
    upstream_headers: dict[str, str],
    openai_body: dict[str, Any],
    timeout: httpx.Timeout,
) -> tuple[httpx.Client, httpx.Response]:
    client = httpx.Client(timeout=timeout)
    try:
        request = client.build_request("POST", upstream_url, headers=upstream_headers, json=openai_body)
        return client, client.send(request, stream=True)
    except Exception:
        client.close()
        raise


def _make_app(
    openai_base_url: str,
    openai_api_key: str,
    model_name: str,
    proxy_api_key: str,
    api_mode: OpenAIApiMode = "auto",
) -> bottle.Bottle:
    app = bottle.Bottle()
    resolved_api_mode = _resolve_api_mode(openai_base_url, api_mode)
    if resolved_api_mode == "responses":
        upstream_url = _responses_url(openai_base_url)
    else:
        upstream_url = _chat_completions_url(openai_base_url)
    upstream_headers = {
        "Authorization": f"Bearer {openai_api_key}",
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(connect=20.0, read=None, write=60.0, pool=20.0)

    def authorized() -> bool:
        key = bottle.request.headers.get("X-Api-Key")
        if not key:
            authorization = bottle.request.headers.get("Authorization", "")
            if authorization.lower().startswith("bearer "):
                key = authorization[7:]
        return bool(key) and secrets.compare_digest(key, proxy_api_key)

    @app.get("/")
    @app.get("/healthz")
    def health() -> dict[str, Any]:
        return {"status": "ok", "model": model_name, "api_mode": resolved_api_mode}

    @app.post("/v1/messages/count_tokens")
    def count_tokens() -> Any:
        if not authorized():
            return _error_response(401, "authentication_error", "Invalid API key")
        try:
            body = _read_json_body()
            openai_body = (
                _responses_request(body, model_name)
                if resolved_api_mode == "responses"
                else _openai_request(body, model_name)
            )
            return {"input_tokens": _estimate_tokens(_token_input(openai_body, resolved_api_mode))}
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return _error_response(400, "invalid_request_error", str(exc))

    @app.post("/v1/messages")
    def messages() -> Any:
        if not authorized():
            return _error_response(401, "authentication_error", "Invalid API key")
        started = time.monotonic()
        try:
            body = _read_json_body()
            if not isinstance(body.get("messages"), list):
                return _error_response(400, "invalid_request_error", "messages must be a list")
            if resolved_api_mode == "responses":
                openai_body = _responses_request(body, model_name)
                message_count = len(openai_body["input"])
            else:
                openai_body = _openai_request(body, model_name)
                message_count = len(openai_body["messages"])
            logger.info(
                "Request model={} api_mode={} stream={} messages={} tools={}",
                model_name,
                resolved_api_mode,
                openai_body["stream"],
                message_count,
                len(openai_body.get("tools", [])),
            )

            if openai_body["stream"]:
                client, upstream = _open_upstream_stream(upstream_url, upstream_headers, openai_body, timeout)
                if upstream.is_error:
                    try:
                        return _upstream_error(upstream)
                    finally:
                        upstream.close()
                        client.close()
                bottle.response.content_type = "text/event-stream; charset=utf-8"
                bottle.response.set_header("Cache-Control", "no-cache")
                bottle.response.set_header("X-Accel-Buffering", "no")
                input_tokens = _estimate_tokens(_token_input(openai_body, resolved_api_mode))
                logger.info("Streaming response started in {:.3f}s", time.monotonic() - started)
                stream_converter = _stream_responses_response if resolved_api_mode == "responses" else _stream_response
                return stream_converter(client, upstream, body.get("model") or model_name, input_tokens)

            with httpx.Client(timeout=timeout) as client:
                upstream = client.post(upstream_url, headers=upstream_headers, json=openai_body)
            if upstream.is_error:
                return _upstream_error(upstream)
            if resolved_api_mode == "responses":
                converted = _anthropic_responses_response(upstream.json(), body.get("model") or model_name)
            else:
                converted = _anthropic_response(upstream.json(), body.get("model") or model_name)
            logger.info(
                "Response completed status={} elapsed={:.3f}s",
                upstream.status_code,
                time.monotonic() - started,
            )
            return converted
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("Invalid request: {}", exc)
            return _error_response(400, "invalid_request_error", str(exc))
        except httpx.RequestError as exc:
            logger.exception("Cannot reach OpenAI upstream: {}", exc)
            return _error_response(502, "api_error", f"Cannot reach OpenAI upstream: {exc}")
        except Exception as exc:  # noqa: BLE001 - WSGI boundary returns structured API errors
            logger.exception("Unhandled proxy error: {}", exc)
            return _error_response(500, "api_error", str(exc))

    return app


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return


class _ReusableWSGIServer(ThreadingMixIn, WSGIServer):
    allow_reuse_address = True
    daemon_threads = True


def _run_proxy_process(
    host: str,
    port: int,
    openai_base_url: str,
    openai_api_key: str,
    model_name: str,
    log_file_path: str,
    proxy_api_key: str,
    api_mode: OpenAIApiMode,
) -> None:
    logger.remove()
    logger.add(
        log_file_path,
        level="INFO",
        encoding="utf-8",
        backtrace=False,
        diagnose=False,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {message}",
    )
    app = _make_app(openai_base_url, openai_api_key, model_name, proxy_api_key, api_mode)
    logger.info(
        "Claude proxy starting at http://{}:{} model={} api_mode={}",
        host,
        port,
        model_name,
        api_mode,
    )
    with make_server(
        host,
        port,
        app,
        server_class=_ReusableWSGIServer,
        handler_class=_QuietHandler,
    ) as server:
        server.serve_forever()


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def start_proxy(
    openai_base_url: str,
    openai_api_key: str,
    model_name: str,
    log_file_path: str,
    api_mode: OpenAIApiMode = "auto",
) -> ClaudeProxyInfo:
    """Start the proxy asynchronously and return its connection information.

    The returned named tuple can either be unpacked or accessed through its
    ``base_url``, ``api_key`` and ``model_name`` attributes. ``api_mode`` may
    be ``chat_completions`` or ``responses``. In ``auto`` mode, a base URL
    ending in ``/responses`` selects Responses; other URLs retain the legacy
    Chat Completions behavior.
    """

    global _process, _proxy_info
    if not openai_api_key:
        raise ValueError("openai_api_key cannot be empty")
    if not model_name or not model_name.strip():
        raise ValueError("model_name cannot be empty")
    resolved_api_mode = _resolve_api_mode(openai_base_url, api_mode)
    if resolved_api_mode == "responses":
        _responses_url(openai_base_url)
    else:
        _chat_completions_url(openai_base_url)
    log_path = Path(log_file_path).expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with _lifecycle_lock:
        if _process is not None and _process.is_alive():
            raise RuntimeError("A Claude proxy process is already running")

        host = "127.0.0.1"
        port = _free_local_port()
        proxy_api_key = f"sk-ant-proxy-{secrets.token_urlsafe(24)}"
        info = ClaudeProxyInfo(
            base_url=f"http://{host}:{port}",
            api_key=proxy_api_key,
            model_name=model_name.strip(),
        )
        process = multiprocessing.Process(
            target=_run_proxy_process,
            args=(
                host,
                port,
                openai_base_url,
                openai_api_key,
                info.model_name,
                str(log_path),
                proxy_api_key,
                resolved_api_mode,
            ),
            name="claude-openai-proxy",
            daemon=True,
        )
        process.start()
        _process = process
        _proxy_info = info

    # Fail fast if the child could not import dependencies or bind its port.
    deadline = time.monotonic() + 10.0
    health_url = f"{info.base_url}/healthz"
    try:
        async with httpx.AsyncClient(timeout=0.25) as client:
            while time.monotonic() < deadline:
                if not process.is_alive():
                    raise RuntimeError("Claude proxy process exited during startup; check the log file")
                try:
                    response = await client.get(health_url)
                    if response.status_code == 200:
                        return info
                except httpx.RequestError:
                    pass
                await asyncio.sleep(0.05)
    except BaseException:
        await stop_proxy()
        raise

    await stop_proxy()
    raise TimeoutError("Claude proxy did not become ready within 10 seconds")


def _take_proxy_process() -> multiprocessing.Process | None:
    global _process, _proxy_info
    with _lifecycle_lock:
        process = _process
        _process = None
        _proxy_info = None
    return process


def _terminate_proxy_process(process: multiprocessing.Process, timeout: float) -> None:
    if process.is_alive():
        process.terminate()
        process.join(timeout=max(0.0, timeout))
    if process.is_alive():
        process.kill()
        process.join(timeout=1.0)
    else:
        process.join(timeout=0)


def _stop_proxy_at_exit(timeout: float = 5.0) -> None:
    process = _take_proxy_process()
    if process is None:
        return
    _terminate_proxy_process(process, timeout)


async def stop_proxy(timeout: float = 5.0) -> None:
    """Stop the proxy without blocking the caller's event loop."""

    process = _take_proxy_process()
    if process is None:
        return
    await asyncio.to_thread(_terminate_proxy_process, process, timeout)


async def close_proxy(timeout: float = 5.0) -> None:
    """Alias for :func:`stop_proxy`."""

    await stop_proxy(timeout)


atexit.register(_stop_proxy_at_exit)
