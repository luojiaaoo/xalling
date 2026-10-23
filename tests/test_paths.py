"""Data directory selection must not depend on the launch directory."""

from pathlib import Path

import pytest

from backend.config.paths import load_data_dir


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # Path.expanduser uses the environment rather than Path.home on Windows.
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_missing_config_defaults_to_home(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    launch_dir = home / "launch"
    launch_dir.mkdir()
    monkeypatch.chdir(launch_dir)

    assert load_data_dir() == home / "xalling-userdata"
    assert not (home / "xalling-userdata").exists()
    config_path = home / "xalling-paths.toml"
    assert config_path.read_text(encoding="utf-8") == 'data_dir = "~/xalling-userdata"\n'

    config_path.write_text("data_dir = 'changed'\n", encoding="utf-8")
    assert load_data_dir() == home / "changed"


@pytest.mark.parametrize("contents", ["", "other = true\n"])
def test_missing_data_dir_defaults_to_home(home: Path, contents: str) -> None:
    (home / "xalling-paths.toml").write_text(contents, encoding="utf-8")

    assert load_data_dir() == home / "xalling-userdata"


@pytest.mark.parametrize("kind", ["absolute", "relative", "tilde"])
def test_custom_data_dir(home: Path, kind: str) -> None:
    directory = home / "自定义数据"
    value = {"absolute": directory.as_posix(), "relative": "自定义数据", "tilde": "~/自定义数据"}[kind]
    (home / "xalling-paths.toml").write_text(f"data_dir = '{value}'\n", encoding="utf-8-sig")

    assert load_data_dir() == directory
    assert not directory.exists()


@pytest.mark.parametrize("value", ['""', '"  "', "123", "false", "[]", "{}"])
def test_invalid_data_dir_is_rejected(home: Path, value: str) -> None:
    (home / "xalling-paths.toml").write_text(f"data_dir = {value}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="data_dir"):
        load_data_dir()


def test_invalid_toml_is_rejected(home: Path) -> None:
    (home / "xalling-paths.toml").write_text("data_dir = [", encoding="utf-8")

    with pytest.raises(ValueError, match="TOML"):
        load_data_dir()


def test_data_dir_cannot_be_a_file(home: Path) -> None:
    (home / "existing-file").touch()
    (home / "xalling-paths.toml").write_text("data_dir = 'existing-file'", encoding="utf-8")

    with pytest.raises(NotADirectoryError):
        load_data_dir()
