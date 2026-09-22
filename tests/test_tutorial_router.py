"""Tests for the tutorial markdown router."""

from pathlib import Path

import pytest

from backend.service import tutorial
from backend.router.tutorial import TutorialRouter


@pytest.fixture()
def tutorials_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the router at an isolated tutorials folder."""
    directory = tmp_path / "tutorials"
    directory.mkdir()
    monkeypatch.setattr(tutorial, "TUTORIALS_DIR", directory)
    return directory


def test_list_tutorials_uses_first_heading_as_title(tutorials_dir: Path) -> None:
    (tutorials_dir / "b.md").write_text("# 命令说明\n\n正文", encoding="utf-8")
    (tutorials_dir / "a.md").write_text("没有标题的内容", encoding="utf-8")

    summaries = TutorialRouter().list_tutorials()

    # 按文件名排序；无一级标题时回退为文件名
    assert summaries == [
        {"id": "a.md", "title": "a"},
        {"id": "b.md", "title": "命令说明"},
    ]


def test_list_tutorials_ignores_non_markdown_and_missing_dir(tutorials_dir: Path) -> None:
    (tutorials_dir / "note.txt").write_text("# 不是教程", encoding="utf-8")
    assert TutorialRouter().list_tutorials() == []

    tutorial.TUTORIALS_DIR = tutorials_dir / "不存在"
    assert TutorialRouter().list_tutorials() == []


def test_get_tutorial_returns_content(tutorials_dir: Path) -> None:
    (tutorials_dir / "help.md").write_text("# 命令说明\n\n正文内容", encoding="utf-8")

    document = TutorialRouter().get_tutorial("help.md")

    assert document == {
        "id": "help.md",
        "title": "命令说明",
        "content": "# 命令说明\n\n正文内容",
    }


def test_get_tutorial_rejects_unknown_id(tutorials_dir: Path) -> None:
    (tutorials_dir / "help.md").write_text("# 标题", encoding="utf-8")

    with pytest.raises(ValueError, match="教程不存在"):
        TutorialRouter().get_tutorial("../help.md")
