"""Claude command and skill routes using the application chat dependency."""

from fastapi import APIRouter, Depends

from backend.router.dependencies import ChatDep, authenticate
from backend.router.schemas import ChatConnectionRequest
from backend.service.command import ClaudeCommand, CommandService
from backend.service.log import capture_api_errors

router = APIRouter(prefix="/api/commands", tags=["commands"], dependencies=[Depends(authenticate)])


@router.post("/list")
@capture_api_errors
async def get_commands(body: ChatConnectionRequest, chat: ChatDep) -> list[ClaudeCommand]:
    return CommandService.get_commands(await chat.get_chat_server_info(**body.model_dump()))


@router.get("/allowed")
@capture_api_errors
def get_allowed_command_names() -> list[str]:
    return CommandService.get_allowed_command_names()


@router.post("/skills")
@capture_api_errors
async def get_skills(body: ChatConnectionRequest, chat: ChatDep) -> list[ClaudeCommand]:
    return CommandService.get_skills(await chat.get_chat_server_info(**body.model_dump()))
