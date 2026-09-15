"""Public types shared by the chat library and its UI adapters."""

from collections.abc import Callable
from typing import Literal, NotRequired, TypedDict

type ChatEffort = Literal["low", "medium", "high", "max"]
type ChatPermissionMode = Literal[
    "default",
    "acceptEdits",
    "plan",
    "auto",
    "bypassPermissions",
]
type ChatEvent = dict[str, object]
type ChatEventHandler = Callable[[ChatEvent], None]


class ChatUsage(TypedDict):
    """Token, cost, and timing metrics for one assistant turn."""

    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    num_turns: int
    model_name: str | None
    stop_reason: str


class ChatReply(TypedDict):
    """The final model response and its resumable session identifier."""

    content: str
    final_output_block_id: str | None
    session_id: str
    stopped: NotRequired[bool]
    usage: ChatUsage
