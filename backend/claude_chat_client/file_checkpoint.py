"""Discover and restore SDK-owned checkpoints without local persistence."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from uuid import UUID, uuid4

import asyncer
from claude_agent_sdk import ClaudeSDKError
from loguru import logger

from .history import ClaudeChatHistory
from .models import ChatEvent, FileRestoreResult, FileRewindPreview

Preview = Callable[[str], Awaitable[FileRewindPreview]]


class FileCheckpointManager:
    """Use public history UUIDs and the CLI's read-only rewind preview."""

    def __init__(self, history: ClaudeChatHistory | None = None) -> None:
        self._history = history or ClaudeChatHistory()

    @staticmethod
    def candidates(session_id: str, events: Iterable[ChatEvent]) -> dict[str, ChatEvent]:
        """Accept only this session's top-level human messages or live checkpoints."""
        candidates = {}
        for event in events:
            if event.parent_tool_use_id is not None or event.session_id not in {None, session_id}:
                continue
            if event.event == "user.message":
                identifier = event.data.get("message_uuid")
            elif event.event == "files.checkpoint":
                identifier = event.data.get("checkpoint_id")
            else:
                continue
            try:
                checkpoint_id = str(UUID(str(identifier)))
            except ValueError:
                continue
            candidates.setdefault(checkpoint_id, event)
        return candidates

    async def project_history(
        self, session_id: str, events: tuple[ChatEvent, ...], preview: Preview,
    ) -> list[ChatEvent]:
        """Append verified checkpoints after replay, without fabricating turn diffs."""
        projected = list(events)
        try:
            # A missing/older CLI or a slow preview must not prevent reading history.
            async with asyncio.timeout(15):
                for checkpoint_id, source in self.candidates(session_id, events).items():
                    result = await preview(checkpoint_id)
                    if result.can_restore:
                        projected.append(ChatEvent(
                            id=f"checkpoint:{checkpoint_id}", event="files.checkpoint",
                            turn_id=source.turn_id, session_id=session_id,
                            created_at=source.created_at,
                            data={"checkpoint_id": checkpoint_id, "preview": result.to_dict()},
                        ))
        except (ClaudeSDKError, RuntimeError, TimeoutError, ValueError):
            logger.exception("Could not finish querying SDK file checkpoints")
        return projected

    async def _source(
        self, session_id: str, project: Path, checkpoint_id: str, events: tuple[ChatEvent, ...],
    ) -> ChatEvent:
        """Resolve live and historical checkpoint ownership behind the same API."""
        source = self.candidates(session_id, events).get(checkpoint_id)
        if source is None:
            snapshot = await asyncer.asyncify(self._history.get_session)(session_id)
            if (snapshot.session.session_id != session_id or snapshot.session.cwd is None
                    or Path(snapshot.session.cwd).resolve() != project.resolve()):
                raise ValueError("文件检查点所属工作区与当前会话不一致")
            source = self.candidates(session_id, snapshot.events).get(checkpoint_id)
        if source is None:
            raise ValueError("此消息不属于当前会话的文件检查点，无法恢复")
        return source

    async def preview_files(
        self, session_id: str, project: Path, checkpoint_id: str, events: tuple[ChatEvent, ...], preview: Preview,
    ) -> FileRewindPreview:
        """Return the same read-only preview for live and historical checkpoints."""
        checkpoint_id = str(UUID(checkpoint_id))
        await self._source(session_id, project, checkpoint_id, events)
        return await preview(checkpoint_id)

    async def rewind_files(
        self,
        session_id: str,
        project: Path,
        checkpoint_id: str,
        events: tuple[ChatEvent, ...],
        preview: Preview,
        rewind: Callable[[str], Awaitable[None]],
        *,
        timeout: float = 30,
    ) -> FileRestoreResult:
        """Validate session ownership and SDK availability before changing files."""
        checkpoint_id = str(UUID(checkpoint_id))
        source = await self._source(session_id, project, checkpoint_id, events)
        result = await preview(checkpoint_id)
        if not result.can_restore:
            raise ValueError("SDK 中已不存在此文件检查点，无法恢复")
        await asyncio.wait_for(rewind(checkpoint_id), timeout=timeout)
        return FileRestoreResult(event=ChatEvent(
            id=f"restore:{uuid4()}", event="files.restored", turn_id=source.turn_id,
            session_id=session_id, data={"checkpoint_id": checkpoint_id},
        ))
