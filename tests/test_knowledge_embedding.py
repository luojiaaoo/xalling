import json
import math
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from backend.service.knowledge import embedding as knowledge_embedding
from backend.service.knowledge.embedding import (
    DIMENSIONS,
    MAX_INPUT_TOKENS,
    MODEL_FILES,
    MODEL_NAME,
    EmbeddingError,
    download_embedding_model,
    embed_texts,
    get_embedding_status,
    split_document,
)
from backend.service.knowledge.store import KnowledgeError, KnowledgeStore


def write_model_files(root, *, ready=True):
    directory = root / "embedding"
    directory.mkdir(parents=True, exist_ok=True)
    for name in MODEL_FILES:
        (directory / name).parent.mkdir(parents=True, exist_ok=True)
        (directory / name).write_bytes(b"model-data")
    if ready:
        (directory / ".ready").write_text(MODEL_NAME, encoding="utf-8")
    return directory


class Vector(list):
    def tolist(self):
        return list(self)


@pytest.fixture
def model(monkeypatch):
    import fastembed

    class Model:
        def __init__(self):
            self.calls = []
            self.batch_sizes = []

        def passage_embed(self, texts, **kwargs):
            self.calls.append(("passage", texts))
            self.batch_sizes.append(kwargs["batch_size"])
            return [Vector([float("甲" in text), float("乙" in text)] + [0.0] * (DIMENSIONS - 2)) for text in texts]

        def query_embed(self, texts, **kwargs):
            self.calls.append(("query", texts))
            self.batch_sizes.append(kwargs["batch_size"])
            return [Vector([1.0] + [0.0] * (DIMENSIONS - 1)) for text in texts]

    instance = Model()
    initialized = []

    class Factory:
        @staticmethod
        def list_supported_models():
            return [{"model": MODEL_NAME}]

        def __new__(cls, **kwargs):
            initialized.append(kwargs)
            return instance

    monkeypatch.setattr(knowledge_embedding, "_MODELS", {})
    monkeypatch.setattr(fastembed, "TextEmbedding", Factory)
    return instance, initialized


def test_each_passage_is_embedded_whole_and_query_uses_distinct_embedding(tmp_path, model):
    instance, initialized = model
    root = tmp_path / "storage"
    directory = write_model_files(root)
    texts = ["甲" * 200 + "乙" * 200, "乙"]
    vectors = embed_texts(root, texts)
    assert len(vectors) == 2
    assert vectors[0][:2] == pytest.approx([1 / math.sqrt(2), 1 / math.sqrt(2)])
    assert vectors[1][:2] == [0.0, 1.0]
    assert embed_texts(root, ["问题"], is_query=True)[0][0] == 1.0
    assert [kind for kind, _ in instance.calls] == ["passage", "query"]
    assert instance.calls[0][1] == texts
    assert instance.batch_sizes == [4, 1]
    assert len(initialized) == 1
    assert initialized[0]["cache_dir"] == str(directory)
    assert initialized[0]["specific_model_path"] == str(directory)
    assert initialized[0]["local_files_only"] is True
    assert initialized[0]["providers"] == ["CPUExecutionProvider"]


def test_custom_granite_registration_is_reused_across_model_directories(tmp_path, monkeypatch):
    import fastembed
    from fastembed.common.model_description import PoolingType

    registered, registrations, initialized = [], [], []

    class Factory:
        @staticmethod
        def list_supported_models():
            return registered

        @staticmethod
        def add_custom_model(**kwargs):
            registrations.append(kwargs)
            registered.append({"model": kwargs["model"]})

        def __new__(cls, **kwargs):
            initialized.append(kwargs)
            return object()

    monkeypatch.setattr(fastembed, "TextEmbedding", Factory)
    directories = [write_model_files(tmp_path / name) for name in ("first", "second")]
    for directory in directories:
        knowledge_embedding._load_model(directory)
    assert len(registrations) == 1
    config = registrations[0]
    assert config["model"] == MODEL_NAME
    assert config["pooling"] == PoolingType.CLS
    assert config["normalization"] is True
    assert config["dim"] == 768
    assert config["model_file"] == "onnx/model_quint8_avx2.onnx"
    assert config["sources"].hf == MODEL_NAME
    assert [item["specific_model_path"] for item in initialized] == list(map(str, directories))
    assert all(item["local_files_only"] for item in initialized)


def test_model_configs_remain_readable_with_windows_gbk_encoding(tmp_path, model):
    directory = write_model_files(tmp_path)
    payload = {"token": "多语言配置🧠", "values": [1, True, None]}
    configs = ("config.json", "tokenizer_config.json", "special_tokens_map.json")
    for name in configs:
        (directory / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tokenizer_before = (directory / "tokenizer.json").read_bytes()

    knowledge_embedding._load_model(directory)

    for name in configs:
        assert json.loads((directory / name).read_text(encoding="gbk")) == payload
    assert (directory / "tokenizer.json").read_bytes() == tokenizer_before
    assert get_embedding_status(tmp_path).status == "ready"


def test_long_document_is_split_before_embedding_without_vector_pooling(tmp_path, model):
    instance, _ = model
    write_model_files(tmp_path)
    text = "甲" * 24000 + "乙" * 24000
    chunks = split_document(tmp_path, text)
    assert "".join(chunks) == text
    assert len(chunks) == 2
    assert [len(chunk) for chunk in chunks] == [32768, 15232]
    vectors = embed_texts(tmp_path, chunks)
    assert len(vectors) == len(chunks)
    assert instance.calls == [("passage", chunks)]
    assert vectors[-1][:2] == [0.0, 1.0]


@pytest.mark.parametrize("is_query", [False, True])
@pytest.mark.parametrize("text", ["", "  ", "\ufeff"])
def test_invalid_input_does_not_invalidate_model_or_invoke_inference(tmp_path, model, text, is_query):
    instance, initialized = model
    write_model_files(tmp_path)
    with pytest.raises(EmbeddingError, match="不能为空"):
        embed_texts(tmp_path, [text], is_query=is_query)
    assert get_embedding_status(tmp_path).status == "ready"
    assert not instance.calls
    assert not initialized


def test_long_query_is_passed_to_backend_for_model_truncation(tmp_path, model):
    instance, _ = model
    write_model_files(tmp_path)
    text = "甲" * 1000
    assert len(embed_texts(tmp_path, [text], is_query=True)) == 1
    assert instance.calls == [("query", [text])]


@pytest.mark.parametrize(
    "text,expected_lengths",
    [
        ("甲" * 2000, [2000]),
        ("甲" * 70000, [32768, 32768, 4464]),
        ("a" * 130000, [60620, 60620, 8760]),
    ],
    ids=["short-dense", "full-dense-budget", "full-ascii-budget"],
)
def test_chunking_uses_full_model_and_density_budget_without_loading_tokenizer(tmp_path, text, expected_lengths):
    write_model_files(tmp_path)
    assert MAX_INPUT_TOKENS == 32768
    chunks = split_document(tmp_path, text)
    assert "".join(chunks) == text
    assert [len(chunk) for chunk in chunks] == expected_lengths


@pytest.mark.parametrize("invalid", [[], [[1.0]], [[0.0] * DIMENSIONS], [[float("nan")] * DIMENSIONS]])
def test_incomplete_or_invalid_model_output_is_rejected(tmp_path, model, monkeypatch, invalid):
    instance, _ = model
    write_model_files(tmp_path)
    monkeypatch.setattr(instance, "passage_embed", lambda *a, **kw: [Vector(values) for values in invalid])
    with pytest.raises(EmbeddingError, match="模型加载或计算失败"):
        embed_texts(tmp_path, ["测试"])
    assert get_embedding_status(tmp_path).status == "error"


def test_empty_input_skips_model_loading_and_load_failure_requires_manual_download(tmp_path, model, monkeypatch):
    _, initialized = model
    assert embed_texts(tmp_path, []) == []
    assert not initialized
    write_model_files(tmp_path)

    def fail(*args, **kwargs):
        raise OSError("private-download-details")

    import fastembed

    monkeypatch.setattr(fastembed, "TextEmbedding", fail)
    with pytest.raises(EmbeddingError, match="手动点击") as error:
        embed_texts(tmp_path, ["测试"])
    assert "private-download-details" not in str(error.value)


def test_missing_model_never_initializes_or_downloads(tmp_path, model, monkeypatch):
    import modelscope.hub as modelscope_hub

    monkeypatch.setattr(modelscope_hub, "snapshot_download", lambda **kwargs: pytest.fail("不得自动下载模型"))
    root = tmp_path / "storage"
    assert get_embedding_status(root).status == "missing"
    with pytest.raises(EmbeddingError, match="手动点击“下载嵌入模型”"):
        embed_texts(root, ["问题"])
    assert model[1] == []
    assert not root.exists()


@pytest.mark.parametrize("missing", [".ready", *MODEL_FILES])
def test_partial_model_is_unavailable_even_if_already_loaded(tmp_path, model, missing):
    directory = write_model_files(tmp_path)
    embed_texts(tmp_path, ["甲"])
    (directory / missing).unlink()
    with pytest.raises(EmbeddingError, match="手动点击"):
        embed_texts(tmp_path, ["问题"])


def test_manual_download_validates_files_and_subsequent_loads_are_local(tmp_path, model, monkeypatch):
    import modelscope.hub as modelscope_hub

    downloads = []

    def download(**kwargs):
        downloads.append(kwargs)
        assert get_embedding_status(tmp_path).status == "downloading"
        with pytest.raises(EmbeddingError, match="正在下载"):
            embed_texts(tmp_path, ["甲"])
        write_model_files(tmp_path, ready=False)

    monkeypatch.setattr(modelscope_hub, "snapshot_download", download)
    state = download_embedding_model(tmp_path)
    assert state.status == "ready"
    assert state.directory == str(tmp_path / "embedding")
    assert downloads[0]["local_dir"] == tmp_path / "embedding"
    assert set(downloads[0]["allow_patterns"]) == set(MODEL_FILES)
    assert model[1][0]["local_files_only"] is True
    # 模拟重启后从磁盘加载，不再访问下载服务。
    knowledge_embedding._MODELS.clear()
    assert embed_texts(tmp_path, ["甲"])[0][0] == 1.0
    assert download_embedding_model(tmp_path).status == "ready"
    assert len(downloads) == 1


@pytest.mark.parametrize("failure", ["network", "incomplete", "load"])
def test_download_failure_is_sanitized_and_retryable(tmp_path, model, monkeypatch, failure):
    import modelscope.hub as modelscope_hub

    def fail(**kwargs):
        if failure == "network":
            raise OSError("private-network-error")
        if failure == "incomplete":
            (tmp_path / "embedding" / MODEL_FILES[-1]).write_bytes(b"partial")
        else:
            write_model_files(tmp_path, ready=False)

    with monkeypatch.context() as patch:
        patch.setattr(modelscope_hub, "snapshot_download", fail)
        if failure == "load":
            patch.setattr(knowledge_embedding, "_load_model", lambda path: (_ for _ in ()).throw(ValueError("invalid")))
        with pytest.raises(EmbeddingError, match="手动点击") as error:
            download_embedding_model(tmp_path)
    assert "private-network-error" not in str(error.value)
    assert get_embedding_status(tmp_path).status == "error"
    assert not (tmp_path / "embedding" / ".ready").exists()
    with pytest.raises(EmbeddingError, match="手动点击"):
        embed_texts(tmp_path, ["甲"])
    monkeypatch.setattr(modelscope_hub, "snapshot_download", lambda **kwargs: write_model_files(tmp_path, ready=False))
    assert download_embedding_model(tmp_path).status == "ready"


def test_concurrent_downloads_share_one_transfer_and_status_stays_responsive(tmp_path, model, monkeypatch):
    import modelscope.hub as modelscope_hub

    entered, release = Event(), Event()
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        entered.set()
        assert release.wait(5)
        write_model_files(tmp_path, ready=False)

    monkeypatch.setattr(modelscope_hub, "snapshot_download", download)
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(download_embedding_model, tmp_path)
        try:
            assert entered.wait(5)
            assert get_embedding_status(tmp_path).status == "downloading"
            assert download_embedding_model(tmp_path).status == "downloading"
        finally:
            release.set()
        assert pending.result().status == "ready"
    assert len(calls) == 1


@pytest.mark.parametrize("operation", ["import", "search", "list", "tree"])
def test_knowledge_entry_points_require_model_before_reading_or_mutating(tmp_path, operation):
    store = KnowledgeStore(tmp_path / "storage")
    actions = {
        "import": lambda: store.import_document(str(tmp_path / "absent.txt")),
        "search": lambda: store.search("问题", 5),
        "list": lambda: store.list_files(0, 10),
        "tree": store.path_tree,
    }
    with pytest.raises(KnowledgeError, match="手动点击“下载嵌入模型”"):
        actions[operation]()
    assert not store.root.exists()
