"""共享离线文档索引，支持多个父目录范围或全局检索。"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import TYPE_CHECKING, Concatenate, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

from backend.config.setting import KNOWLEDGE_DIRECTORY
from backend.service.knowledge.embedding import (
    DIMENSIONS,
    EmbeddingError,
    embed_texts,
    ensure_embedding_model,
    split_document,
)
from backend.service.knowledge.text_files import TEXT_WHITESPACE, decode_text, detect_file_type, utf8_text

if TYPE_CHECKING:
    import zvec

MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_TEXT_CHARACTERS = 20_000_000
PREVIEW_EDGE_CHARACTERS = 500
# 所有会话共用集合；持锁直到句柄关闭，避免原生文件锁竞争。
_STORAGE_LOCK = RLock()


class KnowledgeError(Exception):
    """可直接展示给用户的知识库业务异常。"""


def requires_embedding_model[**P, R](
    action: Callable[Concatenate[KnowledgeStore, P], R],
) -> Callable[Concatenate[KnowledgeStore, P], R]:
    """所有知识库入口先检查本地模型，缺失时不读写清单、原文或向量索引。"""

    @wraps(action)
    def checked(store: KnowledgeStore, *args: P.args, **kwargs: P.kwargs) -> R:
        try:
            ensure_embedding_model(store.root)
        except EmbeddingError as error:
            raise KnowledgeError(str(error)) from error
        return action(store, *args, **kwargs)

    return checked


class DocumentRecord(BaseModel):
    """以源文件路径标识的文档元数据，也是重建向量索引的依据。"""

    # 忽略旧清单中已移除的元数据字段，避免仅删字段就需要重建索引。
    model_config = ConfigDict(extra="ignore", strict=True)

    source: str
    mtime_ns: int
    chunk_count: int = Field(ge=1)

    def chunk_id(self, chunck_number: int) -> str:
        """按源路径和编号生成固定长度的片段 ID，不包含修改时间。"""
        return uuid5(NAMESPACE_URL, f"{os.path.normcase(self.source)}:{chunck_number}").hex


class DocumentPreview(DocumentRecord):
    """已入库正文快照；短文全文放在 head，tail 为空。"""

    head: str
    tail: str
    truncated: bool


class DocumentContent(DocumentRecord):
    """已入库的指定序号切片。"""

    text: str
    chunck_number: int = Field(ge=1)


def _source_literal(source: str) -> str:
    """Zvec 字符串只转义引号，保留文件路径中的反斜杠。"""
    return "'" + source.replace("'", "\\'") + "'"


class _Catalog(BaseModel):
    """知识库的唯一清单，以规范化绝对路径为键；向量库按此清单校验和修复。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1] = 1
    documents: dict[str, DocumentRecord] = Field(default_factory=dict)
    pending: list[str] = Field(default_factory=list)


class KnowledgeStore:
    """所有文档使用一个索引，只存正文片段和元数据，不复制原文档。"""

    def __init__(self, storage_root: Path | None = None) -> None:
        self.root = (storage_root or KNOWLEDGE_DIRECTORY).expanduser().resolve()

    def _catalog(self) -> _Catalog:
        """读取共享文档清单，未创建时返回空清单。"""
        path = self.root / "catalog.json"
        if not path.exists():
            return _Catalog()
        try:
            return _Catalog.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as error:
            raise KnowledgeError(
                "知识库清单无法读取或版本不兼容；请恢复匹配版本的备份，或备份并移走知识库目录后重新导入。"
            ) from error

    def _publish(self, catalog: _Catalog) -> None:
        """临时文件刷盘并关闭后原子替换清单，兼容 Windows 文件占用规则。"""
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.root, delete=False) as file:
                temporary = Path(file.name)
                file.write(catalog.model_dump_json(indent=2))
                file.flush()
                os.fsync(file.fileno())
            temporary.replace(self.root / "catalog.json")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @contextmanager
    def _collection(self, *, create: bool = False) -> Iterator[zvec.Collection]:
        """按需打开共享集合，退出上下文时确保关闭原生句柄。"""
        import zvec

        path = self.root / "index"
        collection = None
        if path.exists():
            collection = zvec.open(str(path))
            if create and collection.schema.field("source") is None:
                # 索引可以重建，旧结构无需迁移；JSON 清单保持不变。
                collection.destroy()
                collection = None
        if collection is None and create:
            path.parent.mkdir(parents=True, exist_ok=True)
            schema = zvec.CollectionSchema(
                name="knowledge",
                fields=[
                    zvec.FieldSchema(
                        "text", zvec.DataType.STRING, index_param=zvec.FtsIndexParam(tokenizer_name="jieba")
                    ),
                    zvec.FieldSchema("source", zvec.DataType.STRING),
                    zvec.FieldSchema("chunck_number", zvec.DataType.INT64),
                ],
                vectors=zvec.VectorSchema(
                    "embedding",
                    zvec.DataType.VECTOR_FP32,
                    DIMENSIONS,
                    index_param=zvec.HnswIndexParam(metric_type=zvec.MetricType.COSINE),
                ),
            )
            collection = zvec.create_and_open(str(path), schema)
        elif collection is None:
            raise KnowledgeError("知识库索引缺失，请重新导入文档。")
        try:
            yield collection
        finally:
            collection.close()

    @requires_embedding_model
    def import_document(self, raw_path: str) -> dict:
        """文件未更新就直接返回；新增或更新时重新写入。"""
        source = Path(raw_path).expanduser().resolve()
        with _STORAGE_LOCK:
            catalog = self._catalog()
            source_key = os.path.normcase(str(source))
            record = catalog.documents.get(source_key)
            try:
                mtime_ns = source.stat().st_mtime_ns
            except OSError as error:
                raise KnowledgeError("无法读取文件，请检查文件路径和访问权限。") from error
            # 已入库且文件修改时间相同：直接返回，不检查向量。
            if record is not None and record.mtime_ns == mtime_ns and source_key not in catalog.pending:
                return {"status": "unchanged", **record.model_dump()}
            return self._write_document(source)

    def _write_document(self, source: Path) -> dict:
        """按 source 删除向量、原子更新 JSON，然后插入新的正文和向量。"""
        import anydoc
        import zvec

        if not source.is_file():
            raise KnowledgeError("文件不存在或不是普通文件。")
        source_key = os.path.normcase(str(source))
        with _STORAGE_LOCK:
            catalog = self._catalog()
            old = catalog.documents.get(source_key)
            try:
                stat = source.stat()
                if stat.st_size > MAX_FILE_BYTES:
                    raise KnowledgeError("单个文件不能超过 200 MiB。")
                with source.open("rb") as file:
                    data = file.read(MAX_FILE_BYTES + 1)
            except OSError as error:
                raise KnowledgeError("无法读取文件，请检查文件路径和访问权限。") from error
            if not data:
                raise KnowledgeError("文件为空。")
            if len(data) > MAX_FILE_BYTES:
                raise KnowledgeError("单个文件不能超过 200 MiB。")
            try:
                # PDF/RTF 等有文本签名的文档也应先由 AnyDoc 识别，不能误作纯文本。
                document_format = anydoc.format_from_bytes(data)
                file_type = detect_file_type(source)
                if document_format is not None:
                    text = anydoc.to_markdown_bytes(data, format=document_format, ocr="reject")
                else:
                    if (file_type is None or file_type["kind"] == "image") and anydoc.format_from_extension(
                        source.suffix.lstrip(".")
                    ) is None:
                        raise KnowledgeError("不支持该二进制文件类型；仅支持 AnyDoc 文档或文本文件。")
                    try:
                        text = decode_text(data)
                    except ValueError as error:
                        document_format = anydoc.format_from_extension(source.suffix.lstrip("."))
                        if document_format is None:
                            raise KnowledgeError("不支持该二进制文件；请导入 AnyDoc 支持的文档或文本文件。") from error
                        text = anydoc.to_markdown_bytes(data, format=document_format, ocr="reject")
            except anydoc.NeedsOcrError as error:
                raise KnowledgeError("该 PDF 含扫描页面，需要先在本地完成 OCR 后再导入。") from error
            except anydoc.ConvertError as error:
                raise KnowledgeError("无法解析文档；请检查格式或加密状态。") from error
            if not text.strip(TEXT_WHITESPACE):
                raise KnowledgeError("文档没有可检索的文本。")
            if len(text) > MAX_TEXT_CHARACTERS:
                raise KnowledgeError("文档解析后超过 2000 万字符，请拆分后导入。")
            if source.stat().st_mtime_ns != stat.st_mtime_ns:
                raise KnowledgeError("文件在导入期间发生修改，请重试。")
            try:
                chunks = split_document(
                    self.root,
                    text,
                    markdown=document_format is not None
                    or (file_type is not None and file_type["format"] == "markdown"),
                )
            except EmbeddingError as error:
                raise KnowledgeError(str(error)) from error
            chunks = [utf8_text(chunk) for chunk in chunks]
            record = DocumentRecord(
                source=str(source),
                mtime_ns=stat.st_mtime_ns,
                chunk_count=len(chunks),
            )
            with self._collection(create=True) as collection:
                # 先删该 source 的向量，再原子更新 JSON，最后插入新向量。
                collection.delete_by_filter(f"source = {_source_literal(source_key)}")
                collection.flush()
                catalog.documents[source_key] = record
                if source_key not in catalog.pending:
                    catalog.pending.append(source_key)
                self._publish(catalog)
                for offset in range(0, len(chunks), 64):
                    batch = chunks[offset : offset + 64]
                    try:
                        vectors = embed_texts(self.root, batch)
                    except EmbeddingError as error:
                        raise KnowledgeError(str(error)) from error
                    statuses = collection.upsert(
                        [
                            zvec.Doc(
                                id=record.chunk_id(chunck_number),
                                fields={
                                    "text": chunk,
                                    "source": source_key,
                                    "chunck_number": chunck_number,
                                },
                                vectors={"embedding": vector},
                            )
                            for chunck_number, (chunk, vector) in enumerate(
                                zip(batch, vectors, strict=True), start=offset + 1
                            )
                        ]
                    )
                    if len(statuses) != len(batch) or not all(status.ok() for status in statuses):
                        raise KnowledgeError("文档索引写入失败，请重试。")
                collection.flush()
                if source.stat().st_mtime_ns != stat.st_mtime_ns:
                    raise KnowledgeError("文件在导入期间发生修改，请重试。")
                # 向量全部写入并刷盘成功，才清除待建索引标记。
                catalog.pending.remove(source_key)
                self._publish(catalog)
            return {"status": "updated" if old else "imported", **record.model_dump()}

    def _files(self, parent_path: str | None = None) -> dict[str, DocumentRecord]:
        """获取以原文件路径为键的文档记录，可限定父目录及其子目录。"""
        parent = Path(parent_path).expanduser().resolve() if parent_path is not None else None
        return {
            record.source: record
            for record in self._catalog().documents.values()
            if parent is None or Path(record.source).parent.is_relative_to(parent)
        }

    @requires_embedding_model
    def list_files(
        self, offset: int, limit: int, *, parent_path: str | None = None, filename: str | None = None
    ) -> dict:
        """分页列出文件，可按父目录（含子目录）和文件名筛选；省略目录时列出全库。"""
        with _STORAGE_LOCK:
            records = self._files(parent_path)
            if filename is not None:
                keyword = filename.casefold()
                records = {
                    source: record for source, record in records.items() if keyword in Path(source).name.casefold()
                }
            sources = sorted(records, key=str.casefold)
            return {
                "total": len(sources),
                "offset": offset,
                "files": [records[source].model_dump() for source in sources[offset : offset + limit]],
            }

    @requires_embedding_model
    def path_tree(self) -> dict:
        """只读展示“父目录 → 原文件路径”关系，不维护分类或文件副本。"""
        with _STORAGE_LOCK:
            groups: dict[str, list[str]] = {}
            for source in self._files():
                groups.setdefault(str(Path(source).parent), []).append(source)
            return {"directories": [{"path": path, "files": sorted(files)} for path, files in sorted(groups.items())]}

    @requires_embedding_model
    def read_document(
        self,
        raw_path: str,
        *,
        chunck_number: int | None = None,
    ) -> DocumentPreview | DocumentContent:
        """读取已入库首尾或指定切片，不同步原文件或计算向量。"""
        with _STORAGE_LOCK:
            catalog = self._catalog()
            error_message = "文档读取失败，请重新导入该文档。"
            source_key = os.path.normcase(str(Path(raw_path).expanduser().resolve()))
            record = catalog.documents.get(source_key)
            if record is None or source_key in catalog.pending:
                raise KnowledgeError(error_message)
            if chunck_number is not None:
                if not 1 <= chunck_number <= record.chunk_count:
                    raise KnowledgeError(f"切片序号超出范围，请使用 1 到 {record.chunk_count}。")
                numbers = [chunck_number]
            else:
                numbers = sorted({1, record.chunk_count})
            try:
                with self._collection() as collection:
                    texts: list[str] = []
                    docs = collection.fetch(
                        [record.chunk_id(selected_number) for selected_number in numbers],
                        output_fields=["text"],
                        include_vector=False,
                    )
                    for selected_number in numbers:
                        doc = docs.get(record.chunk_id(selected_number))
                        if doc is None or not isinstance(text := doc.field("text"), str) or not text:
                            raise KnowledgeError(error_message)
                        texts.append(text)
            except Exception as error:
                raise KnowledgeError(error_message) from error
            if chunck_number is not None:
                return DocumentContent(
                    **record.model_dump(),
                    text=texts[0],
                    chunck_number=chunck_number,
                )
            first, last = texts[0], texts[-1]
            truncated = record.chunk_count > 1 or len(first) > PREVIEW_EDGE_CHARACTERS * 2
            return DocumentPreview(
                **record.model_dump(),
                head=first[:PREVIEW_EDGE_CHARACTERS] if truncated else first,
                tail=last[-PREVIEW_EDGE_CHARACTERS:] if truncated else "",
                truncated=truncated,
            )

    @requires_embedding_model
    def delete_documents(self, sources: list[str]) -> dict[str, int]:
        """移除已确认的文档记录及向量，保留所有磁盘原文件。"""
        keys = {os.path.normcase(str(Path(source).expanduser().resolve())) for source in sources}
        with _STORAGE_LOCK:
            catalog = self._catalog()
            selected = keys.intersection(catalog.documents)
            if not selected:
                return {"deleted": 0}
            if (self.root / "index").exists():
                # 删除中途失败时，保留的记录可在下次检索时重建向量。
                catalog.pending = sorted(set(catalog.pending) | selected)
                self._publish(catalog)
                with self._collection() as collection:
                    for source_key in sorted(selected):
                        collection.delete_by_filter(f"source = {_source_literal(source_key)}")
                    collection.flush()
            for source_key in selected:
                del catalog.documents[source_key]
            catalog.pending = [key for key in catalog.pending if key not in selected]
            self._publish(catalog)
            return {"deleted": len(selected)}

    def _sync(self) -> None:
        """按 JSON 更新文件，并重试上次未完成或索引丢失的写入。"""
        with _STORAGE_LOCK:
            catalog = self._catalog()
            # 整个索引丢失时全部重写，先记录状态，避免重建首个文档后误跳过其余文档。
            index_exists = (self.root / "index").exists()
            for source_key, record in catalog.documents.items():
                source = Path(record.source)
                try:
                    mtime_ns = source.stat().st_mtime_ns
                except FileNotFoundError:
                    mtime_ns = None
                except OSError as error:
                    raise KnowledgeError("无法检查知识库原文件的修改时间，请检查文件路径与访问权限后重试。") from error
                # 原文件已删除：先删向量，再从 JSON 移除。
                if mtime_ns is None:
                    with self._collection(create=True) as collection:
                        collection.delete_by_filter(f"source = {_source_literal(source_key)}")
                        collection.flush()
                    current = self._catalog()
                    del current.documents[source_key]
                    if source_key in current.pending:
                        current.pending.remove(source_key)
                    self._publish(current)
                    continue

                # 原文件更新：删除旧向量、更新 JSON、插入新向量。
                if mtime_ns != record.mtime_ns:
                    self._write_document(source)
                    continue

                # 时间相同、上次已写完且索引目录存在：直接跳过。
                if source_key not in catalog.pending and index_exists:
                    continue
                # 上次写入未完成，或整个索引目录丢失：重新写入。
                self._write_document(source)

    @requires_embedding_model
    def search(
        self,
        query: str,
        top_k: int,
        *,
        parent_paths: list[str] | None = None,
    ) -> dict:
        """先同步全库原文件，再按指定目录范围混合检索正文。"""
        import zvec

        with _STORAGE_LOCK:
            self._sync()
            if parent_paths is None:
                files = self._files()
            else:
                files = {}
                for parent in parent_paths:
                    files.update(self._files(parent))
            if not files:
                return {"query": query, "retrieval": "hybrid", "results": []}
            active = {os.path.normcase(source): record for source, record in files.items()}
            sources = ", ".join(_source_literal(source) for source in active)
            try:
                vector = embed_texts(self.root, [query], is_query=True)[0]
            except EmbeddingError as error:
                raise KnowledgeError(str(error)) from error
            with self._collection() as collection:
                matches = collection.query(
                    [
                        zvec.Query(
                            "text", fts=zvec.Fts(match_string=query), param=zvec.FtsQueryParam(default_operator="OR")
                        ),
                        zvec.Query("embedding", vector=vector),
                    ],
                    topk=max(20, top_k * 4),
                    filter=f"source IN ({sources})",
                    reranker=zvec.RrfReRanker(rank_constant=60),
                )
                results = [
                    {
                        "source": active[match.field("source")].source,
                        "chunck_number": match.field("chunck_number"),
                        "chunk_count": active[match.field("source")].chunk_count,
                        "score": match.score,
                        "text": match.field("text"),
                    }
                    for match in matches[:top_k]
                ]
            return {"query": query, "retrieval": "hybrid", "results": results}
