"""Theme routes; blocking configuration I/O runs in FastAPI's thread pool."""

from fastapi import APIRouter, Depends

from backend.router.dependencies import authenticate
from backend.router.schemas import ThemeRequest
from backend.service.log import capture_api_errors
from backend.service.theme import ThemeService

router = APIRouter(prefix="/api/theme", tags=["theme"], dependencies=[Depends(authenticate)])


@router.get("")
@capture_api_errors
def get_current_theme() -> str:
    return ThemeService.get_current_theme()


@router.put("")
@capture_api_errors
def set_current_theme(body: ThemeRequest) -> None:
    ThemeService.set_current_theme(body.name)
