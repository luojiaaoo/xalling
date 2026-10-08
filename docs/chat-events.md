# 对话事件实现

以原版本 `9824588` 的 ChatEvent / render_event 协议和界面为基础完善。`paseo/` 仅作阅读参考，应用、测试和打包不依赖它，也不再机械同步其时间线核心。

原版本已经实现逻辑回合、动态后台工作流、权限与问答、嵌套子 Agent、用量聚合、搜索定位和断线恢复。此次补齐的是这些功能之间的具体归并缺口。

| 原实现的缺口 | 现在的处理 |
| --- | --- |
| 实时、历史、HTTP 返回分别更新完成态 | 共用 `reduceConversationEvent()`；HTTP 先返回时恢复后端原事件，旧请求不能修改下一轮状态 |
| 完整块和流式块使用不同身份；历史为每个包合成从 0 开始的 delta | 按模型消息累计块号，UUID 保留包身份；完整块更新同一个轨迹节点；历史直接适配完整消息 |
| 只保留最后一个正文包作为结果回退 | 同一模型消息内收集全部正文块；换模型调用后只保留该次调用的正文作为最终内容 |
| 工具完成投影丢掉输出 | 保留 JSON 安全的工具结果，普通工具也能展开查看；错误结果同时展示 |
| 后台任务输出 `tool_id`，归并器读取 `tool_use_id` | 统一为 `tool_use_id`；同一 Agent 的多个任务全部结束后再完成，保留失败状态 |
| 子 Agent 事件早于父工具时被丢弃 | 按回合暂存事件，父工具出现后逐层挂接，支持嵌套子 Agent |
| 历史加载依赖底层存储格式 | 仅使用 SDK 公共历史接口及返回字段，不直接读取原生 transcript；SDK 未提供消息时间，历史事件时间为加载时刻，不恢复真实回合时长 |
| 断线快照移除旧权限，但缓冲里可能再次出现它 | 快照返回全部覆盖事件 ID；恢复时过滤缓冲中的旧事件，已结束回合不重新打开 |
| 前端缺少归并回归测试 | 纯函数测试覆盖正文、工具、任务、权限、终态；跨语言测试执行真实 SDK 适配和实际 TypeScript 归并器 |

## 模块边界

- `backend/claude_chat_client/message_adapter.py`：SDK 消息转 ChatEvent，识别模型消息、块和工具身份。
- `history.py`：仅通过 SDK 公共接口恢复同一事件协议，不读取底层存储或补充 SDK 未公开的元数据。
- `models.py: render_event()`：唯一 SDK 语义到 UI JSON 的投影，原始 SDK 对象不会进入组件。
- `frontend/src/chat/trace.ts`：正文、思考、工具与嵌套轨迹的纯归并。
- `frontend/src/chat/conversation.ts`：用户气泡、逻辑回合、最终正文与终态；实时和历史共用。
- `Workspace.tsx` / `AgentTrace.tsx`：原来的布局、展示和用户交互。

去重按事件和内容块身份执行，不能按正文相等去重，否则会吞掉模型在不同块中有意重复的内容。`turn.proxy.completed` 和 `user.proxy.message` 保留原回合，并把中间回复留在轨迹里。诊断和 hook 仍保留在后端协议中，前端不会为其创建空回复。

## 文件检查点

Claude 连接同时启用 `enable_file_checkpointing` 和 `replay-user-messages`。适配层仅对 SDK 回传的主 Agent 人类输入 UUID 发出 `files.checkpoint`，不会将本地合成消息或后台通知当作已建立的检查点。重复的用户消息回显不会创建第二个用户气泡。

`FileCheckpointStore` 在本地 `file-checkpoints/<session UUID>.json` 保存确认收到的检查点标识、事件身份、所属工作区、恢复时间及每轮最后一份 `files.changed` 差异快照。差异包含预览文件内容，不保存完整聊天正文。历史加载仍使用 SDK 公共消息字段，以 `message_uuid` 接回对应回合；保存的快照优先于缺少结构化工具结果的历史重建，不读取原生 transcript。旧会话没有已记录的检查点时不显示恢复按钮。

检查点存储、历史补齐、恢复事件构造和传输投影均归 `backend/claude_chat_client/`：`file_checkpoint.py` 接收应用注入的目录，提供 `record_event()`、`project_history()` 和 `rewind_files()`；`models.py` 定义 `ChatEvent` / `FileRestoreResult`，由 `ChatEvent.to_payload()` 生成统一的事件及 UI 投影。service 层只消费包的公共接口，负责工作区锁、配置、应用任务和事件转发，不定义或构造 `ChatEvent`。

`POST /api/chat/files/rewind` 校验检查点归属，通过保留或恢复连接的 SDK 客户端调用公共 `rewind_files()`。同一工作区生成期间不能恢复，恢复期间不能开始新的生成、重复恢复或关闭客户端；HTTP 取消不会取消应用持有的恢复任务。成功后产生 `files.restored`，实时推送和 HTTP 返回均通过同一事件归并器更新回合状态，不创建模型回合。

`file_changes.py` 从成功的 SDK Write / Edit / NotebookEdit 结果提取文件变更，每个逻辑回合独立统计。同一文件以首次成功编辑前的内容和最后一次编辑后的内容计算净差异；编辑后又还原的文件不计入。只读、失败或拒绝的调用不计入。内容缺失、过大或前后不连续时标为部分记录，不编造净增删行数；普通子 Agent 的文件编辑可展示，但标记为不在主 Agent 检查点恢复范围内。命令行修改不从 Git 工作区猜测。`files.changed` 使用统一事件投影，前端归并器将文件快照挂在对应 AI 回合，生成期间不显示变更卡片，完成、停止或失败后均能查看已经发生的修改。

前端 `TurnChanges` 在回复下显示文件列表、净增删行数和展开入口，`DiffViewer` 显示保存的本轮差异，`FileCheckpointAction` 在卡片中提供撤销确认。恢复只改文件，保留对话和修改记录；恢复较早消息会撤销该检查点之后 SDK 跟踪的修改，不依赖 Git 提交。独立 Git 面板及其 HTTP 接口已移除。

## 验证

```powershell
uv run pytest
uv run ruff check . --exclude paseo
npm --prefix frontend test
npm --prefix frontend run check
npm --prefix frontend run build
```

跨语言集成测试需要 Node 和前端依赖；没有这些依赖时会明确跳过，Python 自身的回归照常运行。历史仍按会话全量加载；特别长的会话需要另行增加按完整回合分页或虚拟列表，不能只截取 delta 数量而切断工具结构。
