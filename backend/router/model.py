"""Safe model-related methods exposed to the local Web UI."""

from typing import TypedDict

from backend.config.setting import Settings


class ModelInfo(TypedDict):
    """Model fields that are safe to expose to the Web UI."""

    name: str
    vision: bool


class ModelGroup(TypedDict):
    """Model provider fields that are safe to expose to the Web UI."""

    name: str
    models: list[ModelInfo]


class ModelRouter:
    """Expose the non-sensitive subset of the local model configuration."""

    def get_model_groups(self) -> list[ModelGroup]:
        """Return model groups without exposing credentials or endpoint URLs."""
        return [
            {
                "name": site.name,
                "models": [
                    {"name": model.name, "vision": model.vision}
                    for model in site.models
                ],
            }
            for site in Settings().model
        ]
