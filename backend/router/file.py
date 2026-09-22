"""Project file methods exposed to the local Web UI."""

from backend.service.file import DEFAULT_LIMIT, FileService


class FileRouter:
    """Search files inside the project and persist UI attachments."""

    def save_attachment(self, filename: str, data: str) -> dict[str, str]:
        """Save one attachment and return its on-disk absolute path."""
        return FileService.save_attachment(filename, data)

    def search_project_files(
        self,
        project_path: str,
        query: str,
        limit: int = DEFAULT_LIMIT,
    ) -> list[dict[str, object]]:
        """Return project entries whose name or relative path matches the query."""
        return FileService.search_project_files(project_path, query, limit)
