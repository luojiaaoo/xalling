from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

import backend.service.file as file_service
from backend.service.file import FileService


def test_directory_browser_lists_only_immediate_folders(tmp_path: Path) -> None:
    for name in ["中文项目", "beta", "Alpha", ".agents"]:
        (tmp_path / name).mkdir()
    (tmp_path / "Alpha" / "nested").mkdir()
    (tmp_path / "file.txt").write_text("file", encoding="utf-8")
    result = FileService.list_directories(str(tmp_path))
    assert result["current"] == {"name": tmp_path.name, "path": str(tmp_path.resolve())}
    assert result["parent_path"] == str(tmp_path.resolve().parent)
    assert [folder["name"] for folder in result["directories"]] == [".agents", "Alpha", "beta", "中文项目"]
    assert all(Path(folder["path"]).is_absolute() for folder in result["directories"])


def test_directory_browser_uses_linux_root_and_posix_navigation(monkeypatch: pytest.MonkeyPatch) -> None:
    filesystem = {"/": ["etc", "var", "home"], "/etc": ["xalling"], "/etc/xalling": [], "/var": [], "/home": []}

    class LinuxDirectory(PurePosixPath):
        def expanduser(self):
            return self

        def resolve(self, strict=True):
            if str(self) not in filesystem:
                raise FileNotFoundError(str(self))
            return self

        def is_dir(self):
            return str(self) in filesystem

        def iterdir(self):
            return iter(self / name for name in filesystem[str(self)])

    monkeypatch.setattr(file_service, "Path", LinuxDirectory)
    monkeypatch.setattr(file_service, "os", SimpleNamespace(name="posix"))
    root = FileService.list_directories("/")
    assert root["current"] == {"name": "/", "path": "/"}
    assert root["parent_path"] is None
    assert [folder["path"] for folder in root["directories"]] == ["/etc", "/home", "/var"]
    assert [folder["path"] for folder in FileService.list_root_directories()] == ["/", "/etc", "/home", "/var"]
    etc = FileService.list_directories("/etc")
    assert etc["parent_path"] == "/"
    assert etc["directories"] == [{"name": "xalling", "path": "/etc/xalling"}]
    assert FileService.list_directories("/var")["directories"] == []
    with pytest.raises(ValueError, match="绝对"):
        FileService.list_directories("C:\\projects")


@pytest.mark.skipif(file_service.os.name != "nt", reason="Windows drive paths")
def test_directory_browser_lists_windows_drives(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_service, "os", SimpleNamespace(name="nt", listdrives=lambda: ["C:\\", "D:\\"]))
    assert FileService.list_root_directories() == [{"name": "C:\\", "path": "C:\\"}, {"name": "D:\\", "path": "D:\\"}]


def test_directory_browser_defaults_to_backend_project_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.service.file.default_project_folder", lambda: tmp_path)
    assert FileService.list_directories()["current"]["path"] == str(tmp_path.resolve())
    assert FileService.list_directories(str(tmp_path))["directories"] == []


def test_directory_browser_root_has_no_parent(tmp_path: Path) -> None:
    assert FileService.list_directories(tmp_path.anchor)["parent_path"] is None


@pytest.mark.parametrize("path", ["relative/project", "", "missing"])
def test_directory_browser_rejects_relative_paths(path: str) -> None:
    with pytest.raises(ValueError, match="绝对"):
        FileService.list_directories(path)


def test_directory_browser_rejects_files_and_missing_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="不存在"):
        FileService.list_directories(str(tmp_path / "missing"))
    file = tmp_path / "file.txt"
    file.touch()
    with pytest.raises(ValueError, match="必须是文件夹"):
        FileService.list_directories(str(file))


def test_directory_browser_handles_unreadable_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unreadable(_path: Path):
        raise PermissionError("private filesystem information")

    monkeypatch.setattr(Path, "iterdir", unreadable)
    with pytest.raises(ValueError, match="访问权限") as error:
        FileService.list_directories(str(tmp_path))
    assert "private" not in str(error.value)


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    client_dir = tmp_path / "backend" / "claude_chat_client"
    client_dir.mkdir(parents=True)
    (client_dir / "models.py").write_text("# models", encoding="utf-8")
    (tmp_path / "backend" / "router").mkdir()
    ignored = tmp_path / "node_modules" / "junk"
    ignored.mkdir(parents=True)
    (ignored / "trace_fake.py").write_text("# ignored", encoding="utf-8")
    return tmp_path


def test_file_router_searches_files_and_folders(project: Path) -> None:
    router = FileService()

    files = router.search_project_files(str(project), "models")
    assert [item["name"] for item in files] == ["models.py"]
    assert files[0]["path"] == "backend/claude_chat_client/models.py"
    assert files[0]["relative"] == "backend/claude_chat_client/models.py"
    assert files[0]["is_dir"] is False

    folders = router.search_project_files(str(project), "router")
    assert [item["name"] for item in folders] == ["router"]
    assert folders[0]["path"] == "backend/router/"
    assert folders[0]["relative"] == "backend/router"
    assert folders[0]["is_dir"] is True


def test_file_router_skips_ignored_directories(project: Path) -> None:
    router = FileService()

    results = router.search_project_files(str(project), "trace_fake")
    assert results == []


def test_file_router_lists_top_level_entries_for_empty_query(project: Path) -> None:
    (project / "README.md").write_text("# demo", encoding="utf-8")
    router = FileService()

    results = router.search_project_files(str(project), "")
    names = [item["name"] for item in results]
    assert names == ["backend", "README.md"]
    assert "node_modules" not in names


def test_file_router_rejects_missing_project(tmp_path: Path) -> None:
    router = FileService()

    with pytest.raises(ValueError, match="项目文件夹不存在"):
        router.search_project_files(str(tmp_path / "missing"), "trace")
