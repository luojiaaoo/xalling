"""Pydantic settings for the user's current model selection."""

from pathlib import Path

import aiofiles
import aiofiles.os
import tomli_w
from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from backend.config.setting import USER_CONF_DIRPATH

CURRENT_CONF_FILEPATH = USER_CONF_DIRPATH / "current.toml"


class CurrentModelConfig(BaseModel):
    """The currently selected model site and model name."""

    site: str = ""
    name: str = ""


class CurrentConfig(BaseSettings):
    """Current application state grouped by feature."""

    model_config = SettingsConfigDict(
        toml_file=CURRENT_CONF_FILEPATH,
        extra="ignore",
    )

    model: CurrentModelConfig = Field(default_factory=CurrentModelConfig)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Load values from the TOML source declared in `model_config`."""
        return init_settings, TomlConfigSettingsSource(settings_cls)

    @classmethod
    def _conf_file_path(cls) -> Path:
        """Return the path to the current-selection TOML file."""
        return Path(cls.model_config["toml_file"])

    async def write(self) -> None:
        """Write the current selection to its dedicated TOML file."""
        conf_file_path = self._conf_file_path()
        await aiofiles.os.makedirs(conf_file_path.parent, exist_ok=True)
        contents = tomli_w.dumps(self.model_dump(mode="json"))
        async with aiofiles.open(conf_file_path, "w", encoding="utf-8") as file:
            await file.write(contents)
