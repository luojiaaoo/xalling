"""Model-related methods exposed to the local Web UI."""

from typing import TypedDict

import asyncer
import httpx
from pydantic import BaseModel, ValidationError
from yarl import URL

from backend.config.current import CurrentConfig
from backend.config.setting import (
    ModelSiteConfig,
    Settings,
    get_settings,
)


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


class ModelSiteView(TypedDict):
    """The editable fields of a model provider, including the API key."""

    name: str
    api_url: str
    api_key: str
    models: list[ModelInfo]


class _RemoteModel(BaseModel):
    """One model entry returned by a provider's models endpoint."""

    id: str | None = None
    name: str | None = None


class _RemoteModelList(BaseModel):
    """Known shapes used by Anthropic and OpenAI-compatible providers."""

    data: list[_RemoteModel | str] | None = None
    models: list[_RemoteModel | str] | None = None


class ModelRouter:
    """Expose the model configuration to the pywebview bridge."""

    async def get_model_groups(self) -> list[ModelGroup]:
        """Return non-empty model groups without exposing private settings."""
        settings = await get_settings()
        return [
            {
                "name": site.name,
                "models": [
                    {"name": model.name, "image_vision": model.image_vision}
                    for model in site.models
                ],
            }
            for site in settings.model
            if site.models
        ]

    async def get_model_sites(self) -> list[ModelSiteView]:
        """Return provider configuration with API keys for in-app editing."""
        settings = await get_settings()
        return [
            {
                "name": site.name,
                "api_url": site.api_url,
                "api_key": site.api_key,
                "models": [
                    {"name": model.name, "image_vision": model.image_vision}
                    for model in site.models
                ],
            }
            for site in settings.model
        ]

    async def fetch_model_names(self, api_url: str, api_key: str) -> list[str]:
        """Fetch model names from an Anthropic/OpenAI-compatible provider."""
        normalized_url = self._validate_text(api_url, "API 地址", 2048)
        normalized_key = self._validate_secret(api_key)
        endpoint = self._models_endpoint(normalized_url)
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {normalized_key}",
            "anthropic-version": "2023-06-01",
            "x-api-key": normalized_key,
        }

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(15.0),
            ) as client:
                response = await client.get(str(endpoint), headers=headers)
                response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise RuntimeError(f"获取模型列表失败：服务返回 HTTP {error.response.status_code}") from error
        except httpx.HTTPError as error:
            raise RuntimeError(f"获取模型列表失败：{error}") from error

        try:
            payload = _RemoteModelList.model_validate(response.json())
        except (ValidationError, ValueError) as error:
            raise RuntimeError("获取模型列表失败：服务返回了无法识别的数据") from error

        entries = payload.data if payload.data is not None else payload.models
        if entries is None:
            raise RuntimeError("获取模型列表失败：响应中没有模型列表")

        names: list[str] = []
        seen: set[str] = set()
        for entry in entries:
            raw_name = entry if isinstance(entry, str) else entry.id or entry.name
            if raw_name is None:
                continue
            name = raw_name.strip()
            if name and len(name) <= 120 and name not in seen:
                names.append(name)
                seen.add(name)

        if not names:
            raise RuntimeError("获取模型列表失败：没有找到有效的模型名称")
        return names

    async def save_model_site(
        self,
        original_name: str | None,
        name: str,
        api_url: str,
        api_key: str,
        models: list[dict[str, object]],
    ) -> None:
        """Create or update one provider and persist its model list."""
        normalized_original = self._validate_optional_name(original_name)
        normalized_name = self._validate_name(name, "供应商名称")
        normalized_url = self._validate_text(api_url, "API 地址", 2048)
        normalized_key = self._validate_secret(api_key)
        normalized_models = self._validate_models(models)

        settings = await get_settings()
        existing = next(
            (site for site in settings.model if site.name == normalized_original), None
        )
        if normalized_original is not None and existing is None:
            raise ValueError("要编辑的供应商不存在")

        for site in settings.model:
            if site.name == normalized_name and site is not existing:
                raise ValueError("供应商名称已存在")

        replacement = ModelSiteConfig(
            name=normalized_name,
            api_url=normalized_url,
            api_key=normalized_key,
            models=normalized_models,
        )
        if existing is None:
            settings.model.append(replacement)
        else:
            settings.model[settings.model.index(existing)] = replacement

        await asyncer.asyncify(settings.write)()
        self._restore_current_selection(settings)

    async def delete_model_site(self, name: str) -> None:
        """Delete a provider and reset the active selection when necessary."""
        normalized_name = self._validate_name(name, "供应商名称")
        settings = await get_settings()
        remaining_sites = [site for site in settings.model if site.name != normalized_name]
        if len(remaining_sites) == len(settings.model):
            raise ValueError("要删除的供应商不存在")

        settings.model = remaining_sites
        await asyncer.asyncify(settings.write)()
        self._restore_current_selection(settings)

    async def get_current_model(self) -> ModelSelection | None:
        """Return the saved selection, or persist and return the first model."""
        settings = await get_settings()
        current = CurrentConfig()
        selection = self._find_selection(
            settings, current.model.site, current.model.name
        )
        if selection is not None:
            return selection

        for site in settings.model:
            if site.models:
                selection = {"site": site.name, "model": site.models[0].name}
                self._write_selection(selection)
                return selection
        return None

    async def set_current_model(self, site: str, model: str) -> None:
        """Validate and persist the model selected from the desktop UI."""
        if not isinstance(site, str) or not isinstance(model, str):
            raise TypeError("模型站点和模型名称必须是字符串")

        selection = self._find_selection(await get_settings(), site, model)
        if selection is None:
            raise ValueError("所选模型不在当前配置中")
        self._write_selection(selection)

    def _restore_current_selection(self, settings: Settings) -> None:
        """Keep the saved model selection valid after provider changes."""
        current = CurrentConfig()
        selection = self._find_selection(
            settings, current.model.site, current.model.name
        )
        if selection is not None:
            return

        for site in settings.model:
            if site.models:
                self._write_selection({"site": site.name, "model": site.models[0].name})
                return
        self._write_selection({"site": "", "model": ""})

    @staticmethod
    def _validate_optional_name(value: str | None) -> str | None:
        """Normalize an optional original provider name from the UI."""
        if value is None:
            return None
        return ModelRouter._validate_name(value, "原供应商名称")

    @staticmethod
    def _validate_name(value: object, label: str) -> str:
        """Validate a short, non-empty identifier supplied through the bridge."""
        if not isinstance(value, str):
            raise TypeError(f"{label}必须是字符串")
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{label}不能为空")
        if len(normalized) > 120:
            raise ValueError(f"{label}不能超过 120 个字符")
        return normalized

    @staticmethod
    def _validate_text(value: object, label: str, max_length: int) -> str:
        """Validate plain text input while allowing an empty API address."""
        if not isinstance(value, str):
            raise TypeError(f"{label}必须是字符串")
        normalized = value.strip()
        if len(normalized) > max_length:
            raise ValueError(f"{label}不能超过 {max_length} 个字符")
        return normalized

    @staticmethod
    def _validate_secret(value: object) -> str:
        """Validate a required secret without logging it."""
        if not isinstance(value, str):
            raise TypeError("API Key 必须是字符串")
        normalized = value.strip()
        if not normalized:
            raise ValueError("API Key 不能为空")
        if len(normalized) > 4096:
            raise ValueError("API Key 不能超过 4096 个字符")
        return normalized

    @staticmethod
    def _models_endpoint(api_url: str) -> URL:
        """Build the standard models endpoint from a configured API base URL."""
        if not api_url:
            raise ValueError("请填写 API 地址")
        try:
            base_url = URL(api_url)
        except ValueError as error:
            raise ValueError("API 地址格式不正确") from error
        if base_url.scheme not in {"http", "https"} or not base_url.host:
            raise ValueError("API 地址必须是有效的 HTTP 或 HTTPS 地址")

        path = base_url.path.rstrip("/")
        if path.endswith("/models"):
            endpoint_path = path
        elif path.endswith("/v1"):
            endpoint_path = f"{path}/models"
        else:
            endpoint_path = f"{path}/v1/models"
        return base_url.with_path(endpoint_path).with_query(None).with_fragment(None)

    @classmethod
    def _validate_models(cls, value: object) -> list[ModelInfo]:
        """Validate the JSON model list supplied by the configuration screen."""
        if not isinstance(value, list):
            raise TypeError("模型列表必须是数组")

        names: set[str] = set()
        models: list[ModelInfo] = []
        for item in value:
            if not isinstance(item, dict):
                raise TypeError("模型配置必须是对象")
            model_name = cls._validate_name(item.get("name"), "模型名称")
            image_vision = item.get("image_vision", False)
            if type(image_vision) is not bool:
                raise TypeError("图片理解能力必须是布尔值")
            if model_name in names:
                raise ValueError("同一供应商内的模型名称不能重复")
            names.add(model_name)
            models.append({"name": model_name, "image_vision": image_vision})
        return models

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
    def _write_selection(selection: ModelSelection) -> None:
        """Write a selection into the grouped current configuration."""
        CurrentConfig(
            model={"site": selection["site"], "name": selection["model"]}
        ).write()
