"""Safe model-related methods exposed to the local Web UI."""

import asyncio
from typing import TypedDict

from backend.config.current import CurrentConfig
from backend.config.setting import Settings


class ModelInfo(TypedDict):
    """Model fields that are safe to expose to the Web UI."""

    name: str
    image_vision: bool


class ModelGroup(TypedDict):
    """Model provider fields that are safe to expose to the Web UI."""

    name: str
    models: list[ModelInfo]


class ModelSelection(TypedDict):
    """The selected model site and model name."""

    site: str
    model: str


class ModelRouter:
    """Expose the non-sensitive subset of the local model configuration."""

    def get_model_groups(self) -> list[ModelGroup]:
        """Return model groups without exposing credentials or endpoint URLs."""
        return [
            {
                "name": site.name,
                "models": [
                    {"name": model.name, "image_vision": model.image_vision}
                    for model in site.models
                ],
            }
            for site in Settings().model
        ]

    def get_current_model(self) -> ModelSelection | None:
        """Return the saved selection, or persist and return the first model."""
        settings = Settings()
        current = CurrentConfig()
        selection = self._find_selection(
            settings, current.model.site, current.model.name
        )
        if selection is not None:
            return selection

        for site in settings.model:
            if site.models:
                selection = {"site": site.name, "model": site.models[0].name}
                asyncio.run(self._write_selection(selection))
                return selection
        return None

    def set_current_model(self, site: str, model: str) -> None:
        """Adapt the pywebview call to the asynchronous persistence service."""
        asyncio.run(self._set_current_model(site, model))

    async def _set_current_model(self, site: str, model: str) -> None:
        """Validate and asynchronously persist the selected model."""
        if not isinstance(site, str) or not isinstance(model, str):
            raise TypeError("模型站点和模型名称必须是字符串")

        selection = self._find_selection(Settings(), site, model)
        if selection is None:
            raise ValueError("所选模型不在当前配置中")
        await self._write_selection(selection)

    @staticmethod
    def _find_selection(
        settings: Settings, site_name: str, model_name: str
    ) -> ModelSelection | None:
        """Return a selection only when both names still exist in settings."""
        for site in settings.model:
            if site.name == site_name and any(
                model.name == model_name for model in site.models
            ):
                return {"site": site.name, "model": model_name}
        return None

    @staticmethod
    async def _write_selection(selection: ModelSelection) -> None:
        """Asynchronously write a selection into the grouped current config."""
        current = CurrentConfig(
            model={"site": selection["site"], "name": selection["model"]}
        )
        await current.write()
