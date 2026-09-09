from pathlib import Path

import pytest

from backend.router import FileRouter


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    chat_dir = tmp_path / "backend" / "chat"
    chat_dir.mkdir(parents=True)
    (chat_dir / "trace.py").write_text("# trace", encoding="utf-8")
    (tmp_path / "backend" / "router").mkdir()
    ignored = tmp_path / "node_modules" / "junk"
    ignored.mkdir(parents=True)
    (ignored / "trace_fake.py").write_text("# ignored", encoding="utf-8")
    return tmp_path


def test_file_router_searches_files_and_folders(project: Path) -> None:
    router = FileRouter()

    files = router.search_project_files(str(project), "trace")
    assert [item["name"] for item in files] == ["trace.py"]
    assert files[0]["path"] == (project / "backend" / "chat" / "trace.py").as_posix()
    assert files[0]["relative"] == "backend/chat/trace.py"
    assert files[0]["is_dir"] is False

    folders = router.search_project_files(str(project), "router")
    assert [item["name"] for item in folders] == ["router"]
    assert folders[0]["path"].endswith("backend/router/")
    assert folders[0]["is_dir"] is True


def test_file_router_skips_ignored_directories(project: Path) -> None:
    router = FileRouter()

    results = router.search_project_files(str(project), "trace_fake")
    assert results == []


def test_file_router_lists_top_level_entries_for_empty_query(project: Path) -> None:
    (project / "README.md").write_text("# demo", encoding="utf-8")
    router = FileRouter()

    results = router.search_project_files(str(project), "")
    names = [item["name"] for item in results]
    assert names == ["backend", "README.md"]
    assert "node_modules" not in names


def test_file_router_rejects_missing_project(tmp_path: Path) -> None:
    router = FileRouter()

    with pytest.raises(ValueError, match="项目文件夹不存在"):
        router.search_project_files(str(tmp_path / "missing"), "trace")
