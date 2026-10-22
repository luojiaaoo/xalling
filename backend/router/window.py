"""Native desktop controls exposed through FastAPI."""

from fastapi import APIRouter, BackgroundTasks, Depends

from backend.router.dependencies import WindowDep, authenticate
from backend.router.schemas import ResizeRequest
from backend.service.desktop.window import WindowService

router = APIRouter(prefix="/api/window", tags=["window"], dependencies=[Depends(authenticate)])


@router.get("/capabilities")
def get_window_capabilities(window: WindowDep) -> dict[str, bool]:
    return window.get_capabilities()


@router.post("/minimize")
def minimize_window(window: WindowDep) -> None:
    window.minimize()


@router.post("/maximize")
def toggle_maximize_window(window: WindowDep) -> dict[str, bool]:
    return window.toggle_maximize()


@router.post("/close")
def close_window(window: WindowDep, background_tasks: BackgroundTasks) -> dict[str, bool]:
    background_tasks.add_task(window.close)
    return {"closing": True}


@router.post("/resize")
def resize_window(body: ResizeRequest, window: WindowDep) -> None:
    window.resize(body.width, body.height, body.edge)


@router.get("/home-folder")
def get_home_folder() -> dict[str, str]:
    return WindowService.get_home_folder()
