"""Safe model-related methods exposed to the local Web UI."""

from typing import TypedDict

from backend.config.setting import Settings


class ModelGroup(TypedDict):
    """Model provider fields that are safe to expose to the Web UI."""

    name: str
    models: list[str]
    vision: bool


class ModelRouter:
    """Expose the non-sensitive subset of the local model configuration."""

    def get_model_groups(self) -> list[ModelGroup]:
        """Return model groups without exposing credentials or endpoint URLs."""
        return [{"name": model.name, "models": model.models, "vision": model.vision} for model in Settings().model]
