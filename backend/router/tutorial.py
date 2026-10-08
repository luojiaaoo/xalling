"""Local tutorial routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from backend.router.dependencies import authenticate
from backend.service.log import capture_api_errors
from backend.service.tutorial import TutorialDocument, TutorialService, TutorialSummary

router = APIRouter(prefix="/api/tutorials", tags=["tutorials"], dependencies=[Depends(authenticate)])


@router.get("")
@capture_api_errors
def list_tutorials() -> list[TutorialSummary]:
    return TutorialService.list_tutorials()


@router.get("/{tutorial_id}")
@capture_api_errors
def get_tutorial(tutorial_id: Annotated[str, Path(min_length=1, max_length=255)]) -> TutorialDocument:
    return TutorialService.get_tutorial(tutorial_id)
