"""Frontend error reporting route."""

from fastapi import APIRouter, Depends

from backend.router.dependencies import authenticate
from backend.router.schemas import FrontendErrorRequest
from backend.service.desktop.log import LogService

router = APIRouter(prefix="/api/logs", tags=["logs"], dependencies=[Depends(authenticate)])


@router.post("/frontend")
def report_frontend_error(body: FrontendErrorRequest) -> None:
    LogService.report_frontend_error(body.kind, body.message, body.stack)
