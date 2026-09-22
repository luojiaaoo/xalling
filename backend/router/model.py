"""Model-related methods exposed to the local Web UI."""

from backend.service.model import ModelGroup, ModelSelection, ModelService, ModelSiteView


class ModelRouter:
    """Expose the model configuration to the pywebview bridge."""

    async def get_model_groups(self) -> list[ModelGroup]:
        """Return non-empty model groups without exposing private settings."""
        return await ModelService.get_model_groups()

    async def get_model_sites(self) -> list[ModelSiteView]:
        """Return provider configuration with API keys for in-app editing."""
        return await ModelService.get_model_sites()

    async def fetch_model_names(self, api_url: str, api_key: str) -> list[str]:
        """Fetch model names from an Anthropic/OpenAI-compatible provider."""
        return await ModelService.fetch_model_names(api_url, api_key)

    async def save_model_site(
        self,
        original_name: str | None,
        name: str,
        api_url: str,
        api_key: str,
        models: list[dict[str, object]],
        api_protocol: str = "anthropic",
    ) -> None:
        """Create or update one provider and persist its model list."""
        await ModelService.save_model_site(
            original_name,
            name,
            api_url,
            api_key,
            models,
            api_protocol,
        )

    async def delete_model_site(self, name: str) -> None:
        """Delete a provider and reset the active selection when necessary."""
        await ModelService.delete_model_site(name)

    async def get_current_model(self) -> ModelSelection | None:
        """Return the saved selection, or persist and return the first model."""
        return await ModelService.get_current_model()

    async def set_current_model(self, site: str, model: str) -> None:
        """Validate and persist the model selected from the desktop UI."""
        await ModelService.set_current_model(site, model)
