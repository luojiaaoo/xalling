"""Model configuration routes with typed JSON inputs."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.router.dependencies import authenticate
from backend.router.schemas import ModelSelectionRequest, ModelSiteRequest, RemoteModelsRequest
from backend.service.settings.model import ModelGroup, ModelSelection, ModelService, ModelSiteView

router = APIRouter(prefix="/api/models", tags=["models"], dependencies=[Depends(authenticate)])


@router.get("/groups")
async def get_model_groups() -> list[ModelGroup]:
    return await ModelService.get_model_groups()


@router.get("/sites")
async def get_model_sites() -> list[ModelSiteView]:
    return await ModelService.get_model_sites()


@router.post("/remote-names")
async def fetch_model_names(body: RemoteModelsRequest) -> list[str]:
    return await ModelService.fetch_model_names(body.api_url, body.api_key)


@router.put("/sites")
async def save_model_site(body: ModelSiteRequest) -> None:
    await ModelService.save_model_site(
        body.original_name,
        body.name,
        body.api_url,
        body.api_key,
        [model.model_dump() for model in body.models],
        body.api_protocol,
    )


@router.delete("/sites")
async def delete_model_site(name: Annotated[str, Query(min_length=1, max_length=200)]) -> None:
    await ModelService.delete_model_site(name)


@router.get("/current")
async def get_current_model() -> ModelSelection | None:
    return await ModelService.get_current_model()


@router.put("/current")
async def set_current_model(body: ModelSelectionRequest) -> None:
    await ModelService.set_current_model(body.site, body.model)
