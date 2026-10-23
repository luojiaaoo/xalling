"""Installer migration removes the source only after verification and commit."""

import hashlib
import shutil
import subprocess
import sys
import tomllib
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from script import installer_data

CLI_CODE = (
    "from contextlib import nullcontext; from script import installer_data; "
    "installer_data.migration_lock = nullcontext; installer_data.main()"
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    # File migration tests use temporary directories and must not lock the user's app.
    monkeypatch.setattr(installer_data, "migration_lock", nullcontext)
    return tmp_path


def seed(home):
    source = home / "old"
    source.mkdir()
    (source / "sessions").mkdir()
    (source / "sessions" / "中文.jsonl").write_bytes(b"conversation\x00data")
    (source / "empty").mkdir()
    config = home / "xalling-paths.toml"
    config.write_text("data_dir = 'old'\nother = 42\n", encoding="utf-8")
    return source, config


@pytest.mark.parametrize(("size", "display"), [
    (0, "0 B"), (1023, "1023 B"), (1024, "1.00 KB"),
    (1536 * 1024, "1.50 MB"), (2 * 1024**3, "2.00 GB"), (1024**4, "1.00 TB"),
])
def test_format_size_uses_readable_units(size, display):
    assert installer_data.format_size(size) == display


def test_inspect_does_not_create_config(home):
    assert installer_data.existing_data_dir() == home / "xalling-userdata"
    assert not (home / "xalling-paths.toml").exists()
    (home / ".xalling").mkdir()
    assert installer_data.existing_data_dir() == home / "xalling-userdata"


def test_existing_data_dir_uses_config_even_when_directory_is_missing(home):
    (home / "xalling-userdata").mkdir()
    (home / "xalling-paths.toml").write_text("data_dir = 'custom'\n", encoding="utf-8")
    assert installer_data.existing_data_dir() == home / "custom"


def test_migrate_moves_all_data_and_preserves_config_fields(home):
    source, config = seed(home)
    target = home / "new 中文 user's data"
    result = installer_data.switch_data_dir(target)

    assert result["moving"] == "1"
    assert int(result["size"]) == len(b"conversation\x00data")
    assert result["size_display"] == "17 B"
    assert result["required_display"].endswith("GB")
    assert (target / "sessions" / "中文.jsonl").read_bytes() == b"conversation\x00data"
    assert not source.exists()
    assert result["cleanup_warning"] == ""
    assert (target / "empty").is_dir()
    assert tomllib.loads(config.read_text(encoding="utf-8")) == {"data_dir": str(target), "other": 42}


def test_insufficient_space_leaves_everything_unchanged(home, monkeypatch):
    source, config = seed(home)
    before = config.read_bytes()
    target = home / "new"
    monkeypatch.setattr(shutil, "disk_usage", lambda path: SimpleNamespace(free=0))
    with pytest.raises(ValueError, match="空间不足"):
        installer_data.switch_data_dir(target)
    assert config.read_bytes() == before
    assert source.is_dir()
    assert not target.exists()


@pytest.mark.parametrize("extra_bytes", [-1, 0, 1])
def test_preflight_requires_more_than_one_gib_after_copy(home, monkeypatch, extra_bytes):
    seed(home)
    # The seeded file occupies one 4 KiB allocation unit.
    available = 4096 + 1024**3 + extra_bytes
    monkeypatch.setattr(shutil, "disk_usage", lambda path: SimpleNamespace(free=available))
    if extra_bytes <= 0:
        with pytest.raises(ValueError, match="超过 1 GB"):
            installer_data.plan(home / "new")
    else:
        result = installer_data.plan(home / "new")
        assert int(result["required"]) == available


def test_space_consumed_during_copy_does_not_switch_config(home, monkeypatch):
    source, config = seed(home)
    before = config.read_bytes()
    free_space = iter([2 * 1024**3, 1024**3])
    monkeypatch.setattr(shutil, "disk_usage", lambda path: SimpleNamespace(free=next(free_space)))
    target = home / "new"
    with pytest.raises(ValueError, match="超过 1 GB"):
        installer_data.switch_data_dir(target)
    assert config.read_bytes() == before
    assert source.is_dir()
    assert not target.exists()
    assert not list(home.glob("xalling-migration-*"))


@pytest.mark.parametrize("kind", ["inside", "outside", "nonempty", "file", "relative", "root"])
def test_rejects_unsafe_targets(home, kind):
    source, config = seed(home)
    target = home / "new"
    if kind == "inside":
        target = source / "nested"
    elif kind == "outside":
        target = home
    elif kind == "nonempty":
        target.mkdir()
        (target / "precious").touch()
    elif kind == "file":
        target.touch()
    elif kind == "relative":
        target = Path("relative")
    else:
        target = Path(home.anchor)
    before = config.read_bytes()
    with pytest.raises(ValueError):
        installer_data.switch_data_dir(target)
    assert config.read_bytes() == before


def test_copy_failure_cleans_staging_and_keeps_original(home, monkeypatch):
    source, config = seed(home)
    before = config.read_bytes()
    target = home / "new"

    def fail(*args, **kwargs):
        raise OSError("copy failed")

    monkeypatch.setattr(shutil, "copytree", fail)
    with pytest.raises(OSError, match="copy failed"):
        installer_data.switch_data_dir(target)
    assert config.read_bytes() == before
    assert source.is_dir()
    assert not target.exists()
    assert not list(home.glob("xalling-migration-*"))


def test_same_directory_does_not_copy_or_require_full_size(home):
    source, config = seed(home)
    result = installer_data.switch_data_dir(source)
    assert result["moving"] == "0"
    assert result["size"] == "0"
    assert tomllib.loads(config.read_text(encoding="utf-8"))["data_dir"] == str(source)


def test_migrate_explicitly_configured_directory(home):
    source = home / ".xalling"
    source.mkdir()
    (source / "history").write_bytes(b"old history")
    (home / "xalling-paths.toml").write_text("data_dir = '.xalling'\n", encoding="utf-8")
    target = home / "xalling-userdata"
    installer_data.switch_data_dir(target)
    assert (target / "history").read_bytes() == b"old history"
    assert not source.exists()


def test_config_write_failure_does_not_delete_source(home, monkeypatch):
    source, config = seed(home)
    before = config.read_bytes()
    replace = Path.replace

    def fail_config_replace(path, target):
        if Path(target) == config:
            raise OSError("config write failed")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_config_replace)
    with pytest.raises(OSError, match="config write failed"):
        installer_data.switch_data_dir(home / "new")
    assert config.read_bytes() == before
    assert (source / "sessions" / "中文.jsonl").read_bytes() == b"conversation\x00data"


def test_source_delete_failure_keeps_new_data_and_reports_warning(home, monkeypatch):
    source, config = seed(home)
    target = home / "new"
    rmtree = shutil.rmtree

    def fail_source_delete(path, *args, **kwargs):
        if Path(path) == source:
            # Configuration must already point at the verified destination.
            assert tomllib.loads(config.read_text(encoding="utf-8"))["data_dir"] == str(target)
            raise PermissionError("file in use")
        return rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", fail_source_delete)
    result = installer_data.switch_data_dir(target)
    assert (target / "sessions" / "中文.jsonl").read_bytes() == b"conversation\x00data"
    assert source.exists()
    assert "未完全删除" in result["cleanup_warning"]
    assert "file in use" in result["cleanup_warning"]


def test_source_cannot_contain_bootstrap_config(home, monkeypatch):
    # A configured home directory must never be recursively removed.
    config = home / "xalling-paths.toml"
    config.write_text("data_dir = '.'\n", encoding="utf-8")
    monkeypatch.setattr(installer_data, "existing_data_dir", lambda: home)
    with pytest.raises(ValueError, match="用户主目录"):
        installer_data.plan(home.parent / "external-target")
    assert config.exists()


def test_direct_move_transfers_and_verifies_data(home):
    source, config = seed(home)
    target = home / "new"
    result = installer_data.switch_data_dir(target, mode="move")
    assert result["mode"] == "move"
    assert not source.exists()
    assert (target / "sessions" / "中文.jsonl").read_bytes() == b"conversation\x00data"
    assert tomllib.loads(config.read_text(encoding="utf-8"))["data_dir"] == str(target)


def test_direct_move_on_same_disk_does_not_reserve_copy_space(home, monkeypatch):
    seed(home)
    monkeypatch.setattr(shutil, "disk_usage", lambda path: SimpleNamespace(free=1024**3 + 1))
    assert int(installer_data.plan(home / "new", mode="move")["required"]) == 1024**3 + 1
    with pytest.raises(ValueError, match="空间不足"):
        installer_data.plan(home / "new", mode="copy")


def test_interrupted_direct_move_keeps_both_directories_for_recovery(home, monkeypatch):
    source, config = seed(home)
    original_config = config.read_bytes()
    target = home / "new"

    def fail_move(src, dst, **kwargs):
        target.mkdir()
        (source / "sessions").rename(target / "sessions")
        raise OSError("interrupted")

    monkeypatch.setattr(shutil, "move", fail_move)
    with pytest.raises(ValueError, match="不要删除其中任何数据"):
        installer_data.switch_data_dir(target, mode="move")
    assert config.read_bytes() == original_config
    assert source.is_dir()
    assert (target / "sessions" / "中文.jsonl").read_bytes() == b"conversation\x00data"


def test_cli_streams_progress_and_deletes_log_after_success(home):
    source, _config = seed(home)
    target = home / "new"
    log_file = home / "xalling-install-migration.log"
    result = subprocess.run(
        [sys.executable, "-c", CLI_CODE, "migrate", "--target", str(target),
         "--mode", "copy", "--result", str(home / "result.ini"), "--log", str(log_file)],
        capture_output=True, encoding="utf-8", timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    for message in ["复制：", "校验：", "正在删除旧目录", "迁移完成"]:
        assert message in result.stdout
    assert "所需空间：1.00 GB" in result.stdout
    assert not log_file.exists()
    assert not source.exists()


def test_migration_calculates_size_once_before_copy(home, monkeypatch):
    seed(home)
    inventory = installer_data.inventory
    calculations = []

    def record_inventory(root, *, report_progress=False):
        if report_progress:
            calculations.append(root)
        return inventory(root, report_progress=report_progress)

    monkeypatch.setattr(installer_data, "inventory", record_inventory)
    installer_data.switch_data_dir(home / "new")
    assert calculations == [home / "old"]


def test_large_file_copy_and_verification_report_chunk_progress(home, monkeypatch):
    source = home / "large.bin"
    content = b"0123456789abcdef" * (1024 * 1024)
    source.write_bytes(content)
    target = home / "copied.bin"
    ticks = iter(index * 0.6 for index in range(100))
    monkeypatch.setattr(installer_data, "monotonic", lambda: next(ticks))
    messages = []
    sink = installer_data.logger.add(messages.append, format="{message}")
    try:
        progress = installer_data.FileProgress("复制", 1, len(content))
        digest = installer_data.copy_and_hash(source, target, progress)
        verify = installer_data.FileProgress("校验", 1, len(content))
        assert installer_data.file_digest(target, verify) == digest == hashlib.sha256(content).digest()
    finally:
        installer_data.logger.remove(sink)
    assert target.read_bytes() == content
    assert any("复制：25.0%" in line and "4.00 MB / 16.00 MB" in line for line in messages)
    assert any("校验：25.0%" in line for line in messages)
    assert progress.completed_files == verify.completed_files == 1


def test_many_small_files_do_not_flood_progress_log(monkeypatch):
    monkeypatch.setattr(installer_data, "monotonic", lambda: 1.0)
    messages = []
    sink = installer_data.logger.add(messages.append, format="{message}")
    try:
        progress = installer_data.FileProgress("校验", 1000, 1000)
        for _ in range(1000):
            progress.advance(1, file_completed=True)
    finally:
        installer_data.logger.remove(sink)
    # Start, first update, final update; not one UI refresh per file.
    assert len(messages) == 3


def test_cli_keeps_log_after_failure(home):
    source, _config = seed(home)
    target = home / "occupied"
    target.mkdir()
    (target / "file").touch()
    log_file = home / "xalling-install-migration.log"
    result = subprocess.run(
        [sys.executable, "-c", CLI_CODE, "migrate", "--target", str(target),
         "--result", str(home / "result.ini"), "--log", str(log_file)],
        capture_output=True, encoding="utf-8", timeout=30, check=False,
    )
    assert result.returncode == 1
    assert source.exists()
    assert "迁移失败" in log_file.read_text(encoding="utf-8")


@pytest.mark.parametrize("failure", ["corrupt_copy", "source_changed"])
def test_verification_failure_keeps_original_config(home, monkeypatch, failure):
    source, config = seed(home)
    before = config.read_bytes()
    target = home / "new"
    copytree = shutil.copytree

    def alter_after_copy(src, dst, *args, **kwargs):
        result = copytree(src, dst, *args, **kwargs)
        if Path(src) == source:
            if failure == "corrupt_copy":
                (Path(dst) / "sessions" / "中文.jsonl").write_bytes(b"corrupt")
            else:
                (source / "new-file").touch()
        return result

    monkeypatch.setattr(shutil, "copytree", alter_after_copy)
    with pytest.raises(ValueError, match="校验失败|发生变化"):
        installer_data.switch_data_dir(target)
    assert config.read_bytes() == before
    assert not target.exists()
    assert not list(home.glob("xalling-migration-*"))
