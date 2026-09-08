"""Pydantic settings loaded from the application TOML file."""

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

USER_CONF_DIRPATH = Path.home() / ".xalling"
CONF_FILEPATH = USER_CONF_DIRPATH / "setting.toml"


class ModelConfig(BaseModel):
    """One model provider and the models available through it."""

    name: str
    api_key: str = Field(default="", repr=False)
    api_url: str = ""
    models: list[str] = Field(default_factory=list)
    vision: bool = False


class Settings(BaseSettings):
    """Application settings, one field per `[group]` in the TOML file."""

    model_config = SettingsConfigDict(
        toml_file=CONF_FILEPATH,
        extra="ignore",
    )

    model: list[ModelConfig] = Field(default_factory=list)

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

    async def write(self) -> None:
        """Write all values from this instance to the configured TOML file."""
        conf_file_path = self._conf_file_path()
        await aiofiles.os.makedirs(conf_file_path.parent, exist_ok=True)
        contents = tomli_w.dumps(self.model_dump(mode="json"))
        async with aiofiles.open(conf_file_path, "w", encoding="utf-8") as file:
            await file.write(contents)
        return self
