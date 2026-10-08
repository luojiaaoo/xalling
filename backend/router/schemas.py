"""Strict JSON request models shared by FastAPI routes."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ChatConnectionRequest(RequestModel):
    session_id: str | None = Field(default=None, max_length=128)
    project_path: str | None = Field(default=None, max_length=32768)
    effort: Literal["low", "medium", "high", "max"] = "high"
    permission_mode: Literal["default", "acceptEdits", "plan", "auto", "bypassPermissions"] = "default"


class ChatMessageRequest(ChatConnectionRequest):
    prompt: str = Field(min_length=1, max_length=500_000)
    model_site: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)


class PermissionDecisionRequest(RequestModel):
    permission_id: str = Field(min_length=1, max_length=512)
    allowed: bool
    answers: dict[str, str | list[str]] | None = None
    feedback: str | None = Field(default=None, max_length=20_000)
    execution_mode: Literal["default", "acceptEdits", "auto"] | None = None


class SessionRequest(RequestModel):
    session_id: str | None = Field(default=None, max_length=128)


class AttachmentRequest(RequestModel):
    filename: str = Field(min_length=1, max_length=255)
    data: str = Field(min_length=1, max_length=70 * 1024 * 1024)


class ResizeRequest(RequestModel):
    width: int
    height: int
    edge: str = Field(min_length=1, max_length=16)


class ThemeRequest(RequestModel):
    name: str = Field(min_length=1, max_length=100)


class ModelSelectionRequest(RequestModel):
    site: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=200)


class RemoteModelsRequest(RequestModel):
    api_url: str = Field(min_length=1, max_length=8192)
    api_key: str = Field(max_length=32768)


class ModelConfigRequest(RequestModel):
    name: str = Field(min_length=1, max_length=200)
    max_context_tokens: int | None = None


class ModelSiteRequest(RemoteModelsRequest):
    original_name: str | None = Field(default=None, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    models: list[ModelConfigRequest] = Field(max_length=10000)
    api_protocol: Literal["anthropic", "chat", "responses"] = "anthropic"


class FrontendErrorRequest(RequestModel):
    kind: str = Field(min_length=1, max_length=100)
    message: str = Field(max_length=100_000)
    stack: str | None = Field(default=None, max_length=100_000)
