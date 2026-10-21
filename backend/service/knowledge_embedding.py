"""为正文片段和查询生成本地向量，供知识库混合检索使用。"""

from __future__ import annotations

import math
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from fastembed import TextEmbedding

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
MODEL_REPOSITORY = "Qdrant/bge-small-zh-v1.5"
MODEL_FILES = (
    "model_optimized.onnx",
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "vocab.txt",
)
DIMENSIONS = 512
_MODELS: dict[Path, TextEmbedding] = {}
_EMBEDDING_LOCK = RLock()
_STATE_LOCK = RLock()
_DOWNLOADING: set[Path] = set()
_ERRORS: dict[Path, str] = {}
MISSING_MODEL_MESSAGE = "知识库嵌入模型未下载或文件不完整，请打开“本地知识库”，手动点击“下载嵌入模型”后再使用。"


class EmbeddingError(Exception):
    """本地嵌入模型不可用或返回无效向量。"""


class EmbeddingStatus(BaseModel):
    """模型准备状态；查询状态不会加载模型或访问网络。"""

    status: Literal["missing", "downloading", "ready", "error"]
    model: str = MODEL_NAME
    directory: str
    message: str


def _model_directory(root: Path) -> Path:
    return root.expanduser().resolve() / "embedding"


def _files_ready(directory: Path) -> bool:
    try:
        return (directory / ".ready").read_text(encoding="utf-8") == MODEL_NAME and all(
            (directory / name).is_file() and (directory / name).stat().st_size > 0 for name in MODEL_FILES
        )
    except (OSError, UnicodeError):
        return False


def get_embedding_status(root: Path) -> EmbeddingStatus:
    directory = _model_directory(root)
    with _STATE_LOCK:
        if directory in _DOWNLOADING:
            status, message = "downloading", "正在下载并验证嵌入模型，完成后即可使用知识库。"
        elif directory in _ERRORS:
            status, message = "error", _ERRORS[directory]
        elif _files_ready(directory):
            status, message = "ready", "嵌入模型已就绪，可离线使用知识库。"
        else:
            status, message = "missing", MISSING_MODEL_MESSAGE
        return EmbeddingStatus(status=status, directory=str(directory), message=message)


def ensure_embedding_model(root: Path) -> None:
    """仅检查本地文件，绝不触发下载。"""
    state = get_embedding_status(root)
    if state.status != "ready":
        raise EmbeddingError(state.message)


def _load_model(directory: Path) -> TextEmbedding:
    from fastembed import TextEmbedding

    return TextEmbedding(
        model_name=MODEL_NAME,
        cache_dir=str(directory),
        specific_model_path=str(directory),
        local_files_only=True,
        threads=2,
    )


def download_embedding_model(root: Path) -> EmbeddingStatus:
    """仅供用户点击下载时调用，同一目录的并发请求共用一次下载。"""
    directory = _model_directory(root)
    with _STATE_LOCK:
        state = get_embedding_status(root)
        if state.status in {"ready", "downloading"}:
            return state
        retry = state.status == "error"
        _DOWNLOADING.add(directory)
        _ERRORS.pop(directory, None)
    try:
        from huggingface_hub import snapshot_download

        with _EMBEDDING_LOCK:
            _MODELS.pop(directory, None)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".ready").unlink(missing_ok=True)
        snapshot_download(
            repo_id=MODEL_REPOSITORY,
            local_dir=directory,
            allow_patterns=list(MODEL_FILES),
            max_workers=2,
            etag_timeout=15,
            force_download=retry,
        )
        if not all((directory / name).is_file() and (directory / name).stat().st_size > 0 for name in MODEL_FILES):
            raise ValueError("Incomplete model files")
        with _EMBEDDING_LOCK:
            model = _load_model(directory)
            # 成功加载 ONNX 和分词器后才发布就绪标记。
            (directory / ".ready").write_text(MODEL_NAME, encoding="utf-8")
            _MODELS[directory] = model
    except Exception as error:
        message = "嵌入模型下载或验证失败，请检查网络、磁盘空间和目录权限，再手动点击“下载嵌入模型”重试。"
        with _STATE_LOCK:
            _ERRORS[directory] = message
        raise EmbeddingError(message) from error
    finally:
        with _STATE_LOCK:
            _DOWNLOADING.discard(directory)
    return get_embedding_status(root)


def embed_texts(root: Path, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
    """分段嵌入并归一化聚合，避免长片段的后半部分被模型截断。"""
    if not texts:
        return []
    ensure_embedding_model(root)
    with _EMBEDDING_LOCK:
        ensure_embedding_model(root)
        try:
            directory = _model_directory(root)
            if directory not in _MODELS:
                _MODELS[directory] = _load_model(directory)
            model = _MODELS[directory]
            segments = []
            counts = []
            for text in texts:
                parts = [text[start : start + 400] for start in range(0, len(text), 400)]
                if not parts:
                    raise ValueError("Empty embedding input")
                counts.append(len(parts))
                segments.extend(parts)
            output = model.query_embed(segments) if is_query else model.passage_embed(segments, batch_size=16)
            vectors = [vector.tolist() for vector in output]
            if len(vectors) != len(segments) or any(
                len(vector) != DIMENSIONS or not all(math.isfinite(value) for value in vector) for vector in vectors
            ):
                raise ValueError("Invalid embedding output")
            result = []
            offset = 0
            for count in counts:
                vector = [math.fsum(item[n] for item in vectors[offset : offset + count]) for n in range(DIMENSIONS)]
                norm = math.sqrt(math.fsum(value * value for value in vector))
                if norm == 0 or not math.isfinite(norm):
                    raise ValueError("Invalid embedding norm")
                result.append([value / norm for value in vector])
                offset += count
            return result
        except Exception as error:
            message = "本地嵌入模型加载或计算失败，请打开“本地知识库”，手动点击“下载嵌入模型”重新下载。"
            with _STATE_LOCK:
                _ERRORS[directory] = message
                try:
                    (directory / ".ready").unlink(missing_ok=True)
                except OSError:
                    pass  # 目录不可写时仍返回可展示的错误。
            _MODELS.pop(directory, None)
            raise EmbeddingError(message) from error
