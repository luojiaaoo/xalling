"""Standalone installer helper: inspect, check space and move user data."""

import argparse
import configparser
import ctypes
import hashlib
import os
import shutil
import sys
import tempfile
import tomllib
from contextlib import contextmanager
from pathlib import Path
from time import monotonic

import tomli_w
from loguru import logger

from backend.config.paths import load_data_dir

MIN_FREE_SPACE_BYTES = 1024**3
COPY_BUFFER_SIZE = 4 * 1024 * 1024


def format_size(byte_count: int) -> str:
    """Format sizes with familiar KB/MB/GB labels, using 1024 per unit."""
    value = float(byte_count)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < 1024 or unit == "PB":
            return f"{int(value)} B" if unit == "B" else f"{value:.2f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


def existing_data_dir() -> Path:
    """Use the same configured/default directory as the application."""
    return load_data_dir(create_config=False)


class FileProgress:
    """Throttle progress updates while still reporting within large files."""

    def __init__(self, phase: str, total_files: int, total_bytes: int) -> None:
        self.phase = phase
        self.total_files = total_files
        self.total_bytes = total_bytes
        self.completed_files = 0
        self.completed_bytes = 0
        self.next_update = 0.0
        logger.info("开始{}，共 {} 个文件，{}", phase, total_files, format_size(total_bytes))

    def advance(self, byte_count: int = 0, *, file_completed: bool = False) -> None:
        self.completed_bytes += byte_count
        self.completed_files += int(file_completed)
        now = monotonic()
        if now < self.next_update and self.completed_files != self.total_files:
            return
        self.next_update = now + 0.5
        percent = self.completed_bytes / self.total_bytes * 100 if self.total_bytes else 100
        logger.info("{}：{:.1f}%，{} / {}，文件 {}/{}", self.phase, percent,
                    format_size(self.completed_bytes), format_size(self.total_bytes),
                    self.completed_files, self.total_files)


def file_digest(path: Path, progress: FileProgress) -> bytes:
    """Hash in chunks so even a multi-GB file emits regular progress."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(COPY_BUFFER_SIZE):
            digest.update(chunk)
            progress.advance(len(chunk))
    progress.advance(file_completed=True)
    return digest.digest()


def copy_and_hash(src: Path, dst: Path, progress: FileProgress) -> bytes:
    """Copy and collect the source hash in one pass, preserving file metadata."""
    digest = hashlib.sha256()
    with src.open("rb") as source, dst.open("wb") as target:
        while chunk := source.read(COPY_BUFFER_SIZE):
            target.write(chunk)
            digest.update(chunk)
            progress.advance(len(chunk))
    shutil.copystat(src, dst)
    progress.advance(file_completed=True)
    return digest.digest()


def inventory(root: Path, *, report_progress: bool = False) -> dict[Path, tuple[int, int]]:
    """List files without following symlinks or Windows directory junctions."""
    def raise_walk_error(error: OSError) -> None:
        raise error

    files = {}
    size = 0
    next_update = 0.0
    for directory, folders, names in root.walk(on_error=raise_walk_error):
        for name in folders + names:
            item = directory / name
            if item.is_symlink() or item.is_junction():
                raise ValueError(f"数据目录包含链接，请先手动处理：{item}")
        for name in names:
            item = directory / name
            stat = item.stat()
            files[item.relative_to(root)] = (stat.st_size, stat.st_mtime_ns)
            size += stat.st_size
            if report_progress and monotonic() >= next_update:
                logger.info("计算大小：已扫描 {} 个文件，{}", len(files), format_size(size))
                next_update = monotonic() + 0.5
    if report_progress:
        logger.info("大小计算完成：{} 个文件，{}", len(files), format_size(size))
    return files


def prepare_migration(
    target: Path, *, mode: str = "copy", report_progress: bool = False,
) -> tuple[dict[str, str], dict[Path, tuple[int, int]]]:
    """Check directory relationships, conflicts and destination free space."""
    if mode not in {"copy", "move"}:
        raise ValueError("迁移方式必须为 copy 或 move。")
    source = existing_data_dir()
    target = target.expanduser()
    if not target.is_absolute():
        raise ValueError("请选择绝对路径。")
    if target.is_symlink() or target.is_junction():
        raise ValueError("目标目录不能是链接或目录联接。")
    target = target.resolve()
    if target == Path(target.anchor):
        raise ValueError("请选择专用的数据文件夹，不要直接使用磁盘根目录。")
    moving = source.is_dir() and source != target
    files = {}
    if moving:
        config_path = (Path.home() / "xalling-paths.toml").resolve()
        if source == Path(source.anchor) or config_path.is_relative_to(source):
            raise ValueError("源目录不能是磁盘根目录或包含路径配置文件的用户主目录。")
        if source.is_relative_to(target) or target.is_relative_to(source):
            raise ValueError("新旧数据目录不能相互包含。")
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ValueError("目标目录非空，请选择空目录，避免覆盖已有文件。")
        files = inventory(source, report_progress=report_progress)
    elif target.exists() and not target.is_dir():
        raise ValueError("目标路径是文件，请选择目录。")
    size = sum(stat[0] for stat in files.values())
    # Copy needs the full size even on the same drive, plus over 1 GiB free.
    allocated_size = sum((stat[0] + 4095) // 4096 * 4096 for stat in files.values())
    ancestor = target
    while not ancestor.exists():
        ancestor = ancestor.parent
    # A direct move on the same filesystem renames the directory in place.
    same_filesystem = moving and source.stat().st_dev == ancestor.stat().st_dev
    required = (0 if mode == "move" and same_filesystem else allocated_size) + MIN_FREE_SPACE_BYTES + 1
    free = shutil.disk_usage(ancestor).free
    if free < required:
        raise ValueError(
            f"目标磁盘空间不足：迁移后必须剩余超过 1 GB（1024 MB）；"
            f"需要 {format_size(required)}，可用 {format_size(free)}。"
        )
    return {
        "source": str(source), "target": str(target), "moving": str(int(moving)),
        "size": str(size), "required": str(required), "free": str(free), "mode": mode,
        "size_display": format_size(size), "required_display": format_size(required),
        "free_display": format_size(free),
    }, files


def plan(target: Path, *, mode: str = "copy") -> dict[str, str]:
    """Expose a diagnostic space check without changing any data."""
    return prepare_migration(target, mode=mode)[0]


def ensure_free_space_reserve(directory: Path) -> None:
    """Recheck actual free space before switching the data directory."""
    if shutil.disk_usage(directory).free <= MIN_FREE_SPACE_BYTES:
        raise ValueError("目标磁盘空间不足：迁移后必须剩余超过 1 GB（1024 MB），原路径配置保持不变。")


@contextmanager
def migration_lock():
    """Hold the application's mutex so it cannot start while data is copied."""
    if os.name != "nt":
        yield
        return
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    api.CreateMutexW.restype = ctypes.c_void_p
    api.CloseHandle.argtypes = [ctypes.c_void_p]
    api.CloseHandle.restype = ctypes.c_int
    handle = api.CreateMutexW(None, False, "Global\\Xalling.SingleInstance")
    error = ctypes.get_last_error()
    if not handle:
        raise ctypes.WinError(error)
    try:
        if error == 183:
            raise ValueError("Xalling 正在运行，请关闭桌面和无头服务后重试。")
        yield
    finally:
        api.CloseHandle(handle)


def switch_data_dir(target: Path, *, mode: str = "copy") -> dict[str, str]:
    """Move directly or copy and verify before committing and deleting source."""
    with migration_lock():
        logger.info("开始检查迁移目录和磁盘空间，方式：{}", mode)
        result, before = prepare_migration(target, mode=mode, report_progress=True)
        source = Path(result["source"])
        target = Path(result["target"])
        logger.info("源目录：{}；目标目录：{}；数据大小：{}；所需空间：{}；可用空间：{}",
                    source, target, result["size_display"], result["required_display"], result["free_display"])
        if result["moving"] == "1" and mode == "move":
            logger.warning("开始剪切，请勿停止安装或关闭电脑，中断可能导致数据分散或不完整。")
            hashes = {}
            hash_progress = FileProgress("读取源校验值", len(before), int(result["size"]))
            for relative in before:
                hashes[relative] = file_digest(source / relative, hash_progress)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target.rmdir()

            move_progress = FileProgress("剪切", len(before), int(result["size"]))

            def move_copy(src, dst):
                copy_and_hash(Path(src), Path(dst), move_progress)
                return dst

            try:
                logger.info("正在剪切目录：{} → {}", source, target)
                shutil.move(str(source), str(target), copy_function=move_copy)
                if inventory(target) != before:
                    raise ValueError("剪切后的文件列表与源目录不一致")
                verify_progress = FileProgress("校验", len(before), int(result["size"]))
                for relative, expected in hashes.items():
                    if file_digest(target / relative, verify_progress) != expected:
                        raise ValueError(f"剪切校验失败：{relative}")
                ensure_free_space_reserve(target)
            except (OSError, ValueError) as error:
                raise ValueError(
                    f"剪切迁移未完成，请检查源目录 {source} 和目标目录 {target}，不要删除其中任何数据。原因：{error}"
                ) from error
        elif result["moving"] == "1":
            target.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix="xalling-migration-", dir=target.parent))
            try:
                copy_progress = FileProgress("复制", len(before), int(result["size"]))
                hashes = {}

                def copy_file(src, dst):
                    relative = Path(src).relative_to(source)
                    hashes[relative] = copy_and_hash(Path(src), Path(dst), copy_progress)
                    return dst

                shutil.copytree(source, stage, dirs_exist_ok=True, copy_function=copy_file)
                verify_progress = FileProgress("校验", len(before), int(result["size"]))
                for relative in before:
                    if file_digest(stage / relative, verify_progress) != hashes[relative]:
                        raise ValueError(f"迁移校验失败：{relative}")
                logger.info("确认源数据在复制期间未发生变化…")
                if inventory(source) != before:
                    raise ValueError("迁移期间源数据发生变化，请关闭使用数据目录的程序后重试。")
                ensure_free_space_reserve(stage)
                if target.exists():
                    target.rmdir()  # Fails safely if another process added files.
                stage.rename(target)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        else:
            target.mkdir(parents=True, exist_ok=True)
            ensure_free_space_reserve(target)

        logger.info("数据就绪，正在更新路径配置")
        config_path = Path.home() / "xalling-paths.toml"
        config = tomllib.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.exists() else {}
        config["data_dir"] = str(target)
        descriptor, temporary_name = tempfile.mkstemp(prefix="xalling-paths-", suffix=".toml", dir=Path.home())
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(tomli_w.dumps(config))
            temporary.replace(config_path)
        finally:
            temporary.unlink(missing_ok=True)
        result["cleanup_warning"] = ""
        if result["moving"] == "1" and mode == "copy":
            try:
                logger.info("配置已更新，正在删除旧目录：{}", source)
                # Only remove the validated source while it still matches the copy.
                if source.is_symlink() or source.is_junction() or source.resolve() != source:
                    raise ValueError("源目录路径发生变化")
                if inventory(source) != before:
                    raise ValueError("源目录内容发生变化")
                shutil.rmtree(source)
            except (OSError, ValueError) as error:
                result["cleanup_warning"] = (
                    f"数据已迁移到 {target}，路径配置已更新，但旧目录 {source} 未完全删除，请手动清理。原因：{error}"
                ).replace("\r", " ").replace("\n", " ")
                logger.warning(result["cleanup_warning"])
        logger.info("迁移完成：{}", target)
        return result


def main() -> None:
    """Use a UTF-16 INI result for Inno Setup's Unicode INI reader."""
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["inspect", "check", "migrate"])
    parser.add_argument("--target", type=Path)
    parser.add_argument("--mode", choices=["copy", "move"], default="copy")
    parser.add_argument("--log", type=Path)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    logger.remove()
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write("\ufeff")
        sys.stdout.flush()
        logger.add(sys.stdout, format="{time:HH:mm:ss} | {message}", colorize=False)
    log_sink = None
    if args.log is not None:
        log_sink = logger.add(args.log, encoding="utf-8", format="{time:YYYY-MM-DD HH:mm:ss} | {message}")
    try:
        if args.action == "inspect":
            source = existing_data_dir()
            result = {"source": str(source), "found": str(int(source.is_dir()))}
        elif args.target is None:
            raise ValueError("缺少目标目录。")
        elif args.action == "check":
            result = plan(args.target, mode=args.mode)
        else:
            result = switch_data_dir(args.target, mode=args.mode)
        result["error"] = ""
    except (OSError, ValueError) as error:
        result = {"error": str(error).replace("\r", " ").replace("\n", " ")}
        logger.error("迁移失败：{}", result["error"])
        if args.mode == "move" and args.action == "migrate":
            result["error"] += " 剪切可能已移动部分数据，请检查源目录和目标目录，勿删除任何一方。"
    response = configparser.ConfigParser(interpolation=None)
    response["result"] = result
    with args.result.open("w", encoding="utf-16") as output:
        response.write(output)
    if log_sink is not None:
        logger.remove(log_sink)  # Close the file before deleting it on Windows.
        if not result["error"] and not result.get("cleanup_warning"):
            try:
                args.log.unlink(missing_ok=True)
            except OSError as error:
                logger.warning("迁移已完成，但日志未能删除：{}；原因：{}", args.log, error)
    raise SystemExit(1 if result["error"] else 0)


if __name__ == "__main__":
    main()
