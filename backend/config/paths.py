"""Resolve the application data directory before loading other settings."""

import tomllib
from pathlib import Path


def load_data_dir(*, create_config: bool = True) -> Path:
    """Read ~/xalling-paths.toml, resolving relative paths against home."""
    home = Path.home()
    config_path = home / "xalling-paths.toml"
    try:
        contents = config_path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        if create_config:
            config_path.write_text('data_dir = "~/xalling-userdata"\n', encoding="utf-8")
        return (home / "xalling-userdata").resolve()

    try:
        config = tomllib.loads(contents)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{config_path}: TOML 格式无效") from exc
    value = config.get("data_dir", "~/xalling-userdata")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{config_path}: data_dir 必须是非空路径字符串")

    directory = Path(value).expanduser()
    if not directory.is_absolute():
        directory = home / directory
    directory = directory.resolve()
    if directory.exists() and not directory.is_dir():
        raise NotADirectoryError(f"{config_path}: data_dir 指向的路径不是目录")
    return directory
