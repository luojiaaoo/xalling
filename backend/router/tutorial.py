"""Tutorial markdown documents exposed to the local Web UI."""

import re
from pathlib import Path
from typing import TypedDict

# 教程目录：项目根目录下的 tutorials/，仅向界面暴露其中的 Markdown 文件
TUTORIALS_DIR = Path(__file__).resolve().parents[2] / "tutorials"

_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


class TutorialSummary(TypedDict):
    """教程列表项：id 即文件名，标题取自文件首个一级标题。"""

    id: str
    title: str


class TutorialDocument(TutorialSummary):
    """完整教程文档，content 为 Markdown 原文。"""

    content: str


def _tutorial_files() -> list[Path]:
    """List tutorial markdown files in stable name order."""
    if not TUTORIALS_DIR.is_dir():
        return []
    return sorted(
        (path for path in TUTORIALS_DIR.iterdir() if path.is_file() and path.suffix.lower() == ".md"),
        key=lambda path: path.name,
    )


def _extract_title(path: Path, content: str) -> str:
    """取首个一级标题作为教程标题，没有标题时回退为文件名。"""
    match = _HEADING_RE.search(content)
    return match.group(1) if match else path.stem


class TutorialRouter:
    """Read local tutorial markdown files for the help menu."""

    def list_tutorials(self) -> list[TutorialSummary]:
        """Return tutorial entries for the title-bar help menu."""
        tutorials: list[TutorialSummary] = []
        for path in _tutorial_files():
            content = path.read_text(encoding="utf-8")
            tutorials.append({"id": path.name, "title": _extract_title(path, content)})
        return tutorials

    def get_tutorial(self, tutorial_id: str) -> TutorialDocument:
        """Return one tutorial's markdown content, looked up by file name."""
        if not isinstance(tutorial_id, str):
            raise TypeError("教程 id 必须是字符串")
        # 只匹配目录内实际存在的文件名，天然杜绝路径穿越
        for path in _tutorial_files():
            if path.name == tutorial_id:
                content = path.read_text(encoding="utf-8")
                return {
                    "id": path.name,
                    "title": _extract_title(path, content),
                    "content": content,
                }
        raise ValueError("教程不存在")
