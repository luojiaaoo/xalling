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


class ChatReply(TypedDict):
    """The final model response and its resumable session identifier."""

    content: str
    final_output_block_id: str | None
    session_id: str
    stopped: NotRequired[bool]
