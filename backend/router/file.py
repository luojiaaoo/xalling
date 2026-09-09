"""Project file search methods exposed to the local Web UI."""

import os
from pathlib import Path

IGNORED_DIR_NAMES = frozenset({
    ".git",
    ".hg",
    ".idea",
    ".svn",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
})
MAX_SCANNED_ENTRIES = 20000
DEFAULT_LIMIT = 30


class FileRouter:
    """Search files and folders inside the selected project folder."""

    def search_project_files(
        self,
        project_path: str,
        query: str,
        limit: int = DEFAULT_LIMIT,
    ) -> list[dict[str, object]]:
        """Return project entries whose name or relative path matches the query."""
        if not isinstance(project_path, str) or not isinstance(query, str):
            raise TypeError("项目路径和搜索词必须是字符串")
        if type(limit) is not int:
            raise TypeError("结果数量必须是整数")

        root = Path(project_path).resolve()
        if not root.is_dir():
            raise ValueError("项目文件夹不存在")

        limit = max(1, min(limit, 100))
        normalized_query = query.strip().lower()
        if not normalized_query:
            return self._list_top_level(root, limit)
        return self._search(root, normalized_query, limit)

    def _list_top_level(self, root: Path, limit: int) -> list[dict[str, object]]:
        entries = sorted(
            (
                entry for entry in root.iterdir()
                if not entry.name.startswith(".") and entry.name not in IGNORED_DIR_NAMES
            ),
            key=lambda entry: (not entry.is_dir(), entry.name.lower()),
        )
        return [self._describe(root, entry) for entry in entries[:limit]]

    def _search(
        self,
        root: Path,
        query: str,
        limit: int,
    ) -> list[dict[str, object]]:
        scored: list[tuple[int, str, dict[str, object]]] = []
        scanned = 0
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                name for name in dirnames
                if name not in IGNORED_DIR_NAMES and not name.startswith(".")
            ]
            for name in (*dirnames, *filenames):
                scanned += 1
                if scanned > MAX_SCANNED_ENTRIES:
                    break
                entry = Path(dirpath) / name
                relative = entry.relative_to(root).as_posix()
                lowered_name = name.lower()
                if lowered_name.startswith(query):
                    score = 0
                elif query in lowered_name:
                    score = 1
                elif query in relative.lower():
                    score = 2
                else:
                    continue
                scored.append((score, relative, self._describe(root, entry)))
            if scanned > MAX_SCANNED_ENTRIES:
                break

        scored.sort(key=lambda item: (item[0], item[1].count("/"), item[1]))
        return [item[2] for item in scored[:limit]]

    @staticmethod
    def _describe(root: Path, entry: Path) -> dict[str, object]:
        is_dir = entry.is_dir()
        path = entry.as_posix()
        if is_dir and not path.endswith("/"):
            path = f"{path}/"
        return {
            "name": entry.name,
            "path": path,
            "relative": entry.relative_to(root).as_posix(),
            "is_dir": is_dir,
        }
