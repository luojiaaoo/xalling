"""Per-turn file changes from successful public SDK tool results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from difflib import unified_diff
from typing import Any

_MAX_CONTENT = 1_000_000
_MAX_PATCH = 200_000
_FILE_TOOLS = frozenset({"Write", "Edit", "NotebookEdit"})


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and len(value) <= _MAX_CONTENT and value.count("\n") <= 20_000 else None


def _unified(before: str, after: str, path: str, created: bool) -> str:
    lines = unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                         fromfile="/dev/null" if created else path, tofile=path)
    return "".join(line if line.endswith("\n") else f"{line}\n\\ No newline at end of file\n" for line in lines)


def _structured_patch(result: Mapping[str, Any], path: str) -> str:
    hunks = result.get("structuredPatch")
    if not isinstance(hunks, list):
        return ""
    parts = [f"--- {path}\n+++ {path}\n"]
    for hunk in hunks:
        if not isinstance(hunk, Mapping):
            continue
        coordinates = [hunk.get(key) for key in ("oldStart", "oldLines", "newStart", "newLines")]
        lines = hunk.get("lines")
        if not all(isinstance(value, int) and value >= 0 for value in coordinates) or not isinstance(lines, list):
            continue
        if not all(isinstance(line, str) for line in lines):
            continue
        parts.append(f"@@ -{coordinates[0]},{coordinates[1]} +{coordinates[2]},{coordinates[3]} @@\n")
        parts.extend(f"{line}\n" for line in lines)
    return "".join(parts) if len(parts) > 1 else ""


@dataclass(slots=True)
class _FileState:
    before: str | None
    after: str | None
    created: bool
    complete: bool
    restorable: bool
    patches: list[str]


class TurnFileChanges:
    """Compare the first successful edit's before state with the last after state.

    Unknown or discontinuous contents stay explicitly partial. Git's working
    tree and the current filesystem are never used as historical baselines.
    """

    def __init__(self) -> None:
        self.files: dict[str, _FileState] = {}
        self.seen_tools: set[str] = set()

    def apply(self, name: str, tool_input: Mapping[str, Any], result: Mapping[str, Any],
              tool_id: str, *, restorable: bool) -> bool:
        if name not in _FILE_TOOLS or tool_id in self.seen_tools:
            return False
        path = result.get("filePath") or tool_input.get("file_path") or tool_input.get("notebook_path")
        if not isinstance(path, str) or not path:
            return False
        self.seen_tools.add(tool_id)
        before = _text(result.get("originalFile"))
        created = name == "Write" and result.get("type") == "create"
        if created:
            before = ""
        after = None
        if name == "Write":
            after = _text(result.get("content"))
            if after is None and result.get("userModified") is not True:
                after = _text(tool_input.get("content"))
        elif name == "Edit" and before is not None:
            old = result.get("oldString", tool_input.get("old_string"))
            new = result.get("newString", tool_input.get("new_string"))
            accepted = result.get("userModified") is not True or "newString" in result
            if accepted and isinstance(old, str) and old and isinstance(new, str) and old in before:
                replace_all = result.get("replaceAll", tool_input.get("replace_all", False)) is True
                if replace_all or before.count(old) == 1:
                    after = _text(before.replace(old, new, -1 if replace_all else 1))
        fallback = _structured_patch(result, path)
        state = self.files.get(path)
        if state is None:
            state = _FileState(before, after, created, before is not None and after is not None,
                               restorable, [fallback] if fallback else [])
            self.files[path] = state
        else:
            # A change made outside these tools between two edits must not be
            # attributed to this conversation or silently folded into its diff.
            state.complete = state.complete and before == state.after and after is not None
            state.after = after
            state.restorable = state.restorable and restorable
            if fallback:
                state.patches.append(fallback)
        return True

    def snapshot(self) -> list[dict[str, Any]]:
        changes = []
        for path, state in self.files.items():
            if state.complete:
                if state.before == state.after and not state.created:
                    continue
                patch = _unified(state.before or "", state.after or "", path, state.created)
                body = patch.splitlines()[2:]
                additions = sum(line.startswith("+") for line in body)
                deletions = sum(line.startswith("-") for line in body)
            else:
                patch = "\n".join(state.patches)
                additions = deletions = None
            changes.append({"path": path, "status": "added" if state.created else "modified",
                            "additions": additions, "deletions": deletions,
                            "patch": patch[:_MAX_PATCH], "truncated": len(patch) > _MAX_PATCH,
                            "partial": not state.complete, "restorable": state.restorable})
        return changes
