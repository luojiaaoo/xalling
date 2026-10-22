# 知识库文档首尾预览

`GET /api/knowledge/documents/preview` 通过 `source` 查询参数指定已入库文件的完整原路径，使用与其他业务接口相同的 Bearer token 认证。前端统一调用 `getKnowledgeDocumentPreview(source)`，由请求层编码路径。

响应示例：

```json
{
  "source": "C:\\资料\\manual.pdf",
  "mtime_ns": 1780000000000000000,
  "chunk_count": 12,
  "head": "已入库正文的开头……",
  "tail": "……已入库正文的结尾",
  "truncated": true
}
```

- 长文：`head`、`tail` 分别从首、末片段截取最多 500 个字符，`truncated` 为 `true`；首尾片段不足 500 字符时按实际长度返回。调用方可在两段之间显示省略号。
- 不超过 1000 字符的单片段文档：`head` 返回全文，`tail` 为空字符串，`truncated` 为 `false`。
- `mtime_ns`、`chunk_count` 对应入库快照。预览不读取或同步磁盘原文件，不触发解析、向量计算或全库扫描。原文件变更后，预览仍显示此前入库的内容，直到重新导入或检索时完成同步。
- 未认证返回 401，参数缺失或非法返回 422，文档未入库或已移除返回 404，模型未就绪、索引未完成或首尾片段缺失/不一致返回 400。其他异常返回不含内部细节的 500 响应。

正文只保存在 Zvec 的 `text` 字段中。`catalog.json` 继续只保存文档元数据和索引状态，不增加预览正文副本。服务先检查清单和 `pending` 状态，再根据 `DocumentRecord.chunk_id(1)` 与 `chunk_id(chunk_count)` 一次读取至多两个片段，只取正文及用于校验的元数据，不读取向量。单片段只读取一次。

读取及校验在知识库共用存储锁内完成，与导入和删除互斥。索引不完整时明确报错，不返回一半预览或自动修改知识库。
