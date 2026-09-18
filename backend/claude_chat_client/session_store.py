"""Asynchronous, file-backed session storage for the Claude SDK.

The Agent SDK exposes :class:`SessionStore` as a protocol and ships an
in-memory reference implementation.  Xalling keeps the same key layout, but
stores JSONL transcripts below ``~/.xalling/projects`` so they survive process
restarts while still being readable through the SDK's async ``*_from_store``
helpers.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

import aiofiles
import anyio
from claude_agent_sdk import (
    SessionKey,
    SessionListSubkeysKey,
    SessionStore,
    SessionStoreEntry,
    SessionStoreListEntry,
    project_key_for_directory,
)

PROJECTS_DIRECTORY = Path.home() / ".xalling" / "projects"


class DiskSessionStore(SessionStore):
    """Persist Claude session-store entries as JSONL files on disk.

    The layout mirrors ``InMemorySessionStore``'s composite key::

        ~/.xalling/projects/<project_key>/<session_id>.jsonl
        ~/.xalling/projects/<project_key>/<session_id>/<subpath>.jsonl

    ``append`` and all reads are asynchronous.  ``anyio.Path`` is used for
    directory/stat operations and ``aiofiles`` for transcript contents.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else PROJECTS_DIRECTORY
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()
        self._project_directories: dict[str, Path] = {}

    def register_project_directory(self, directory: Path | str) -> str:
        """Remember the real project path represented by a store key.

        ``SessionStore`` keys intentionally contain only a sanitized project
        key.  Keeping this reverse mapping lets the history API call the
        SDK's store helpers with the original project directory and restore
        the same ``cwd`` metadata as the native disk implementation.
        """
        project_directory = Path(directory).resolve()
        project_key = project_key_for_directory(project_directory)
        self._project_directories[project_key] = project_directory
        return project_key

    async def append(
        self,
        key: SessionKey,
        entries: list[SessionStoreEntry],
    ) -> None:
        """Append a batch of SDK transcript entries to its JSONL file."""
        if not entries:
            return
        path = self._path_for_key(key)
        lock = await self._lock_for(path)
        async with lock:
            await anyio.Path(path.parent).mkdir(parents=True, exist_ok=True)
            project_directory = self._project_directories.get(key["project_key"])
            if project_directory is None:
                project_directory = _cwd_from_entries(entries)
                if project_directory is not None:
                    self._project_directories[key["project_key"]] = project_directory
            if project_directory is not None:
                await self._write_project_directory(
                    key["project_key"],
                    project_directory,
                )
            async with aiofiles.open(path, mode="a", encoding="utf-8") as file:
                for entry in entries:
                    await file.write(
                        json.dumps(
                            entry,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    )
                    await file.write("\n")
                await file.flush()

    async def load(self, key: SessionKey) -> list[SessionStoreEntry] | None:
        """Load all JSON objects from one session-store key."""
        path = self._path_for_key(key)
        try:
            async with aiofiles.open(path, mode="r", encoding="utf-8") as file:
                content = await file.read()
        except FileNotFoundError:
            return None
        except OSError:
            return None

        entries: list[SessionStoreEntry] = []
        for line in content.splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
        return entries or None

    async def list_sessions(self, project_key: str) -> list[SessionStoreListEntry]:
        """List main transcript files for one project key."""
        project_directory = anyio.Path(self.root / self._safe_component(project_key))
        try:
            entries = [entry async for entry in project_directory.iterdir()]
        except OSError:
            return []

        sessions: list[SessionStoreListEntry] = []
        for entry in entries:
            if entry.suffix != ".jsonl":
                continue
            try:
                stat = await entry.stat()
            except OSError:
                continue
            sessions.append(
                {
                    "session_id": entry.stem,
                    "mtime": stat.st_mtime_ns // 1_000_000,
                }
            )
        return sessions

    async def list_subkeys(self, key: SessionListSubkeysKey) -> list[str]:
        """List subagent paths below one parent session."""
        session_directory = anyio.Path(
            self.root
            / self._safe_component(key["project_key"])
            / self._safe_component(key["session_id"])
        )
        try:
            candidates = [file async for file in session_directory.rglob("*.jsonl")]
        except OSError:
            return []

        subkeys: list[str] = []
        for file in candidates:
            if not await file.is_file():
                continue
            relative = file.relative_to(session_directory)
            subkeys.append(relative.with_suffix("").as_posix())
        return sorted(subkeys)

    async def delete(self, key: SessionKey) -> None:
        """Delete one key, cascading subkeys for a main transcript."""
        path = anyio.Path(self._path_for_key(key))
        if key.get("subpath"):
            try:
                await path.unlink()
            except FileNotFoundError:
                return
            return

        try:
            await path.unlink()
        except FileNotFoundError:
            pass

        session_directory = path.with_suffix("")
        try:
            files = [file async for file in session_directory.rglob("*")]
        except OSError:
            return
        for file in sorted(files, key=lambda item: len(item.parts), reverse=True):
            try:
                if await file.is_file():
                    await file.unlink()
                elif await file.is_dir():
                    await file.rmdir()
            except FileNotFoundError:
                continue

    async def list_project_directories(self) -> list[Path]:
        """Return original project directories with persisted sessions."""
        root = anyio.Path(self.root)
        try:
            entries = [entry async for entry in root.iterdir()]
        except OSError:
            return []

        directories: list[Path] = []
        for entry in entries:
            if not await entry.is_dir():
                continue
            project_key = entry.name
            project_directory = self._project_directories.get(project_key)
            if project_directory is None:
                project_directory = await self._read_project_directory(project_key)
            if project_directory is not None:
                self._project_directories[project_key] = project_directory
                directories.append(project_directory)
        return sorted(set(directories), key=os.fspath)

    async def find_session_directory(self, session_id: str) -> Path | None:
        """Find the project directory containing a main session transcript."""
        for project_directory in await self.list_project_directories():
            project_key = project_key_for_directory(project_directory)
            candidate = anyio.Path(
                self.root / self._safe_component(project_key) / f"{session_id}.jsonl"
            )
            try:
                if await candidate.is_file():
                    return project_directory
            except OSError:
                continue
        return None

    async def _lock_for(self, path: Path) -> asyncio.Lock:
        lock_key = os.fspath(path)
        async with self._locks_guard:
            return self._locks.setdefault(lock_key, asyncio.Lock())

    async def _write_project_directory(
        self,
        project_key: str,
        directory: Path,
    ) -> None:
        marker = self.root / self._safe_component(project_key) / ".directory"
        async with aiofiles.open(marker, mode="w", encoding="utf-8") as file:
            await file.write(os.fspath(directory))

    async def _read_project_directory(self, project_key: str) -> Path | None:
        marker = anyio.Path(
            self.root / self._safe_component(project_key) / ".directory"
        )
        try:
            value = (await marker.read_text(encoding="utf-8")).strip()
        except (OSError, UnicodeError):
            return None
        return Path(value).resolve() if value else None

    def _path_for_key(self, key: SessionKey) -> Path:
        project_key = self._safe_component(key["project_key"])
        session_id = self._safe_component(key["session_id"])
        subpath = key.get("subpath")
        if not subpath:
            return self.root / project_key / f"{session_id}.jsonl"

        safe_subpath = self._safe_subpath(subpath)
        return self.root / project_key / session_id / f"{safe_subpath}.jsonl"

    @staticmethod
    def _safe_component(value: str) -> str:
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("session-store key contains an unsafe path component")
        return value

    @classmethod
    def _safe_subpath(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("session-store subpath is unsafe")
        return "/".join(cls._safe_component(part) for part in path.parts)


session_store = DiskSessionStore()

__all__ = ["PROJECTS_DIRECTORY", "DiskSessionStore", "session_store"]


def _cwd_from_entries(entries: Iterable[SessionStoreEntry]) -> Path | None:
    """Extract a transcript cwd when the SDK mirror includes one."""
    for entry in entries:
        cwd = entry.get("cwd")
        if isinstance(cwd, str) and cwd:
            return Path(cwd).resolve()
    return None
