"""Typed, event-oriented wrapper around :class:`ClaudeSDKClient`.

The package exposes a stable event protocol suitable for SSE and other realtime
transports while keeping SDK message adaptation and usage accounting internal.
"""

from .client import ClaudeChatClient
from .file_checkpoint import FileCheckpointStore
from .history import ClaudeChatHistory, assemble_session_messages
from .models import (
    AskUserAnswer,
    AskUserQuestionCompletedData,
    AskUserQuestionItem,
    AskUserQuestionOption,
    AskUserQuestionRequestedData,
    ChatEvent,
    ChatResult,
    ChatSearchMatch,
    ChatSessionInfo,
    ChatSessionSnapshot,
    CompletionHandler,
    EventData,
    EventHandler,
    EventName,
    ExitPlanModeCompletedData,
    ExitPlanModeRequestedData,
    FileRestoreResult,
    PermissionHandler,
    PermissionModeChangedData,
    PermissionRequestedData,
    PermissionResolvedData,
    PlanApprovalMode,
    SpecialEventData,
    SubagentUsage,
    TurnUsage,
)

__all__ = [
    "AskUserAnswer",
    "AskUserQuestionCompletedData",
    "AskUserQuestionItem",
    "AskUserQuestionOption",
    "AskUserQuestionRequestedData",
    "ChatEvent",
    "ChatResult",
    "ChatSearchMatch",
    "ChatSessionInfo",
    "ChatSessionSnapshot",
    "ClaudeChatClient",
    "ClaudeChatHistory",
    "CompletionHandler",
    "EventData",
    "EventHandler",
    "EventName",
    "ExitPlanModeCompletedData",
    "ExitPlanModeRequestedData",
    "FileCheckpointStore",
    "FileRestoreResult",
    "PermissionHandler",
    "PermissionModeChangedData",
    "PermissionRequestedData",
    "PermissionResolvedData",
    "PlanApprovalMode",
    "SpecialEventData",
    "SubagentUsage",
    "TurnUsage",
    "assemble_session_messages",
]
