import math

import pytest

from backend.service import knowledge_embedding
from backend.service.knowledge_embedding import DIMENSIONS, EmbeddingError, embed_texts


class Vector(list):
    def tolist(self):
        return list(self)


@pytest.fixture
def model(monkeypatch):
    import fastembed

    class Model:
        def __init__(self):
            self.calls = []

        def passage_embed(self, texts, **kwargs):
            self.calls.append(("passage", texts))
            return [Vector([float("甲" in text), float("乙" in text)] + [0.0] * (DIMENSIONS - 2)) for text in texts]

        def query_embed(self, texts):
            self.calls.append(("query", texts))
            return [Vector([1.0] + [0.0] * (DIMENSIONS - 1)) for text in texts]

    instance = Model()
    initialized = []

    def create(**kwargs):
        initialized.append(kwargs)
        return instance

    monkeypatch.setattr(knowledge_embedding, "_MODELS", {})
    monkeypatch.setattr(fastembed, "TextEmbedding", create)
    return instance, initialized


def test_long_passages_include_tail_and_query_uses_distinct_embedding(tmp_path, model):
    instance, initialized = model
    root = tmp_path / "storage"
    vectors = embed_texts(root, ["甲" * 400 + "乙" * 400, "乙"])
    assert len(vectors) == 2
    assert vectors[0][:2] == pytest.approx([1 / math.sqrt(2), 1 / math.sqrt(2)])
    assert vectors[1][:2] == [0.0, 1.0]
    assert embed_texts(root, ["问题"], is_query=True)[0][0] == 1.0
    assert [kind for kind, _ in instance.calls] == ["passage", "query"]
    assert len(initialized) == 1
    assert initialized[0]["cache_dir"] == str(tmp_path / "xalling-embedding-models")


@pytest.mark.parametrize("invalid", [[], [[1.0]], [[0.0] * DIMENSIONS], [[float("nan")] * DIMENSIONS]])
def test_incomplete_or_invalid_model_output_is_rejected(tmp_path, model, monkeypatch, invalid):
    instance, _ = model
    monkeypatch.setattr(instance, "passage_embed", lambda *a, **kw: [Vector(values) for values in invalid])
    with pytest.raises(EmbeddingError, match="模型下载、加载或计算失败"):
        embed_texts(tmp_path, ["测试"])


def test_empty_input_skips_model_loading_and_download_failure_is_actionable(tmp_path, model, monkeypatch):
    _, initialized = model
    assert embed_texts(tmp_path, []) == []
    assert not initialized

    def fail(*args, **kwargs):
        raise OSError("private-download-details")

    import fastembed

    monkeypatch.setattr(fastembed, "TextEmbedding", fail)
    with pytest.raises(EmbeddingError, match="网络及模型缓存") as error:
        embed_texts(tmp_path, ["测试"])
    assert "private-download-details" not in str(error.value)
