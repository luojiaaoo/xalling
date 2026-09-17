"""Typed, event-oriented wrapper around :class:`ClaudeSDKClient`.

The package exposes a stable event protocol suitable for SSE and other realtime
transports while keeping SDK message adaptation and usage accounting internal.
"""

from .client import ClaudeChatClient
from .history import ClaudeChatHistory, assemble_session_messages
from .models import (
    AskUserAnswer,
    AskUserQuestionCompletedData,
    AskUserQuestionItem,
    AskUserQuestionOption,
    AskUserQuestionRequestedData,
    ChatEvent,
    ChatResult,
    EventData,
    EventHandler,
    EventName,
    ExitPlanModeCompletedData,
    ExitPlanModeRequestedData,
    ModelUsage,
    PermissionHandler,
    PermissionRequestedData,
    PermissionResolvedData,
    PlanApprovalMode,
    SpecialEventData,
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
    "ClaudeChatClient",
    "ClaudeChatHistory",
    "EventData",
    "EventHandler",
    "EventName",
    "ExitPlanModeCompletedData",
    "ExitPlanModeRequestedData",
    "ModelUsage",
    "PermissionHandler",
    "PermissionRequestedData",
    "PermissionResolvedData",
    "PlanApprovalMode",
    "SpecialEventData",
    "TurnUsage",
    "assemble_session_messages",
]
