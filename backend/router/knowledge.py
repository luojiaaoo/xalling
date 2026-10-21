"""知识库只读路径展示接口，导入及检索由智能体工具完成。"""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.router.dependencies import authenticate
from backend.service.knowledge import KnowledgeError, KnowledgeStore

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"], dependencies=[Depends(authenticate)])


def get_store() -> KnowledgeStore:
    return KnowledgeStore()


StoreDep = Annotated[KnowledgeStore, Depends(get_store)]


def checked(action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return action(*args, **kwargs)
    except KnowledgeError as error:
        raise HTTPException(400, str(error)) from error


@router.get("/tree")
def path_tree(store: StoreDep) -> dict[str, Any]:
    return checked(store.path_tree)


@router.get("/documents")
def list_documents(
    store: StoreDep,
    parent_path: Annotated[str | None, Query(min_length=1, max_length=4096)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    filename: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
) -> dict[str, Any]:
    return checked(store.list_files, offset, limit, parent_path=parent_path, filename=filename)
