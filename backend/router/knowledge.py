"""知识库路径展示、文档移除和手动下载嵌入模型接口。"""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.router.dependencies import authenticate
from backend.router.schemas import KnowledgeDeleteRequest
from backend.service.knowledge.embedding import (
    EmbeddingError,
    EmbeddingStatus,
    download_embedding_model,
    get_embedding_status,
)
from backend.service.knowledge.store import KnowledgeError, KnowledgeStore

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"], dependencies=[Depends(authenticate)])


def get_store() -> KnowledgeStore:
    return KnowledgeStore()


StoreDep = Annotated[KnowledgeStore, Depends(get_store)]


def checked(action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return action(*args, **kwargs)
    except (KnowledgeError, EmbeddingError) as error:
        raise HTTPException(400, str(error)) from error


@router.get("/embedding")
def embedding_status(store: StoreDep) -> EmbeddingStatus:
    return get_embedding_status(store.root)


@router.post("/embedding/download")
def download_embedding(store: StoreDep) -> EmbeddingStatus:
    return checked(download_embedding_model, store.root)


@router.get("/tree")
def path_tree(store: StoreDep) -> dict[str, Any]:
    return checked(store.path_tree)


@router.delete("/documents")
def delete_documents(request: KnowledgeDeleteRequest, store: StoreDep) -> dict[str, int]:
    return checked(store.delete_documents, request.sources)


@router.get("/documents")
def list_documents(
    store: StoreDep,
    parent_path: Annotated[str | None, Query(min_length=1, max_length=4096)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    filename: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
) -> dict[str, Any]:
    return checked(store.list_files, offset, limit, parent_path=parent_path, filename=filename)
