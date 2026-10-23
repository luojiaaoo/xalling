"""为正文片段和查询生成本地向量，供知识库混合检索使用。"""

from __future__ import annotations

import json
import math
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from backend.service.knowledge.chunking import chunk_text, index_chunk_options
from backend.service.knowledge.text_files import TEXT_WHITESPACE, utf8_text

if TYPE_CHECKING:
    from fastembed import TextEmbedding
    from modelscope.hub.callback import ProgressCallback

MODEL_NAME = "ibm-granite/granite-embedding-311m-multilingual-r2"
# 魔搭（ModelScope）仓库，国内网络可直接下载。
MODEL_REPOSITORY = MODEL_NAME
MODEL_FILES = (
    "onnx/model_quint8_avx2.onnx",
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
)
DIMENSIONS = 768
MAX_INPUT_TOKENS = 8192  # 原生最大 32768，限制分块预算以避免知识块过大。
_MODELS: dict[Path, TextEmbedding] = {}
_EMBEDDING_LOCK = RLock()
_STATE_LOCK = RLock()
_DOWNLOADING: set[Path] = set()
_ERRORS: dict[Path, str] = {}
_PROGRESS: dict[Path, EmbeddingDownloadProgress] = {}
MISSING_MODEL_MESSAGE = "知识库嵌入模型未下载或文件不完整，请打开“本地知识库”，手动点击“下载嵌入模型”后再使用。"


class EmbeddingError(Exception):
    """本地嵌入模型不可用或返回无效向量。"""


class EmbeddingDownloadProgress(BaseModel):
    """下载回调提供的字节进度；所有文件大小已知后才返回总大小。"""

    phase: Literal["preparing", "downloading", "validating"] = "preparing"
    downloaded_bytes: int = Field(default=0, ge=0)
    total_bytes: int | None = Field(default=None, ge=1)
    completed_files: int = Field(default=0, ge=0, le=len(MODEL_FILES))
    total_files: int = len(MODEL_FILES)


class EmbeddingStatus(BaseModel):
    """模型准备状态；查询状态不会加载模型或访问网络。"""

    status: Literal["missing", "downloading", "ready", "error"]
    model: str = MODEL_NAME
    directory: str
    message: str
    progress: EmbeddingDownloadProgress | None = None


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
            progress = _PROGRESS.get(directory)
            status = "downloading"
            message = (
                "文件下载完成，正在验证并加载嵌入模型。"
                if progress and progress.phase == "validating"
                else "正在下载嵌入模型，完成后将验证模型文件。"
            )
        elif directory in _ERRORS:
            status, message = "error", _ERRORS[directory]
        elif _files_ready(directory):
            status, message = "ready", "嵌入模型已就绪，可离线使用知识库。"
        else:
            status, message = "missing", MISSING_MODEL_MESSAGE
        return EmbeddingStatus(
            status=status,
            directory=str(directory),
            message=message,
            progress=_PROGRESS.get(directory) if status == "downloading" else None,
        )


def _download_callback(directory: Path) -> type[ProgressCallback]:
    from modelscope.hub.callback import ProgressCallback

    files: dict[str, tuple[int, int]] = {}
    completed: set[str] = set()

    def publish() -> None:
        # 调用方持有状态锁；不同文件和分片下载可能在多个线程回调。
        if directory not in _DOWNLOADING:
            return
        total = sum(size for _, size in files.values())
        all_sizes_known = set(files) == set(MODEL_FILES) and all(size > 0 for _, size in files.values())
        _PROGRESS[directory] = EmbeddingDownloadProgress(
            phase="downloading",
            downloaded_bytes=sum(downloaded for downloaded, _ in files.values()),
            total_bytes=total if all_sizes_known else None,
            completed_files=len(completed),
        )

    class DownloadCallback(ProgressCallback):
        def __init__(self, filename: str, file_size: int):
            super().__init__(filename, file_size)
            with _STATE_LOCK:
                files[filename] = (0, max(0, file_size))
                publish()

        def update(self, size: int) -> None:
            with _STATE_LOCK:
                downloaded, total = files[self.filename]
                downloaded = max(0, downloaded + size)
                files[self.filename] = (min(downloaded, total) if total else downloaded, total)
                publish()

        def end(self) -> None:
            with _STATE_LOCK:
                downloaded, total = files[self.filename]
                files[self.filename] = (total or downloaded, total)
                completed.add(self.filename)
                publish()

    return DownloadCallback


def ensure_embedding_model(root: Path) -> None:
    """仅检查本地文件，绝不触发下载。"""
    state = get_embedding_status(root)
    if state.status != "ready":
        raise EmbeddingError(state.message)


def _load_model(directory: Path) -> TextEmbedding:
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType

    # tokenizer_config.json 有特殊符号，FastEmbed 0.7 用系统默认编码读取这些 JSON；转义非 ASCII 字符兼容 Windows GBK。
    for name in ("config.json", "tokenizer_config.json", "special_tokens_map.json"):
        path = directory / name
        content = path.read_text(encoding="utf-8")
        if not content.isascii():
            path.write_text(json.dumps(json.loads(content), ensure_ascii=True), encoding="utf-8")

    if not any(model["model"] == MODEL_NAME for model in TextEmbedding.list_supported_models()):
        TextEmbedding.add_custom_model(
            model=MODEL_NAME,
            pooling=PoolingType.CLS,
            normalization=True,
            sources=ModelSource(hf=MODEL_NAME),
            dim=DIMENSIONS,
            model_file=MODEL_FILES[0],
        )

    return TextEmbedding(
        model_name=MODEL_NAME,
        cache_dir=str(directory),
        specific_model_path=str(directory),
        local_files_only=True,
        threads=2,
        providers=["CPUExecutionProvider"],
    )


def _invalidate_model(directory: Path, message: str) -> None:
    """在持有嵌入锁时撤销就绪状态，使用户能手动重新下载损坏的模型。"""
    with _STATE_LOCK:
        _ERRORS[directory] = message
        try:
            (directory / ".ready").unlink(missing_ok=True)
        except OSError:
            pass  # 目录不可写时仍返回可展示的错误。
    _MODELS.pop(directory, None)


def split_document(root: Path, text: str, *, markdown: bool = False) -> list[str]:
    """与 zvec-grep 一致，按模型预算和文本密度配置字符切片。"""
    ensure_embedding_model(root)
    max_chars, overlap_chars = index_chunk_options(MAX_INPUT_TOKENS, text)
    return chunk_text(text, markdown=markdown, max_chars=max_chars, overlap_chars=overlap_chars)


def download_embedding_model(root: Path) -> EmbeddingStatus:
    """仅供用户点击下载时调用，同一目录的并发请求共用一次下载。"""
    directory = _model_directory(root)
    with _STATE_LOCK:
        state = get_embedding_status(root)
        if state.status in {"ready", "downloading"}:
            return state
        _DOWNLOADING.add(directory)
        _ERRORS.pop(directory, None)
        _PROGRESS[directory] = EmbeddingDownloadProgress()
    try:
        from modelscope.hub import snapshot_download

        with _EMBEDDING_LOCK:
            _MODELS.pop(directory, None)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".ready").unlink(missing_ok=True)
        # 先清掉可能残留的不完整文件，确保重试时真正重新下载。
        for name in MODEL_FILES:
            (directory / name).unlink(missing_ok=True)
        snapshot_download(
            model_id=MODEL_REPOSITORY,
            local_dir=directory,
            allow_patterns=list(MODEL_FILES),
            max_workers=2,
            progress_callbacks=[_download_callback(directory)],
        )
        if not all((directory / name).is_file() and (directory / name).stat().st_size > 0 for name in MODEL_FILES):
            raise ValueError("Incomplete model files")
        with _STATE_LOCK:
            total = sum((directory / name).stat().st_size for name in MODEL_FILES)
            _PROGRESS[directory] = EmbeddingDownloadProgress(
                phase="validating", downloaded_bytes=total, total_bytes=total, completed_files=len(MODEL_FILES)
            )
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
            _PROGRESS.pop(directory, None)
    return get_embedding_status(root)


def embed_texts(root: Path, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
    """每片生成一个归一化向量，超长模型输入由 FastEmbed 分词器截断。"""
    if not texts:
        return []
    ensure_embedding_model(root)
    with _EMBEDDING_LOCK:
        ensure_embedding_model(root)
        directory = _model_directory(root)
        try:
            if any(not text.strip(TEXT_WHITESPACE) for text in texts):
                raise EmbeddingError("嵌入文本不能为空。")
            texts = [utf8_text(text) for text in texts]
            if directory not in _MODELS:
                _MODELS[directory] = _load_model(directory)
            model = _MODELS[directory]
            # 此量化模型的输出受同批其他文本影响，逐条计算以保持向量一致。
            output = model.query_embed(texts, batch_size=1) if is_query else model.passage_embed(texts, batch_size=4)
            vectors = [vector.tolist() for vector in output]
            if len(vectors) != len(texts) or any(
                len(vector) != DIMENSIONS or not all(math.isfinite(value) for value in vector) for vector in vectors
            ):
                raise ValueError("Invalid embedding output")
            result = []
            for vector in vectors:
                norm = math.sqrt(math.fsum(value * value for value in vector))
                if norm == 0 or not math.isfinite(norm):
                    raise ValueError("Invalid embedding norm")
                result.append([value / norm for value in vector])
            return result
        except EmbeddingError:
            raise
        except Exception as error:
            message = "本地嵌入模型加载或计算失败，请打开“本地知识库”，手动点击“下载嵌入模型”重新下载。"
            _invalidate_model(directory, message)
            raise EmbeddingError(message) from error
