"""Native FastAPI chat routes sharing one application-level ChatService."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query

from backend.router.dependencies import ChatDep, ServicesDep, authenticate
from backend.router.schemas import ChatConnectionRequest, ChatMessageRequest, PermissionDecisionRequest, SessionRequest
from backend.service.log import capture_api_errors

router = APIRouter(prefix="/api/chat", tags=["chat"], dependencies=[Depends(authenticate)])
SessionId = Annotated[str, Path(min_length=1, max_length=128)]


@router.post("/messages")
@capture_api_errors
async def send_chat_message(body: ChatMessageRequest, services: ServicesDep) -> dict[str, Any]:
    return await services.send_chat_message(**body.model_dump())


@router.get("/sessions")
@capture_api_errors
async def list_chat_sessions(chat: ChatDep) -> list[dict[str, Any]]:
    return await chat.list_chat_sessions()


@router.get("/search")
@capture_api_errors
async def search_chat_sessions(chat: ChatDep, query: Annotated[str, Query(max_length=1000)]) -> list[dict[str, Any]]:
    return await chat.search_chat_sessions(query)


@router.post("/history")
@capture_api_errors
async def get_chat_session(body: ChatConnectionRequest, chat: ChatDep) -> dict[str, Any]:
    return await chat.get_chat_session(**body.model_dump())


@router.get("/sessions/{session_id}/active")
@capture_api_errors
async def get_active_chat(
    session_id: SessionId, chat: ChatDep, include_completed: bool = False
) -> dict[str, object] | None:
    return chat.get_active_chat(session_id, include_completed)


@router.get("/sessions/{session_id}/context")
@capture_api_errors
async def get_context_usage(session_id: SessionId, chat: ChatDep) -> dict[str, Any] | None:
    return await chat.get_context_usage(session_id)


@router.post("/stop")
@capture_api_errors
async def stop_chat_message(body: SessionRequest, chat: ChatDep) -> bool:
    return await chat.stop_chat_message(body.session_id)


@router.post("/close")
@capture_api_errors
async def close_chat_client(body: SessionRequest, chat: ChatDep) -> bool:
    return await chat.close_chat_client(body.session_id)


@router.put("/permission-mode")
@capture_api_errors
async def set_chat_permission_mode(body: ChatConnectionRequest, chat: ChatDep) -> bool:
    return await chat.set_chat_permission_mode(**body.model_dump())


@router.post("/permissions")
@capture_api_errors
async def respond_chat_permission(body: PermissionDecisionRequest, chat: ChatDep) -> bool:
    return chat.respond_chat_permission(**body.model_dump())


@router.get("/scheduled-tasks")
@capture_api_errors
async def list_scheduled_tasks(
    chat: ChatDep, project_path: Annotated[str | None, Query(max_length=32768)] = None
) -> list[dict[str, Any]]:
    return await chat.list_scheduled_tasks(project_path)


@router.get("/all-scheduled-tasks")
@capture_api_errors
async def list_all_scheduled_tasks(chat: ChatDep) -> list[dict[str, Any]]:
    return await chat.list_all_scheduled_tasks()


@router.delete("/scheduled-tasks/{task_id}")
@capture_api_errors
async def delete_scheduled_task(
    chat: ChatDep,
    task_id: Annotated[str, Path(min_length=1, max_length=128)],
    project_path: Annotated[str | None, Query(max_length=32768)] = None,
) -> dict[str, Any]:
    return await chat.delete_scheduled_task(task_id, project_path)
