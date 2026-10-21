"""为正文片段和查询生成本地向量，供知识库混合检索使用。"""

from __future__ import annotations

import math
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastembed import TextEmbedding

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
DIMENSIONS = 512
_MODELS: dict[Path, TextEmbedding] = {}
_EMBEDDING_LOCK = RLock()


class EmbeddingError(Exception):
    """本地嵌入模型不可用或返回无效向量。"""


def embed_texts(root: Path, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
    """分段嵌入并归一化聚合，避免长片段的后半部分被模型截断。"""
    if not texts:
        return []
    with _EMBEDDING_LOCK:
        try:
            from fastembed import TextEmbedding

            directory = root.parent / "xalling-embedding-models"
            if directory not in _MODELS:
                _MODELS[directory] = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(directory), threads=2)
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
            raise EmbeddingError("本地嵌入模型下载、加载或计算失败，请检查网络及模型缓存后重试。") from error
