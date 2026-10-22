"""Async tests use the same backend as Uvicorn and Claude SDK."""

import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def knowledge_vectors(monkeypatch):
    """知识库集成测试使用确定性向量，仍执行真实 Zvec 混合查询。"""
    import hashlib
    import math
    import re

    from backend.service.knowledge import store as knowledge
    from backend.service.knowledge.chunking import chunk_text, index_chunk_options
    from backend.service.knowledge.embedding import DIMENSIONS, MAX_INPUT_TOKENS

    def embed(root, texts, *, is_query=False):
        result = []
        for text in texts:
            vector = [0.0] * DIMENSIONS
            for word in re.findall(r"\w+", text.casefold()):
                index = int.from_bytes(hashlib.sha256(word.encode()).digest()[:2]) % DIMENSIONS
                vector[index] += 1.0
            norm = math.sqrt(sum(value * value for value in vector))
            result.append([value / (norm or 1.0) for value in vector])
        return result

    monkeypatch.setattr(knowledge, "embed_texts", embed)
    monkeypatch.setattr(knowledge, "ensure_embedding_model", lambda root: None)

    def split(root, text, *, markdown=False):
        max_chars, overlap_chars = index_chunk_options(MAX_INPUT_TOKENS, text)
        return chunk_text(text, markdown=markdown, max_chars=max_chars, overlap_chars=overlap_chars)

    monkeypatch.setattr(knowledge, "split_document", split)
