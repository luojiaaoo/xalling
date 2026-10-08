"""Project file search and attachment persistence routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.router.dependencies import authenticate
from backend.router.schemas import AttachmentRequest
from backend.service.file import FileService
from backend.service.log import capture_api_errors

router = APIRouter(prefix="/api/files", tags=["files"], dependencies=[Depends(authenticate)])


@router.get("/search")
@capture_api_errors
def search_project_files(
    project_path: Annotated[str, Query(min_length=1, max_length=32768)],
    query: Annotated[str, Query(max_length=1000)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[dict[str, object]]:
    return FileService.search_project_files(project_path, query, limit)


@router.post("/attachments")
@capture_api_errors
def save_attachment(body: AttachmentRequest) -> dict[str, str]:
    return FileService.save_attachment(body.filename, body.data)
