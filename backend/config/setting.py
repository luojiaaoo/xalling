"""Pydantic settings loaded from the application TOML file."""

import tomllib
from pathlib import Path
from typing import Any, Literal, Self

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
    """Values stored in the `[model]` TOML group."""

    api_key: str = Field(default="", repr=False)
    api_url: str = ""
    models: list[str] = Field(default_factory=list)
    effort: Literal["low", "medium", "high", "xhigh"] = "medium"


class Settings(BaseSettings):
    """Application settings, one field per `[group]` in the TOML file."""

    model_config = SettingsConfigDict(
        toml_file=CONF_FILEPATH,
        extra="ignore",
    )

    model: ModelConfig = Field(default_factory=ModelConfig)

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

    def update(self, **values: Any) -> Self:
        """Apply validated values and write them while retaining unmanaged TOML groups."""
        updated_values = self.model_dump(mode="json")
        for field_name, value in values.items():
            current_value = updated_values.get(field_name)
            if isinstance(current_value, dict) and isinstance(value, dict):
                updated_values[field_name] = current_value | value
            else:
                updated_values[field_name] = value

        updated_settings = type(self).model_validate(updated_values)
        conf_file_path = self._conf_file_path()
        try:
            with conf_file_path.open("rb") as file:
                persisted_values = tomllib.load(file)
        except FileNotFoundError:
            persisted_values = {}

        persisted_values.update(updated_settings.model_dump(mode="json"))
        conf_file_path.parent.mkdir(parents=True, exist_ok=True)
        conf_file_path.write_text(tomli_w.dumps(persisted_values), encoding="utf-8")
        self.__dict__.update(updated_settings.__dict__)
        return self


