"""Pydantic settings for the user's current model selection."""

from pathlib import Path

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


class CurrentThemeConfig(BaseModel):
    """The currently selected UI theme."""

    name: str = "default"


class CurrentConfig(BaseSettings):
    """Current application state grouped by feature."""

    model_config = SettingsConfigDict(
        toml_file=CURRENT_CONF_FILEPATH,
        extra="ignore",
    )

    model: CurrentModelConfig = Field(default_factory=CurrentModelConfig)
    theme: CurrentThemeConfig = Field(default_factory=CurrentThemeConfig)

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

    def write(self) -> None:
        """Write the current selection to its dedicated TOML file."""
        conf_file_path = self._conf_file_path()
        conf_file_path.parent.mkdir(parents=True, exist_ok=True)
        contents = tomli_w.dumps(self.model_dump(mode="json"))
        conf_file_path.write_text(contents, encoding="utf-8")
