"""Persist confirmed checkpoints and turn diffs without inspecting SDK files."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import asyncer
from loguru import logger
from pydantic import BaseModel, Field

from .models import ChatEvent, FileRestoreResult


class FileCheckpoint(BaseModel):
    checkpoint_id: str
    turn_id: str
    event_id: str
    created_at: str
    restored_at: str | None = None
    restore_event_id: str | None = None

    def events(self, session_id: str, turn_id: str | None = None) -> list[ChatEvent]:
        event = ChatEvent(
            id=self.event_id,
            event="files.checkpoint",
            turn_id=turn_id or self.turn_id,
            session_id=session_id,
            created_at=self.created_at,
            data={"checkpoint_id": self.checkpoint_id},
        )
        events = [event]
        if self.restored_at and self.restore_event_id:
            events.append(replace(event, id=self.restore_event_id, event="files.restored", created_at=self.restored_at))
        return events


class StoredFileChanges(BaseModel):
    event_id: str
    created_at: str
    files: list[dict[str, object]]

    def event(self, session_id: str, turn_id: str) -> ChatEvent:
        return ChatEvent(id=self.event_id, event="files.changed", turn_id=turn_id,
                         session_id=session_id, created_at=self.created_at, data={"files": self.files})


class SessionCheckpoints(BaseModel):
    project_path: str
    checkpoints: dict[str, FileCheckpoint] = Field(default_factory=dict)
    file_changes: dict[str, StoredFileChanges] = Field(default_factory=dict)


class FileCheckpointStore:
    """Synchronous local metadata I/O, called through the application's thread pool."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    async def record_event(self, session_id: str, project: Path, event: ChatEvent) -> bool:
        """Persist checkpoint events before publishing an available restore action.

        Diff snapshots may still be delivered when persistence fails; a failed
        checkpoint save must not advertise a restore action we cannot own.
        """
        if event.event not in {"files.checkpoint", "files.changed"}:
            return True
        record = self.record if event.event == "files.checkpoint" else self.record_changes
        try:
            await asyncer.asyncify(record)(session_id, project, event)
        except (OSError, ValueError):
            logger.exception("Could not persist the file checkpoint event")
            return event.event != "files.checkpoint"
        return True

    async def rewind_files(
        self,
        session_id: str,
        project: Path,
        checkpoint_id: str,
        rewind: Callable[[str], Awaitable[None]],
        *,
        timeout: float = 30,
    ) -> FileRestoreResult:
        """Validate ownership, restore via the client and create its public event."""
        checkpoint_id = str(UUID(checkpoint_id))
        record = await asyncer.asyncify(self.load)(session_id, project)
        checkpoint = record.checkpoints.get(checkpoint_id)
        if checkpoint is None:
            raise ValueError("此消息没有已记录的文件检查点，无法恢复")
        await asyncio.wait_for(rewind(checkpoint_id), timeout=timeout)
        restored = ChatEvent(
            id=f"restore:{uuid4()}", event="files.restored", turn_id=checkpoint.turn_id,
            session_id=session_id, data={"checkpoint_id": checkpoint_id},
        )
        metadata_saved = True
        try:
            await asyncer.asyncify(self.restore)(session_id, project, restored)
        except OSError:
            logger.exception("File restoration succeeded but checkpoint metadata could not be saved")
            metadata_saved = False
        return FileRestoreResult(event=restored, metadata_saved=metadata_saved)

    def _path(self, session_id: str) -> Path:
        return self.directory / f"{UUID(session_id)}.json"

    def load(self, session_id: str, project: Path) -> SessionCheckpoints:
        path = self._path(session_id)
        if not path.exists():
            return SessionCheckpoints(project_path=str(project.resolve()))
        record = SessionCheckpoints.model_validate_json(path.read_text(encoding="utf-8"))
        if Path(record.project_path).resolve() != project.resolve():
            raise ValueError("文件检查点所属工作区与当前会话不一致")
        return record

    def save(self, session_id: str, record: SessionCheckpoints) -> None:
        path = self._path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{uuid4().hex}.tmp")
        try:
            temporary.write_text(record.model_dump_json(), encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def record(self, session_id: str, project: Path, event: ChatEvent) -> None:
        checkpoint_id = str(UUID(str(event.data["checkpoint_id"])))
        record = self.load(session_id, project)
        if checkpoint_id not in record.checkpoints:
            record.checkpoints[checkpoint_id] = FileCheckpoint(
                checkpoint_id=checkpoint_id,
                turn_id=event.turn_id,
                event_id=event.id,
                created_at=event.created_at,
            )
            self.save(session_id, record)

    def restore(self, session_id: str, project: Path, event: ChatEvent) -> None:
        record = self.load(session_id, project)
        checkpoint = record.checkpoints[str(event.data["checkpoint_id"])]
        checkpoint.restored_at = event.created_at
        checkpoint.restore_event_id = event.id
        self.save(session_id, record)

    def record_changes(self, session_id: str, project: Path, event: ChatEvent) -> None:
        record = self.load(session_id, project)
        turn_id = str(UUID(event.turn_id))
        record.file_changes[turn_id] = StoredFileChanges(
            event_id=event.id, created_at=event.created_at, files=event.data["files"],
        )
        self.save(session_id, record)

    def project_history(self, session_id: str, project: Path, events: tuple[ChatEvent, ...]) -> list[ChatEvent]:
        """Reattach saved checkpoints and final diffs to public history turns."""
        record = self.load(session_id, project)
        projected = []
        restored = []
        turn_sources: dict[str, str] = {}
        for event in events:
            if event.event == "files.changed" and turn_sources.get(event.turn_id) in record.file_changes:
                continue
            if event.event in {"turn.completed", "turn.failed"}:
                changes = record.file_changes.get(turn_sources.get(event.turn_id, ""))
                if changes:
                    projected.append(changes.event(session_id, event.turn_id))
            projected.append(event)
            if event.event != "user.message":
                continue
            source = str(event.data.get("message_uuid"))
            turn_sources[event.turn_id] = source
            checkpoint = record.checkpoints.get(source)
            if checkpoint:
                checkpoint_events = checkpoint.events(session_id, event.turn_id)
                projected.append(checkpoint_events[0])
                restored.extend(checkpoint_events[1:])
        return [*projected, *restored]
