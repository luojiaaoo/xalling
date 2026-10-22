# 领域服务

`backend/router/` 处理 HTTP / WebSocket 传输，`backend/service/` 按职责组织业务服务：

| 子包 | 职责 | 模块 |
| --- | --- | --- |
| `chat/` | 对话生命周期、SDK 连接选项、斜杠命令和事件推送 | `service.py`、`options.py`、`command.py`、`events.py` |
| `knowledge/` | 知识库存储、索引、检索和向量模型 | `store.py`、`embedding.py` |
| `scheduling/` | 定时任务生命周期、调度和 SQLite 持久化 | `service.py` |
| `tools/` | 向 Agent 暴露的 SDK MCP 工具 | `knowledge.py`、`research.py`、`scheduler.py`、`web_search.py` |
| `desktop/` | 本机文件、窗口、日志和教程资源 | `file.py`、`window.py`、`log.py`、`tutorial.py` |
| `settings/` | 模型站点和主题设置的业务操作 | `model.py`、`theme.py` |

新增 MCP 工具放入 `tools/`，在 `chat/options.py` 中注册。工具调用知识库等业务能力时，复用对应领域服务；存储和检索实现放入 `knowledge/`。

`tools/scheduler.py` 负责 Agent 工具参数与结果，调用 `scheduling/service.py` 执行调度操作。原 `backend/scheduler.py` 仅保留旧持久化任务反序列化所需的类和执行入口，业务代码不从该路径导入。

`settings/` 使用 `backend/config/` 的配置模型与持久化能力。Claude SDK 消息适配、历史装配和统一事件定义仍由 `backend/claude_chat_client/` 负责。

调用方直接导入具体模块，例如 `from backend.service.chat.service import ChatService`。子目录使用命名空间包，不添加空的 `__init__.py`。
