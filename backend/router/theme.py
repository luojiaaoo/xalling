"""Theme routes; blocking configuration I/O runs in FastAPI's thread pool."""

from fastapi import APIRouter, Depends

from backend.router.dependencies import authenticate
from backend.router.schemas import ThemeRequest
from backend.service.theme import ThemeService

router = APIRouter(prefix="/api/theme", tags=["theme"], dependencies=[Depends(authenticate)])


@router.get("")
def get_current_theme() -> str:
    return ThemeService.get_current_theme()


@router.put("")
def set_current_theme(body: ThemeRequest) -> None:
    ThemeService.set_current_theme(body.name)
