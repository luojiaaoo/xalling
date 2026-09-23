"""Pydantic settings loaded from the application TOML file."""

import os
from pathlib import Path
from typing import Literal

import asyncer
import tomli_w
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

USER_CONF_DIRPATH = Path(os.getcwd()) / ".xalling"
CURRENT_CONF_FILEPATH = USER_CONF_DIRPATH / "xalling-current.toml"
# 给 history 中获取历史数据的函数使用，设置环境变量
os.environ["CLAUDE_CONFIG_DIR"] = str(USER_CONF_DIRPATH)
CONF_FILEPATH = USER_CONF_DIRPATH / "xalling-setting.toml"

# UI 上传的附件落盘目录，路径会注入到提示词中供模型读取。
ATTACHMENTS_DIRECTORY = USER_CONF_DIRPATH / "xalling-attachments"

# Application log output paths.
LOG_DIRECTORY = USER_CONF_DIRPATH / "xalling-log"
ACCESS_LOG_FILEPATH = LOG_DIRECTORY / "access.log"
BROWSER_LOG_FILEPATH = LOG_DIRECTORY / "browser.log"
ERROR_LOG_FILEPATH = LOG_DIRECTORY / "error.log"
CLAUDE_SDK_FILEPATH = LOG_DIRECTORY / "claude-sdk.log"
CLAUDE_PROXY_LOG_DIRECTORY = LOG_DIRECTORY / "claude-proxy"
SCHEDULER_DATABASE_FILEPATH = USER_CONF_DIRPATH / "xalling-scheduler.sqlite3"

SESSION_DEBUG_DIRECTORY = LOG_DIRECTORY / "session-debug"

CONTEXT_TOKEN_OPTIONS = {0, 200_000, 256_000, 1_000_000}


def default_project_folder() -> Path:
    """Return the default project folder: Desktop if it exists, else home."""
    home = Path.home().resolve()
    desktop = home / "Desktop"
    if desktop.exists() and desktop.is_dir():
        return desktop
    return home


class ModelConfig(BaseModel):
    """One model and its context settings."""

    name: str
    max_context_tokens: int | None = None

    @model_validator(mode="after")
    def validate_max_context_tokens(self) -> "ModelConfig":
        """Only accept context sizes offered by the model settings UI."""
        if self.max_context_tokens is not None and self.max_context_tokens not in CONTEXT_TOKEN_OPTIONS:
            raise ValueError("上下文长度不是支持的选项")
        return self


class ModelSiteConfig(BaseModel):
    """One model site and the models available through it."""

    name: str
    api_key: str = Field(default="", repr=False)
    api_url: str = ""
    api_protocol: Literal["anthropic", "chat", "responses"] = "anthropic"
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
        contents = tomli_w.dumps(self.model_dump(mode="json", exclude_none=True))
        conf_file_path.write_text(contents, encoding="utf-8")


async def get_settings() -> Settings:
    """Load application settings without blocking the async runtime."""
    return await asyncer.asyncify(Settings)()
