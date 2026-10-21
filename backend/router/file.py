"""Project file search and attachment persistence routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.router.dependencies import authenticate
from backend.router.schemas import AttachmentRequest, DirectoryListingResponse, ProjectFolderResponse
from backend.service.file import FileService

router = APIRouter(prefix="/api/files", tags=["files"], dependencies=[Depends(authenticate)])


@router.get("/roots")
def list_root_directories() -> list[ProjectFolderResponse]:
    return [ProjectFolderResponse.model_validate(folder) for folder in FileService.list_root_directories()]


@router.get("/directories")
def list_directories(
    path: Annotated[str | None, Query(min_length=1, max_length=32768)] = None,
) -> DirectoryListingResponse:
    return DirectoryListingResponse.model_validate(FileService.list_directories(path))


@router.get("/search")
def search_project_files(
    project_path: Annotated[str, Query(min_length=1, max_length=32768)],
    query: Annotated[str, Query(max_length=1000)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[dict[str, object]]:
    return FileService.search_project_files(project_path, query, limit)


@router.post("/attachments")
def save_attachment(body: AttachmentRequest) -> dict[str, str]:
    return FileService.save_attachment(body.filename, body.data)
