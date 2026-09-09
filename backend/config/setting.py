"""Pydantic settings loaded from the application TOML file."""

from pathlib import Path

import tomli_w
from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

USER_CONF_DIRPATH = Path.home() / ".xalling"
CONF_FILEPATH = USER_CONF_DIRPATH / "setting.toml"


def default_project_folder() -> Path:
    """Return the default project folder: Desktop if it exists, else home."""
    home = Path.home().resolve()
    desktop = home / "Desktop"
    if desktop.exists() and desktop.is_dir():
        return desktop
    return home


class ModelConfig(BaseModel):
    """One model and its capabilities."""

    name: str
    image_vision: bool = False


class ModelSiteConfig(BaseModel):
    """One model site and the models available through it."""

    name: str
    api_key: str = Field(default="", repr=False)
    api_url: str = ""
    models: list[ModelConfig] = Field(default_factory=list)


class Settings(BaseSettings):
    """Application settings, one field per `[group]` in the TOML file."""

    model_config = SettingsConfigDict(
        toml_file=CONF_FILEPATH,
        extra="ignore",
    )

    model: list[ModelSiteConfig] = Field(default_factory=list)

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
        """Return the path to the TOML configuration file."""
        return Path(cls.model_config["toml_file"])

    def write(self) -> None:
        """Write all values from this instance to the configured TOML file."""
        conf_file_path = self._conf_file_path()
        conf_file_path.parent.mkdir(parents=True, exist_ok=True)
        contents = tomli_w.dumps(self.model_dump(mode="json"))
        conf_file_path.write_text(contents, encoding="utf-8")
