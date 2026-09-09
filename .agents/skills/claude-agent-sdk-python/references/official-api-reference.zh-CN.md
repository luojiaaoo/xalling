> ## Documentation Index
> Fetch the complete documentation index at: https://code.claude.com/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Agent SDK 参考 - Python

> Python Agent SDK 的完整 API 参考，包括所有函数、类型和类。

<h2 id="installation">
  安装
</h2>

在虚拟环境中安装该包。在最近的 Debian、Ubuntu 和 Homebrew Python 安装上，针对系统 Python 运行 `pip install` 会失败，出现 `error: externally-managed-environment` 错误。

```bash theme={null}
python3 -m venv .venv
source .venv/bin/activate
pip install claude-agent-sdk
```

有关 uv、Windows PowerShell 和 API 密钥设置，请参阅 [Agent SDK 概述中的入门](/docs/zh-CN/agent-sdk/overview#get-started)。

<h2 id="choosing-between-query-and-claudesdkclient">
  在 `query()` 和 `ClaudeSDKClient` 之间选择
</h2>

Python SDK 提供了两种与 Claude Code 交互的方式：

<h3 id="quick-comparison">
  快速比较
</h3>

| 功能        | `query()`                                  | `ClaudeSDKClient` |
| :-------- | :----------------------------------------- | :---------------- |
| **会话**    | 默认创建新会话                                    | 重用同一会话            |
| **对话**    | 单次交换                                       | 同一上下文中的多次交换       |
| **连接**    | 自动管理                                       | 手动控制              |
| **流式输入**  | ✅ 支持                                       | ✅ 支持              |
| **中断**    | ❌ 不支持                                      | ✅ 支持              |
| **hooks** | ✅ 支持                                       | ✅ 支持              |
| **自定义工具** | ✅ 支持                                       | ✅ 支持              |
| **继续聊天**  | 通过 `continue_conversation` 或 `resume` 手动进行 | ✅ 自动              |
| **用例**    | 一次性任务                                      | 持续对话              |

<h3 id="when-to-use-query-one-off-tasks">
  何时使用 `query()`（一次性任务）
</h3>

**最适合：**

* 不需要对话历史的一次性问题
* 不需要来自之前交换的上下文的独立任务
* 简单的自动化脚本
* 当你想每次都重新开始时

<h3 id="when-to-use-claudesdkclient-continuous-conversation">
  何时使用 `ClaudeSDKClient`（持续对话）
</h3>

**最适合：**

* **继续对话** - 当你需要 Claude 记住上下文时
* **后续问题** - 基于之前的响应进行构建
* **交互式应用程序** - 聊天界面、REPL
* **响应驱动的逻辑** - 当下一步操作取决于 Claude 的响应时
* **会话控制** - 显式管理对话生命周期

<h2 id="functions">
  函数
</h2>

<h3 id="query">
  `query()`
</h3>

为每次与 Claude Code 的交互创建一个新会话。默认情况下返回一个异步迭代器，当消息到达时产生消息。每次调用 `query()` 都会重新开始，不记得之前的交互，除非你传递 `continue_conversation=True` 或在 [`ClaudeAgentOptions`](#claudeagentoptions) 中传递 `resume`。参见 [Sessions](/docs/zh-CN/agent-sdk/sessions)。

```python theme={null}
async def query(
    *,
    prompt: str | AsyncIterable[dict[str, Any]],
    options: ClaudeAgentOptions | None = None,
    transport: Transport | None = None
) -> AsyncIterator[Message]
```

<h4 id="parameters">
  参数
</h4>

| 参数          | 类型                           | 描述                                          |
| :---------- | :--------------------------- | :------------------------------------------ |
| `prompt`    | `str \| AsyncIterable[dict]` | 输入提示，可以是字符串或用于流式模式的异步可迭代对象                  |
| `options`   | `ClaudeAgentOptions \| None` | 可选配置对象（如果为 None，默认为 `ClaudeAgentOptions()`） |
| `transport` | `Transport \| None`          | 用于与 CLI 进程通信的可选自定义传输                        |

<h4 id="returns">
  返回
</h4>

返回一个 `AsyncIterator[Message]`，从对话中产生消息。

<h4 id="example-with-options">
  示例 - 带选项
</h4>

```python theme={null}
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions


async def main():
    options = ClaudeAgentOptions(
        system_prompt="You are an expert Python developer",
        permission_mode="acceptEdits",
        cwd="/home/user/project",
    )

    async for message in query(prompt="Create a Python web server", options=options):
        print(message)


asyncio.run(main())
```

<h3 id="tool">
  `tool()`
</h3>

用于定义具有类型安全的 MCP 工具的装饰器。

```python theme={null}
def tool(
    name: str,
    description: str,
    input_schema: type | dict[str, Any],
    annotations: ToolAnnotations | None = None
) -> Callable[[Callable[[Any], Awaitable[dict[str, Any]]]], SdkMcpTool[Any]]
```

<h4 id="parameters-2">
  参数
</h4>

| 参数             | 类型                                              | 描述                      |
| :------------- | :---------------------------------------------- | :---------------------- |
| `name`         | `str`                                           | 工具的唯一标识符                |
| `description`  | `str`                                           | 工具功能的人类可读描述             |
| `input_schema` | `type \| dict[str, Any]`                        | 定义工具输入参数的模式（见下文）        |
| `annotations`  | [`ToolAnnotations`](#toolannotations)` \| None` | 可选的 MCP 工具注解，为客户端提供行为提示 |

<h4 id="input-schema-options">
  输入模式选项
</h4>

1. **简单类型映射**（推荐）：

   ```python theme={null}
   {"text": str, "count": int, "enabled": bool}
   ```

2. **JSON Schema 格式**（用于复杂验证）：
   ```python theme={null}
   {
       "type": "object",
       "properties": {
           "text": {"type": "string"},
           "count": {"type": "integer", "minimum": 0},
       },
       "required": ["text"],
   }
   ```

<h4 id="returns-2">
  返回
</h4>

一个装饰器函数，包装工具实现并返回一个 `SdkMcpTool` 实例。

<h4 id="example">
  示例
</h4>

```python theme={null}
from claude_agent_sdk import tool
from typing import Any


@tool("greet", "Greet a user", {"name": str})
async def greet(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": f"Hello, {args['name']}!"}]}
```

<h4 id="toolannotations">
  `ToolAnnotations`
</h4>

从 `mcp.types` 重新导出（也可以从 `claude_agent_sdk` 导入为 `from claude_agent_sdk import ToolAnnotations`）。所有字段都是可选的提示；客户端不应依赖它们做出安全决策。

| 字段                | 类型             | 默认值     | 描述                                                             |
| :---------------- | :------------- | :------ | :------------------------------------------------------------- |
| `title`           | `str \| None`  | `None`  | 工具的人类可读标题                                                      |
| `readOnlyHint`    | `bool \| None` | `False` | 如果为 `True`，工具不修改其环境                                            |
| `destructiveHint` | `bool \| None` | `True`  | 如果为 `True`，工具可能执行破坏性更新（仅当 `readOnlyHint` 为 `False` 时有意义）       |
| `idempotentHint`  | `bool \| None` | `False` | 如果为 `True`，使用相同参数的重复调用没有额外效果（仅当 `readOnlyHint` 为 `False` 时有意义） |
| `openWorldHint`   | `bool \| None` | `True`  | 如果为 `True`，工具与外部实体交互（例如网络搜索）。如果为 `False`，工具的域是封闭的（例如内存工具）      |

```python theme={null}
from claude_agent_sdk import tool, ToolAnnotations
from typing import Any


@tool(
    "search",
    "Search the web",
    {"query": str},
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)
async def search(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": f"Results for: {args['query']}"}]}
```

<h3 id="create_sdk_mcp_server">
  `create_sdk_mcp_server()`
</h3>

创建在 Python 应用程序中运行的进程内 MCP 服务器。

```python theme={null}
def create_sdk_mcp_server(
    name: str,
    version: str = "1.0.0",
    tools: list[SdkMcpTool[Any]] | None = None
) -> McpSdkServerConfig
```

<h4 id="parameters-3">
  参数
</h4>

| 参数        | 类型                              | 默认值       | 描述                      |
| :-------- | :------------------------------ | :-------- | :---------------------- |
| `name`    | `str`                           | -         | 服务器的唯一标识符               |
| `version` | `str`                           | `"1.0.0"` | 服务器版本字符串                |
| `tools`   | `list[SdkMcpTool[Any]] \| None` | `None`    | 使用 `@tool` 装饰器创建的工具函数列表 |

<h4 id="returns-3">
  返回
</h4>

返回一个 `McpSdkServerConfig` 对象，可以传递给 `ClaudeAgentOptions.mcp_servers`。

<h4 id="example-2">
  示例
</h4>

```python theme={null}
from claude_agent_sdk import tool, create_sdk_mcp_server


@tool("add", "Add two numbers", {"a": float, "b": float})
async def add(args):
    return {"content": [{"type": "text", "text": f"Sum: {args['a'] + args['b']}"}]}


@tool("multiply", "Multiply two numbers", {"a": float, "b": float})
async def multiply(args):
    return {"content": [{"type": "text", "text": f"Product: {args['a'] * args['b']}"}]}


calculator = create_sdk_mcp_server(
    name="calculator",
    version="2.0.0",
    tools=[add, multiply],  # Pass decorated functions
)

# Use with Claude
options = ClaudeAgentOptions(
    mcp_servers={"calc": calculator},
    allowed_tools=["mcp__calc__add", "mcp__calc__multiply"],
)
```

<h3 id="list_sessions">
  `list_sessions()`
</h3>

列出带有元数据的过去会话。按项目目录过滤或列出所有项目中的会话。同步；立即返回。

```python theme={null}
def list_sessions(
    directory: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    include_worktrees: bool = True
) -> list[SDKSessionInfo]
```

<h4 id="parameters-4">
  参数
</h4>

| 参数                  | 类型            | 默认值    | 描述                                             |
| :------------------ | :------------ | :----- | :--------------------------------------------- |
| `directory`         | `str \| None` | `None` | 列出会话的目录。省略时，返回所有项目中的会话                         |
| `limit`             | `int \| None` | `None` | 返回的最大会话数                                       |
| `offset`            | `int`         | `0`    | 从排序结果开始跳过的会话数。与 `limit` 一起用于分页                 |
| `include_worktrees` | `bool`        | `True` | 当 `directory` 在 git 仓库内时，包括所有 worktrees 路径中的会话 |

<h4 id="return-type-sdksessioninfo">
  返回类型：`SDKSessionInfo`
</h4>

| 属性              | 类型            | 描述                                           |
| :-------------- | :------------ | :------------------------------------------- |
| `session_id`    | `str`         | 唯一会话标识符                                      |
| `summary`       | `str`         | 显示标题：自定义标题、自动生成的摘要或第一个提示                     |
| `last_modified` | `int`         | 上次修改时间（自纪元以来的毫秒数）                            |
| `file_size`     | `int \| None` | 会话文件大小（字节）（远程存储后端为 `None`）                   |
| `custom_title`  | `str \| None` | 用户设置的会话标题                                    |
| `first_prompt`  | `str \| None` | 会话中的第一个有意义的用户提示                              |
| `git_branch`    | `str \| None` | 会话结束时的 Git 分支                                |
| `cwd`           | `str \| None` | 会话的工作目录                                      |
| `tag`           | `str \| None` | 用户设置的会话标签（见 [`tag_session()`](#tag_session)） |
| `created_at`    | `int \| None` | 会话创建时间（自纪元以来的毫秒数）                            |

<h4 id="example-3">
  示例
</h4>

打印项目的 10 个最近会话。结果按 `last_modified` 降序排序，所以第一项是最新的。省略 `directory` 以搜索所有项目。

```python theme={null}
from claude_agent_sdk import list_sessions

for session in list_sessions(directory="/path/to/project", limit=10):
    print(f"{session.summary} ({session.session_id})")
```

<h3 id="get_session_messages">
  `get_session_messages()`
</h3>

从过去的会话中检索消息。同步；立即返回。

```python theme={null}
def get_session_messages(
    session_id: str,
    directory: str | None = None,
    limit: int | None = None,
    offset: int = 0
) -> list[SessionMessage]
```

<h4 id="parameters-5">
  参数
</h4>

| 参数           | 类型            | 默认值    | 描述                  |
| :----------- | :------------ | :----- | :------------------ |
| `session_id` | `str`         | 必需     | 要检索消息的会话 ID         |
| `directory`  | `str \| None` | `None` | 要查看的项目目录。省略时，搜索所有项目 |
| `limit`      | `int \| None` | `None` | 返回的最大消息数            |
| `offset`     | `int`         | `0`    | 从开始跳过的消息数           |

<h4 id="return-type-sessionmessage">
  返回类型：`SessionMessage`
</h4>

| 属性                   | 类型                             | 描述      |
| :------------------- | :----------------------------- | :------ |
| `type`               | `Literal["user", "assistant"]` | 消息角色    |
| `uuid`               | `str`                          | 唯一消息标识符 |
| `session_id`         | `str`                          | 会话标识符   |
| `message`            | `Any`                          | 原始消息内容  |
| `parent_tool_use_id` | `None`                         | 保留供将来使用 |

<h4 id="example-4">
  示例
</h4>

```python theme={null}
from claude_agent_sdk import list_sessions, get_session_messages

sessions = list_sessions(limit=1)
if sessions:
    messages = get_session_messages(sessions[0].session_id)
    for msg in messages:
        print(f"[{msg.type}] {msg.uuid}")
```

<h3 id="get_session_info">
  `get_session_info()`
</h3>

按 ID 读取单个会话的元数据，无需扫描完整项目目录。同步；立即返回。

```python theme={null}
def get_session_info(
    session_id: str,
    directory: str | None = None,
) -> SDKSessionInfo | None
```

<h4 id="parameters-6">
  参数
</h4>

| 参数           | 类型            | 默认值    | 描述                  |
| :----------- | :------------ | :----- | :------------------ |
| `session_id` | `str`         | 必需     | 要查找的会话的 UUID        |
| `directory`  | `str \| None` | `None` | 项目目录路径。省略时，搜索所有项目目录 |

返回 [`SDKSessionInfo`](#return-type-sdksessioninfo)，如果找不到会话则返回 `None`。

<h4 id="example-5">
  示例
</h4>

查找单个会话的元数据，无需扫描项目目录。当你已经从之前的运行中获得会话 ID 时很有用。

```python theme={null}
from claude_agent_sdk import get_session_info

info = get_session_info("550e8400-e29b-41d4-a716-446655440000")
if info:
    print(f"{info.summary} (branch: {info.git_branch}, tag: {info.tag})")
```

<h3 id="rename_session">
  `rename_session()`
</h3>

通过追加自定义标题条目来重命名会话。重复调用是安全的；最新的标题获胜。同步。

```python theme={null}
def rename_session(
    session_id: str,
    title: str,
    directory: str | None = None,
) -> None
```

<h4 id="parameters-7">
  参数
</h4>

| 参数           | 类型            | 默认值    | 描述                  |
| :----------- | :------------ | :----- | :------------------ |
| `session_id` | `str`         | 必需     | 要重命名的会话的 UUID       |
| `title`      | `str`         | 必需     | 新标题。去除空格后必须非空       |
| `directory`  | `str \| None` | `None` | 项目目录路径。省略时，搜索所有项目目录 |

如果 `session_id` 不是有效的 UUID 或 `title` 为空，则抛出 `ValueError`；如果找不到会话，则抛出 `FileNotFoundError`。

<h4 id="example-6">
  示例
</h4>

重命名最近的会话，使其更容易找到。新标题在后续读取时出现在 [`SDKSessionInfo.custom_title`](#return-type-sdksessioninfo) 中。

```python theme={null}
from claude_agent_sdk import list_sessions, rename_session

sessions = list_sessions(directory="/path/to/project", limit=1)
if sessions:
    rename_session(sessions[0].session_id, "Refactor auth module")
```

<h3 id="tag_session">
  `tag_session()`
</h3>

标记会话。传递 `None` 以清除标签。重复调用是安全的；最新的标签获胜。同步。

```python theme={null}
def tag_session(
    session_id: str,
    tag: str | None,
    directory: str | None = None,
) -> None
```

<h4 id="parameters-8">
  参数
</h4>

| 参数           | 类型            | 默认值    | 描述                                  |
| :----------- | :------------ | :----- | :---------------------------------- |
| `session_id` | `str`         | 必需     | 要标记的会话的 UUID                        |
| `tag`        | `str \| None` | 必需     | 标签字符串，或 `None` 以清除。存储前进行 Unicode 清理 |
| `directory`  | `str \| None` | `None` | 项目目录路径。省略时，搜索所有项目目录                 |

如果 `session_id` 不是有效的 UUID 或 `tag` 在清理后为空，则抛出 `ValueError`；如果找不到会话，则抛出 `FileNotFoundError`。

<h4 id="example-7">
  示例
</h4>

标记会话，然后在稍后的读取中按该标签过滤。传递 `None` 以清除现有标签。

```python theme={null}
from claude_agent_sdk import list_sessions, tag_session

# Tag a session
tag_session("550e8400-e29b-41d4-a716-446655440000", "needs-review")

# Later: find all sessions with that tag
for session in list_sessions(directory="/path/to/project"):
    if session.tag == "needs-review":
        print(session.summary)
```

<h2 id="classes">
  类
</h2>

<h3 id="claudesdkclient">
  `ClaudeSDKClient`
</h3>

**在多次交换中维持对话会话。** 这是 TypeScript SDK 的 `query()` 函数内部工作方式的 Python 等价物 - 它创建一个可以继续对话的客户端对象。

<h4 id="key-features">
  关键特性
</h4>

* **会话连续性**：在多个 `query()` 调用中维持对话上下文
* **同一对话**：会话保留之前的消息
* **中断支持**：可以在任务中途停止执行
* **显式生命周期**：你控制会话何时开始和结束
* **响应驱动的流程**：可以对响应做出反应并发送后续消息
* **自定义工具和 hooks**：支持自定义工具（使用 `@tool` 装饰器创建）和 hooks

```python theme={null}
class ClaudeSDKClient:
    def __init__(self, options: ClaudeAgentOptions | None = None, transport: Transport | None = None)
    async def connect(self, prompt: str | AsyncIterable[dict] | None = None) -> None
    async def query(self, prompt: str | AsyncIterable[dict], session_id: str = "default") -> None
    async def receive_messages(self) -> AsyncIterator[Message]
    async def receive_response(self) -> AsyncIterator[Message]
    async def interrupt(self) -> None
    async def set_permission_mode(self, mode: str) -> None
    async def set_model(self, model: str | None = None) -> None
    async def rewind_files(self, user_message_id: str) -> None
    async def get_mcp_status(self) -> McpStatusResponse
    async def reconnect_mcp_server(self, server_name: str) -> None
    async def toggle_mcp_server(self, server_name: str, enabled: bool) -> None
    async def stop_task(self, task_id: str) -> None
    async def get_server_info(self) -> dict[str, Any] | None
    async def disconnect(self) -> None
```

<h4 id="methods">
  方法
</h4>

| 方法                                        | 描述                                                                                                  |
| :---------------------------------------- | :-------------------------------------------------------------------------------------------------- |
| `__init__(options)`                       | 使用可选配置初始化客户端                                                                                        |
| `connect(prompt)`                         | 连接到 Claude，可选初始提示或消息流                                                                               |
| `query(prompt, session_id)`               | 以流式模式发送新请求                                                                                          |
| `receive_messages()`                      | 以异步迭代器形式接收来自 Claude 的所有消息                                                                           |
| `receive_response()`                      | 接收消息直到并包括 ResultMessage                                                                             |
| `interrupt()`                             | 发送中断信号（仅在流式模式下工作）                                                                                   |
| `set_permission_mode(mode)`               | 更改当前会话的权限模式                                                                                         |
| `set_model(model)`                        | 更改当前会话的模型。传递 `None` 以重置为默认值                                                                         |
| `rewind_files(user_message_id)`           | 将文件恢复到指定用户消息时的状态。需要 `enable_file_checkpointing=True`。见 [文件检查点](/docs/zh-CN/agent-sdk/file-checkpointing) |
| `get_mcp_status()`                        | 获取所有配置的 MCP 服务器的状态。返回 [`McpStatusResponse`](#mcpstatusresponse)                                     |
| `reconnect_mcp_server(server_name)`       | 重试连接到失败或断开连接的 MCP 服务器                                                                               |
| `toggle_mcp_server(server_name, enabled)` | 在会话中启用或禁用 MCP 服务器。禁用会移除其工具                                                                          |
| `stop_task(task_id)`                      | 停止运行的后台任务。一个状态为 `"stopped"` 的 [`TaskNotificationMessage`](#tasknotificationmessage) 随后在消息流中出现       |
| `get_server_info()`                       | 获取服务器信息，包括会话 ID 和功能                                                                                 |
| `disconnect()`                            | 从 Claude 断开连接                                                                                       |

<h4 id="context-manager-support">
  上下文管理器支持
</h4>

客户端可以用作异步上下文管理器以自动管理连接：

```python theme={null}
async with ClaudeSDKClient() as client:
    await client.query("Hello Claude")
    async for message in client.receive_response():
        print(message)
```

> **重要：** 迭代消息时，避免使用 `break` 提前退出，因为这可能导致 asyncio 清理问题。相反，让迭代自然完成或使用标志来跟踪何时找到了你需要的内容。

<h4 id="example-continuing-a-conversation">
  示例 - 继续对话
</h4>

```python theme={null}
import asyncio
from claude_agent_sdk import ClaudeSDKClient, AssistantMessage, TextBlock, ResultMessage


async def main():
    async with ClaudeSDKClient() as client:
        # First question
        await client.query("What's the capital of France?")

        # Process response
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"Claude: {block.text}")

        # Follow-up question - the session retains the previous context
        await client.query("What's the population of that city?")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"Claude: {block.text}")

        # Another follow-up - still in the same conversation
        await client.query("What are some famous landmarks there?")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"Claude: {block.text}")


asyncio.run(main())
```

<h4 id="example-streaming-input-with-claudesdkclient">
  示例 - 使用 ClaudeSDKClient 进行流式输入
</h4>

```python theme={null}
import asyncio
from claude_agent_sdk import ClaudeSDKClient


async def message_stream():
    """Generate messages dynamically."""
    yield {
        "type": "user",
        "message": {"role": "user", "content": "Analyze the following data:"},
    }
    await asyncio.sleep(0.5)
    yield {
        "type": "user",
        "message": {"role": "user", "content": "Temperature: 25°C, Humidity: 60%"},
    }
    await asyncio.sleep(0.5)
    yield {
        "type": "user",
        "message": {"role": "user", "content": "What patterns do you see?"},
    }


async def main():
    async with ClaudeSDKClient() as client:
        # Stream input to Claude
        await client.query(message_stream())

        # Process response
        async for message in client.receive_response():
            print(message)

        # Follow-up in same session
        await client.query("Should we be concerned about these readings?")

        async for message in client.receive_response():
            print(message)


asyncio.run(main())
```

<h4 id="example-using-interrupts">
  示例 - 使用中断
</h4>

```python theme={null}
import asyncio
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, ResultMessage


async def interruptible_task():
    options = ClaudeAgentOptions(allowed_tools=["Bash"], permission_mode="acceptEdits")

    async with ClaudeSDKClient(options=options) as client:
        # Start a long-running task
        await client.query("Count from 1 to 100 slowly, using the bash sleep command")

        # Let it run for a bit
        await asyncio.sleep(2)

        # Interrupt the task
        await client.interrupt()
        print("Task interrupted!")

        # Drain the interrupted task's messages (including its ResultMessage)
        async for message in client.receive_response():
            if isinstance(message, ResultMessage):
                print(f"Interrupted task finished with subtype={message.subtype!r}")
                # subtype is "error_during_execution" for interrupted tasks

        # Send a new command
        await client.query("Just say hello instead")

        # Now receive the new response
        async for message in client.receive_response():
            if isinstance(message, ResultMessage) and message.subtype == "success":
                print(f"New result: {message.result}")


asyncio.run(interruptible_task())
```

<Note>
  **中断后的缓冲行为：** `interrupt()` 发送停止信号但不清除消息缓冲区。被中断任务已产生的消息，包括其 `ResultMessage`（带 `subtype="error_during_execution"`），保留在流中。你必须在读取新查询的响应之前用 `receive_response()` 清空它们。如果在 `interrupt()` 之后立即发送新查询并仅调用一次 `receive_response()`，你将收到被中断任务的消息，而不是新查询的响应。
</Note>

<h4 id="example-advanced-permission-control">
  示例 - 高级权限控制
</h4>

```python theme={null}
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
from claude_agent_sdk.types import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)


async def custom_permission_handler(
    tool_name: str, input_data: dict, context: ToolPermissionContext
) -> PermissionResultAllow | PermissionResultDeny:
    """Custom logic for tool permissions."""

    # Block writes to system directories
    if tool_name == "Write" and input_data.get("file_path", "").startswith("/system/"):
        return PermissionResultDeny(
            message="System directory write not allowed", interrupt=True
        )

    # Redirect sensitive file operations
    if tool_name in ["Write", "Edit"] and "config" in input_data.get("file_path", ""):
        safe_path = f"./sandbox/{input_data['file_path']}"
        return PermissionResultAllow(
            updated_input={**input_data, "file_path": safe_path}
        )

    # Allow everything else
    return PermissionResultAllow(updated_input=input_data)


async def main():
    # 不要同时在 allowed_tools 中列出受限工具：allow 规则在 can_use_tool 运行之前批准调用
    options = ClaudeAgentOptions(can_use_tool=custom_permission_handler)

    async with ClaudeSDKClient(options=options) as client:
        await client.query("Update the system config file")

        async for message in client.receive_response():
            # Will use sandbox path instead
            print(message)


asyncio.run(main())
```

<h2 id="types">
  类型
</h2>

<Note>
  **`@dataclass` vs `TypedDict`：** 此 SDK 使用两种类型。用 `@dataclass` 装饰的类（如 `ResultMessage`、`AgentDefinition`、`TextBlock`）在运行时是对象实例，支持属性访问：`msg.result`。用 `TypedDict` 定义的类（如 `ThinkingConfigEnabled`、`McpStdioServerConfig`、`SyncHookJSONOutput`）在运行时是**普通字典**，需要键访问：`config["budget_tokens"]`，而不是 `config.budget_tokens`。`ClassName(field=value)` 调用语法对两者都有效，但只有数据类产生具有属性的对象。
</Note>

<h3 id="sdkmcptool">
  `SdkMcpTool`
</h3>

使用 `@tool` 装饰器创建的 SDK MCP 工具的定义。

```python theme={null}
@dataclass
class SdkMcpTool(Generic[T]):
    name: str
    description: str
    input_schema: type[T] | dict[str, Any]
    handler: Callable[[T], Awaitable[dict[str, Any]]]
    annotations: ToolAnnotations | None = None
```

| 属性             | 类型                                         | 描述                                                                               |
| :------------- | :----------------------------------------- | :------------------------------------------------------------------------------- |
| `name`         | `str`                                      | 工具的唯一标识符                                                                         |
| `description`  | `str`                                      | 人类可读的描述                                                                          |
| `input_schema` | `type[T] \| dict[str, Any]`                | 输入验证的模式                                                                          |
| `handler`      | `Callable[[T], Awaitable[dict[str, Any]]]` | 处理工具执行的异步函数                                                                      |
| `annotations`  | `ToolAnnotations \| None`                  | 可选的 MCP 工具注解（例如 `readOnlyHint`、`destructiveHint`、`openWorldHint`）。来自 `mcp.types` |

<h3 id="transport">
  `Transport`
</h3>

自定义传输实现的抽象基类。使用此类通过自定义通道与 Claude 进程通信（例如，远程连接而不是本地子进程）。

<Warning>
  这是一个低级内部 API。接口可能在未来版本中更改。自定义实现必须更新以匹配任何接口更改。
</Warning>

```python theme={null}
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class Transport(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def write(self, data: str) -> None: ...

    @abstractmethod
    def read_messages(self) -> AsyncIterator[dict[str, Any]]: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    def is_ready(self) -> bool: ...

    @abstractmethod
    async def end_input(self) -> None: ...
```

| 方法                | 描述                       |
| :---------------- | :----------------------- |
| `connect()`       | 连接传输并准备通信                |
| `write(data)`     | 将原始数据（JSON + 换行符）写入传输    |
| `read_messages()` | 异步迭代器，产生解析的 JSON 消息      |
| `close()`         | 关闭连接并清理资源                |
| `is_ready()`      | 如果传输可以发送和接收，返回 `True`    |
| `end_input()`     | 关闭输入流（例如，为子进程传输关闭 stdin） |

导入：`from claude_agent_sdk import Transport`

<h3 id="claudeagentoptions">
  `ClaudeAgentOptions`
</h3>

Claude Code 查询的配置数据类。

```python theme={null}
@dataclass
class ClaudeAgentOptions:
    tools: list[str] | ToolsPreset | None = None
    allowed_tools: list[str] = field(default_factory=list)
    system_prompt: str | SystemPromptPreset | SystemPromptFile | None = None
    mcp_servers: dict[str, McpServerConfig] | str | Path = field(default_factory=dict)
    strict_mcp_config: bool = False
    permission_mode: PermissionMode | None = None
    continue_conversation: bool = False
    resume: str | None = None
    max_turns: int | None = None
    max_budget_usd: float | None = None
    disallowed_tools: list[str] = field(default_factory=list)
    model: str | None = None
    fallback_model: str | None = None
    betas: list[SdkBeta] = field(default_factory=list)
    output_format: dict[str, Any] | None = None
    permission_prompt_tool_name: str | None = None
    cwd: str | Path | None = None
    cli_path: str | Path | None = None
    settings: str | None = None
    add_dirs: list[str | Path] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    extra_args: dict[str, str | None] = field(default_factory=dict)
    max_buffer_size: int | None = None
    debug_stderr: Any = sys.stderr  # Deprecated
    stderr: Callable[[str], None] | None = None
    can_use_tool: CanUseTool | None = None
    hooks: dict[HookEvent, list[HookMatcher]] | None = None
    user: str | None = None
    include_partial_messages: bool = False
    include_hook_events: bool = False
    fork_session: bool = False
    agents: dict[str, AgentDefinition] | None = None
    setting_sources: list[SettingSource] | None = None
    skills: list[str] | Literal["all"] | None = None
    sandbox: SandboxSettings | None = None
    plugins: list[SdkPluginConfig] = field(default_factory=list)
    max_thinking_tokens: int | None = None  # Deprecated: use thinking instead
    thinking: ThinkingConfig | None = None
    effort: EffortLevel | None = None
    enable_file_checkpointing: bool = False
    session_store: SessionStore | None = None
    session_store_flush: SessionStoreFlushMode = "batched"
```

| 属性                            | 类型                                                                                       | 默认值                 | 描述                                                                                                                                                                                                                                                                          |
| :---------------------------- | :--------------------------------------------------------------------------------------- | :------------------ | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tools`                       | `list[str] \| ToolsPreset \| None`                                                       | `None`              | 工具配置。使用 `{"type": "preset", "preset": "claude_code"}` 获取 Claude Code 的默认工具                                                                                                                                                                                                  |
| `allowed_tools`               | `list[str]`                                                                              | `[]`                | 无需提示即可自动批准的工具。这不会限制 Claude 仅使用这些工具；未列出的工具会通过 `permission_mode` 和 `can_use_tool` 处理。使用 `disallowed_tools` 阻止工具。见 [权限](/docs/zh-CN/agent-sdk/permissions#allow-and-deny-rules)                                                                                                     |
| `system_prompt`               | `str \| SystemPromptPreset \| SystemPromptFile \| None`                                  | `None`              | 系统提示配置。传递字符串以获取自定义提示，`{"type": "preset", "preset": "claude_code"}` 获取 Claude Code 的系统提示（带可选 `"append"`），或 `{"type": "file", "path": "..."}` 从磁盘加载大型提示。见 [`SystemPromptPreset`](#systempromptpreset) 和 [`SystemPromptFile`](#systempromptfile)                               |
| `mcp_servers`                 | `dict[str, McpServerConfig] \| str \| Path`                                              | `{}`                | MCP 服务器配置或配置文件路径                                                                                                                                                                                                                                                            |
| `strict_mcp_config`           | `bool`                                                                                   | `False`             | 当为 `True` 时，仅使用在 `mcp_servers` 中传递的服务器，忽略项目 `.mcp.json`、用户设置、插件提供的 MCP 服务器和 [claude.ai 连接器](/docs/zh-CN/mcp#use-mcp-servers-from-claude-ai)。映射到 CLI `--strict-mcp-config` 标志                                                                                                     |
| `permission_mode`             | `PermissionMode \| None`                                                                 | `None`              | 工具使用的权限模式                                                                                                                                                                                                                                                                   |
| `continue_conversation`       | `bool`                                                                                   | `False`             | 继续最近的对话                                                                                                                                                                                                                                                                     |
| `resume`                      | `str \| None`                                                                            | `None`              | 要恢复的会话 ID                                                                                                                                                                                                                                                                   |
| `max_turns`                   | `int \| None`                                                                            | `None`              | 最大代理轮次（工具使用往返）                                                                                                                                                                                                                                                              |
| `max_budget_usd`              | `float \| None`                                                                          | `None`              | 当客户端成本估计达到此 USD 值时停止查询。与 `total_cost_usd` 的相同估计进行比较；见 [跟踪成本和使用](/docs/zh-CN/agent-sdk/cost-tracking) 了解准确性注意事项                                                                                                                                                                   |
| `disallowed_tools`            | `list[str]`                                                                              | `[]`                | 要拒绝的工具。裸名称如 `"Bash"` 从 Claude 的上下文中移除工具。作用域规则如 `"Bash(rm *)"` 保持工具可用，并在每个权限模式（包括 `bypassPermissions`）中拒绝匹配的调用。见 [权限](/docs/zh-CN/agent-sdk/permissions#allow-and-deny-rules)                                                                                                     |
| `enable_file_checkpointing`   | `bool`                                                                                   | `False`             | 启用文件更改跟踪以进行回滚。见 [文件检查点](/docs/zh-CN/agent-sdk/file-checkpointing)                                                                                                                                                                                                                |
| `model`                       | `str \| None`                                                                            | `None`              | Claude 模型别名或完整模型名称。见 [接受的值和特定于提供商的 ID](/docs/zh-CN/model-config#available-models)                                                                                                                                                                                                |
| `fallback_model`              | `str \| None`                                                                            | `None`              | 主模型失败时使用的备用模型                                                                                                                                                                                                                                                               |
| `betas`                       | `list[SdkBeta]`                                                                          | `[]`                | 要启用的测试功能。见 [`SdkBeta`](#sdkbeta) 了解可用选项                                                                                                                                                                                                                                     |
| `output_format`               | `dict[str, Any] \| None`                                                                 | `None`              | 结构化响应的输出格式（例如 `{"type": "json_schema", "schema": {...}}`）。见 [结构化输出](/docs/zh-CN/agent-sdk/structured-outputs) 了解详情                                                                                                                                                               |
| `permission_prompt_tool_name` | `str \| None`                                                                            | `None`              | 权限提示的 MCP 工具名称                                                                                                                                                                                                                                                              |
| `cwd`                         | `str \| Path \| None`                                                                    | `None`              | 当前工作目录                                                                                                                                                                                                                                                                      |
| `cli_path`                    | `str \| Path \| None`                                                                    | `None`              | Claude Code CLI 可执行文件的自定义路径                                                                                                                                                                                                                                                 |
| `settings`                    | `str \| None`                                                                            | `None`              | 设置文件的路径                                                                                                                                                                                                                                                                     |
| `add_dirs`                    | `list[str \| Path]`                                                                      | `[]`                | Claude 可以访问的其他目录                                                                                                                                                                                                                                                            |
| `env`                         | `dict[str, str]`                                                                         | `{}`                | 环境变量合并到继承的进程环境之上。见 [环境变量](/docs/zh-CN/env-vars) 了解底层 CLI 读取的变量，以及 [处理缓慢或停滞的 API 响应](#handle-slow-or-stalled-api-responses) 了解超时相关变量                                                                                                                                              |
| `extra_args`                  | `dict[str, str \| None]`                                                                 | `{}`                | 直接传递给 CLI 的其他 CLI 参数                                                                                                                                                                                                                                                        |
| `max_buffer_size`             | `int \| None`                                                                            | `None`              | 缓冲 CLI stdout 时的最大字节数                                                                                                                                                                                                                                                       |
| `debug_stderr`                | `Any`                                                                                    | `sys.stderr`        | *已弃用* - 用于调试输出的类文件对象。改用 `stderr` 回调                                                                                                                                                                                                                                         |
| `stderr`                      | `Callable[[str], None] \| None`                                                          | `None`              | CLI 中 stderr 输出的回调函数                                                                                                                                                                                                                                                        |
| `can_use_tool`                | [`CanUseTool`](#canusetool) ` \| None`                                                   | `None`              | 工具权限回调，仅在[权限流](/docs/zh-CN/agent-sdk/permissions#how-permissions-are-evaluated)落到提示时调用。不会为 `allowed_tools` 自动批准的调用、允许规则或 `permission_mode` 调用。见 [`CanUseTool`](#canusetool) 了解详情                                                                                                 |
| `hooks`                       | `dict[HookEvent, list[HookMatcher]] \| None`                                             | `None`              | 用于拦截事件的 hooks 配置                                                                                                                                                                                                                                                            |
| `user`                        | `str \| None`                                                                            | `None`              | 用户标识符                                                                                                                                                                                                                                                                       |
| `include_partial_messages`    | `bool`                                                                                   | `False`             | 包括部分消息流式事件。启用时，会产生 [`StreamEvent`](#streamevent) 消息                                                                                                                                                                                                                         |
| `include_hook_events`         | `bool`                                                                                   | `False`             | 在消息流中包括 hooks 生命周期事件作为 `HookEventMessage` 对象                                                                                                                                                                                                                                |
| `fork_session`                | `bool`                                                                                   | `False`             | 使用 `resume` 恢复时，分叉到新会话 ID 而不是继续原始会话                                                                                                                                                                                                                                         |
| `agents`                      | `dict[str, AgentDefinition] \| None`                                                     | `None`              | 以编程方式定义的子代理                                                                                                                                                                                                                                                                 |
| `plugins`                     | `list[SdkPluginConfig]`                                                                  | `[]`                | 从本地路径加载自定义插件。见 [Plugins](/docs/zh-CN/agent-sdk/plugins) 了解详情                                                                                                                                                                                                                     |
| `sandbox`                     | [`SandboxSettings`](#sandboxsettings) ` \| None`                                         | `None`              | 以编程方式配置沙箱行为。见 [沙箱设置](#sandboxsettings) 了解详情                                                                                                                                                                                                                                 |
| `setting_sources`             | `list[SettingSource] \| None`                                                            | `None`（CLI 默认值：所有源） | 控制加载哪些文件系统设置。传递 `[]` 以禁用用户、项目和本地设置。无论如何都会加载托管策略设置；当会话使用组织凭证在[符合条件的配置](/docs/zh-CN/server-managed-settings#platform-availability)上进行身份验证时，会获取服务器管理的设置。见 [使用 Claude Code 功能](/docs/zh-CN/agent-sdk/claude-code-features#what-settingsources-does-not-control) 了解无论此选项如何都会读取的输入，以及如何禁用它们 |
| `skills`                      | `list[str] \| Literal["all"] \| None`                                                    | `None`              | 会话可用的技能。传递 `"all"` 以启用每个发现的技能，或传递技能名称列表。设置时，SDK 会自动将 Skill 工具添加到 `allowed_tools`。如果你也传递 `tools`，在该列表中包含 `"Skill"`。见 [Skills](/docs/zh-CN/agent-sdk/skills)                                                                                                                       |
| `max_thinking_tokens`         | `int \| None`                                                                            | `None`              | *已弃用* - 思考块的最大令牌数。改用 `thinking`                                                                                                                                                                                                                                             |
| `thinking`                    | [`ThinkingConfig`](#thinkingconfig) ` \| None`                                           | `None`              | 控制扩展思考行为。优先于 `max_thinking_tokens`                                                                                                                                                                                                                                          |
| `effort`                      | [`EffortLevel`](#effortlevel) ` \| None`                                                 | `None`              | 思考深度的努力级别。见 [调整努力级别](/docs/zh-CN/model-config#adjust-effort-level)                                                                                                                                                                                                               |
| `session_store`               | [`SessionStore`](/docs/zh-CN/agent-sdk/session-storage#the-sessionstore-interface) ` \| None` | `None`              | 将会话记录镜像到外部后端，以便任何主机都可以恢复它们。见 [将会话持久化到外部存储](/docs/zh-CN/agent-sdk/session-storage)                                                                                                                                                                                                |
| `session_store_flush`         | `Literal["batched", "eager"]`                                                            | `"batched"`         | 何时将镜像的记录条目刷新到 `session_store`。`"batched"` 每轮刷新一次或当缓冲区填满时；`"eager"` 在每帧后触发后台刷新。当 `session_store` 为 `None` 时忽略                                                                                                                                                                |

<h4 id="handle-slow-or-stalled-api-responses">
  处理缓慢或停滞的 API 响应
</h4>

CLI 子进程读取多个环境变量，这些变量控制 API 超时和停滞检测。通过 `ClaudeAgentOptions.env` 传递它们：

```python theme={null}
options = ClaudeAgentOptions(
    env={
        "API_TIMEOUT_MS": "120000",
        "CLAUDE_CODE_MAX_RETRIES": "2",
        "CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS": "120000",
    },
)
```

* `API_TIMEOUT_MS`：Anthropic 客户端上的每个请求超时，以毫秒为单位。默认 `600000`。适用于主循环和所有子代理。
* `CLAUDE_CODE_MAX_RETRIES`：最大 API 重试次数。默认 `10`，上限为 `15`。每次重试都有自己的 `API_TIMEOUT_MS` 窗口，因此最坏情况下的实际时间大约是 `API_TIMEOUT_MS × (CLAUDE_CODE_MAX_RETRIES + 1)` 加上退避。对于需要等待更长时间中断的无人值守运行，设置 `CLAUDE_CODE_RETRY_WATCHDOG=1`：它无限期重试容量错误，自 Claude Code v2.1.199 起，对其他瞬时错误将默认值提高到 `300` 并移除此变量的上限。
* `CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS`：使用 `run_in_background` 启动的子代理的停滞监视器。默认 `600000`。在每个流事件时重置；停滞时中止子代理，将任务标记为失败，并将错误与任何部分结果一起呈现给父代理。不适用于同步子代理。
* `CLAUDE_ENABLE_STREAM_WATCHDOG` 与 `CLAUDE_STREAM_IDLE_TIMEOUT_MS`：当标头已到达但响应体停止流式传输时中止请求。监视器对所有提供商默认启用；设置 `CLAUDE_ENABLE_STREAM_WATCHDOG=0` 以禁用它。`CLAUDE_STREAM_IDLE_TIMEOUT_MS` 默认为 `300000` 并被限制为该最小值。中止的请求通过正常重试路径进行。

<h3 id="outputformat">
  `OutputFormat`
</h3>

结构化输出验证的配置。将其作为 `dict` 传递给 `ClaudeAgentOptions` 上的 `output_format` 字段：

```python theme={null}
# Expected dict shape for output_format
{
    "type": "json_schema",
    "schema": {...},  # Your JSON Schema definition
}
```

| 字段       | 必需 | 描述                                    |
| :------- | :- | :------------------------------------ |
| `type`   | 是  | 必须是 `"json_schema"` 用于 JSON Schema 验证 |
| `schema` | 是  | 用于输出验证的 JSON Schema 定义                |

<h3 id="systempromptpreset">
  `SystemPromptPreset`
</h3>

使用 Claude Code 的预设系统提示和可选添加的配置。

```python theme={null}
class SystemPromptPreset(TypedDict):
    type: Literal["preset"]
    preset: Literal["claude_code"]
    append: NotRequired[str]
    exclude_dynamic_sections: NotRequired[bool]
```

| 字段                         | 必需 | 描述                                                                                                                                                                |
| :------------------------- | :- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `type`                     | 是  | 必须是 `"preset"` 以使用预设系统提示                                                                                                                                          |
| `preset`                   | 是  | 必须是 `"claude_code"` 以使用 Claude Code 的系统提示                                                                                                                         |
| `append`                   | 否  | 要追加到预设系统提示的其他说明                                                                                                                                                   |
| `exclude_dynamic_sections` | 否  | 将每个会话的上下文（如工作目录、git 状态和内存路径）从系统提示移到第一条用户消息。改进跨用户和机器的提示缓存重用。见 [修改系统提示](/docs/zh-CN/agent-sdk/modifying-system-prompts#improve-prompt-caching-across-users-and-machines) |

<h3 id="systempromptfile">
  `SystemPromptFile`
</h3>

从文件加载自定义系统提示而不是作为字符串传递的配置。SDK 将其映射到 CLI [`--system-prompt-file`](/docs/zh-CN/cli-reference#system-prompt-flags) 标志。当提示很大时使用文件形式：SDK 在 CLI 子进程 argv 上传递字符串 `system_prompt`，这受到 OS 命令行长度限制的限制，然后 SDK 才能发送任何 API 请求。在 Linux 上，单个参数长于大约 128 KB 会在进程生成时失败，出现 `Argument list too long`。在 Windows 上，整个命令行被限制为大约 32 KB，因此字符串形式在更低的阈值处失败。

```python theme={null}
class SystemPromptFile(TypedDict):
    type: Literal["file"]
    path: str
```

| 字段     | 必需 | 描述                    |
| :----- | :- | :-------------------- |
| `type` | 是  | 必须是 `"file"` 以从磁盘加载提示 |
| `path` | 是  | 包含系统提示的文件的路径          |

<h3 id="settingsource">
  `SettingSource`
</h3>

控制 SDK 从哪些基于文件系统的配置源加载设置。

```python theme={null}
SettingSource = Literal["user", "project", "local"]
```

| 值           | 描述                 | 位置                            |
| :---------- | :----------------- | :---------------------------- |
| `"user"`    | 全局用户设置             | `~/.claude/settings.json`     |
| `"project"` | 共享项目设置（版本控制）       | `.claude/settings.json`       |
| `"local"`   | 本地项目设置（gitignored） | `.claude/settings.local.json` |

<h4 id="default-behavior">
  默认行为
</h4>

当 `setting_sources` 被省略或为 `None` 时，`query()` 加载与 Claude Code CLI 相同的文件系统设置：用户、项目和本地。无论如何都会加载托管策略设置；当会话使用组织凭证在[符合条件的配置](/docs/zh-CN/server-managed-settings#platform-availability)上进行身份验证时，会获取服务器管理的设置。见 [settingSources 不控制什么](/docs/zh-CN/agent-sdk/claude-code-features#what-settingsources-does-not-control) 了解无论此选项如何都会读取的输入，以及如何禁用它们。

<h4 id="why-use-setting_sources">
  为什么使用 setting\_sources
</h4>

**禁用文件系统设置：**

```python theme={null}
# Do not load user, project, or local settings from disk
from claude_agent_sdk import query, ClaudeAgentOptions

async for message in query(
    prompt="Analyze this code",
    options=ClaudeAgentOptions(
        setting_sources=[]
    ),
):
    print(message)
```

<Note>
  在 Python SDK 0.1.59 及更早版本中，空列表的处理方式与省略选项相同，因此 `setting_sources=[]` 不会禁用文件系统设置。如果你需要空列表生效，请升级到较新版本。TypeScript SDK 不受影响。
</Note>

**显式加载所有文件系统设置：**

```python theme={null}
from claude_agent_sdk import query, ClaudeAgentOptions

async for message in query(
    prompt="Analyze this code",
    options=ClaudeAgentOptions(
        setting_sources=["user", "project", "local"]
    ),
):
    print(message)
```

**仅加载特定设置源：**

```python theme={null}
# Load only project settings, ignore user and local
async for message in query(
    prompt="Run CI checks",
    options=ClaudeAgentOptions(
        setting_sources=["project"]  # Only .claude/settings.json
    ),
):
    print(message)
```

**测试和 CI 环境：**

```python theme={null}
# Ensure consistent behavior in CI by excluding local settings
async for message in query(
    prompt="Run tests",
    options=ClaudeAgentOptions(
        setting_sources=["project"],  # Only team-shared settings
        permission_mode="bypassPermissions",
    ),
):
    print(message)
```

**仅 SDK 应用程序：**

```python theme={null}
# Define everything programmatically.
# Pass [] to opt out of filesystem setting sources.
async for message in query(
    prompt="Review this PR",
    options=ClaudeAgentOptions(
        setting_sources=[],
        agents={...},
        mcp_servers={...},
        allowed_tools=["Read", "Grep", "Glob"],
    ),
):
    print(message)
```

**加载 CLAUDE.md 项目说明：**

```python theme={null}
# Load project settings to include CLAUDE.md files
async for message in query(
    prompt="Add a new feature following project conventions",
    options=ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",  # Use Claude Code's system prompt
        },
        setting_sources=["project"],  # Loads CLAUDE.md from project
        allowed_tools=["Read", "Write", "Edit"],
    ),
):
    print(message)
```

<h4 id="settings-precedence">
  设置优先级
</h4>

加载多个源时，设置按此优先级合并（从高到低）：

1. 本地设置（`.claude/settings.local.json`）
2. 项目设置（`.claude/settings.json`）
3. 用户设置（`~/.claude/settings.json`）

编程选项（如 `agents` 和 `allowed_tools`）覆盖用户、项目和本地文件系统设置。托管策略设置优先于编程选项。

<h3 id="agentdefinition">
  `AgentDefinition`
</h3>

以编程方式定义的子代理的配置。

```python theme={null}
@dataclass
class AgentDefinition:
    description: str
    prompt: str
    tools: list[str] | None = None
    disallowedTools: list[str] | None = None
    model: str | None = None
    skills: list[str] | None = None
    memory: Literal["user", "project", "local"] | None = None
    mcpServers: list[str | dict[str, Any]] | None = None
    initialPrompt: str | None = None
    maxTurns: int | None = None
    background: bool | None = None
    effort: EffortLevel | int | None = None
    permissionMode: PermissionMode | None = None
```

| 字段                | 必需 | 描述                                                                                                          |
| :---------------- | :- | :---------------------------------------------------------------------------------------------------------- |
| `description`     | 是  | 何时使用此代理的自然语言描述                                                                                              |
| `prompt`          | 是  | 代理的系统提示                                                                                                     |
| `tools`           | 否  | 允许的工具名称数组。如果省略，继承所有工具                                                                                       |
| `disallowedTools` | 否  | 要从代理的工具集中移除的工具名称数组。也接受 MCP 服务器级别的模式：`mcp__server` 或 `mcp__server__*` 移除该服务器的每个工具，`mcp__*` 移除任何服务器的每个 MCP 工具 |
| `model`           | 否  | 此代理的模型覆盖。接受别名如 `"sonnet"`、`"opus"`、`"haiku"` 或 `"inherit"`，或完整模型 ID。如果省略，使用主模型                              |
| `skills`          | 否  | 此代理可用的技能名称列表                                                                                                |
| `memory`          | 否  | 此代理的内存源：`"user"`、`"project"` 或 `"local"`                                                                    |
| `mcpServers`      | 否  | 此代理可用的 MCP 服务器。每个条目是服务器名称或内联 `{name: config}` 字典                                                            |
| `initialPrompt`   | 否  | 当此代理作为主线程代理运行时自动提交为第一个用户轮次                                                                                  |
| `maxTurns`        | 否  | 代理停止前的最大代理轮次数                                                                                               |
| `background`      | 否  | 调用时将此代理作为非阻塞后台任务运行                                                                                          |
| `effort`          | 否  | 此代理的推理努力级别。接受命名级别或整数。见 [`EffortLevel`](#effortlevel)                                                        |
| `permissionMode`  | 否  | 此代理内工具执行的权限模式。见 [`PermissionMode`](#permissionmode)                                                         |

<Note>
  `AgentDefinition` 字段名称使用 camelCase，如 `disallowedTools`、`permissionMode` 和 `maxTurns`。这些名称直接映射到与 TypeScript SDK 共享的线路格式。这与 `ClaudeAgentOptions` 不同，后者对等效的顶级字段（如 `disallowed_tools` 和 `permission_mode`）使用 Python snake\_case。因为 `AgentDefinition` 是数据类，传递 snake\_case 关键字在构造时会引发 `TypeError`。
</Note>

<h3 id="permissionmode">
  `PermissionMode`
</h3>

用于控制工具执行的权限模式。

```python theme={null}
PermissionMode = Literal[
    "default",  # Standard permission behavior
    "acceptEdits",  # Auto-accept file edits
    "plan",  # Planning mode - explore without editing
    "dontAsk",  # Deny anything not pre-approved instead of prompting
    "bypassPermissions",  # Bypass permission checks; explicit ask rules still prompt (use with caution)
    "auto",  # A model classifier approves or denies each tool call
]
```

<h3 id="effortlevel">
  `EffortLevel`
</h3>

用于指导思考深度的努力级别。

```python theme={null}
EffortLevel = Literal[
    "low",  # Minimal thinking, fastest responses
    "medium",  # Moderate thinking
    "high",  # Deep reasoning
    "xhigh",  # Extended reasoning; falls back to "high" on models that don't support it
    "max",  # Maximum effort
]
```

<h3 id="canusetool">
  `CanUseTool`
</h3>

工具权限回调函数的类型别名。

```python theme={null}
CanUseTool = Callable[
    [str, dict[str, Any], ToolPermissionContext], Awaitable[PermissionResult]
]
```

回调接收：

* `tool_name`：被调用的工具的名称
* `input_data`：工具的输入参数
* `context`：带有附加信息的 `ToolPermissionContext`

返回 `PermissionResult`（`PermissionResultAllow` 或 `PermissionResultDeny`）。

回调是 SDK 对交互式权限提示的替代：它仅在[权限评估流](/docs/zh-CN/agent-sdk/permissions#how-permissions-are-evaluated)解析为提示时调用。已由 `allowed_tools` 条目、设置允许规则或权限模式（如 `acceptEdits` 或 `bypassPermissions`）批准的工具调用永远不会调用它。要限制每个工具调用，改用 [`PreToolUse` hook](/docs/zh-CN/agent-sdk/hooks)。

`AskUserQuestion`、标记为 [`requiresUserInteraction`](/docs/zh-CN/mcp#require-approval-for-a-specific-tool) 的 MCP 工具，以及你的组织[设置为 `ask`](/docs/zh-CN/mcp#organization-controls-on-connector-tools) 的连接器工具即使允许规则匹配也会到达回调。在 `dontAsk` 模式下，这些调用被拒绝，不调用回调。

<h3 id="toolpermissioncontext">
  `ToolPermissionContext`
</h3>

传递给工具权限回调的上下文信息。

```python theme={null}
@dataclass
class ToolPermissionContext:
    signal: Any | None = None  # Future: abort signal support
    suggestions: list[PermissionUpdate] = field(default_factory=list)
    blocked_path: str | None = None
    decision_reason: str | None = None
    title: str | None = None
    display_name: str | None = None
    description: str | None = None
```

| 字段                | 类型                       | 描述                                                                                                                            |
| :---------------- | :----------------------- | :---------------------------------------------------------------------------------------------------------------------------- |
| `signal`          | `Any \| None`            | 保留供将来中止信号支持                                                                                                                   |
| `suggestions`     | `list[PermissionUpdate]` | 来自 CLI 的权限更新建议。Bash 提示包括带有 `localSettings` 目标的建议，因此在 `updated_permissions` 中返回它会将规则写入 `.claude/settings.local.json` 并在会话间持久化。 |
| `blocked_path`    | `str \| None`            | 触发权限请求的文件路径（如适用）。例如，当 Bash 命令尝试访问允许目录外的路径时                                                                                    |
| `decision_reason` | `str \| None`            | 触发此权限请求的原因。从 PreToolUse hooks 的 `permissionDecisionReason` 转发，当 hooks 返回 `"ask"` 时                                            |
| `title`           | `str \| None`            | 完整权限提示句子，如 `Claude wants to read foo.txt`。存在时用作主要提示文本                                                                         |
| `display_name`    | `str \| None`            | 工具操作的短名词短语，如 `Read file`，适合按钮标签                                                                                               |
| `description`     | `str \| None`            | 权限 UI 的人类可读副标题                                                                                                                |

<h3 id="permissionresult">
  `PermissionResult`
</h3>

权限回调结果的联合类型。

```python theme={null}
PermissionResult = PermissionResultAllow | PermissionResultDeny
```

<h3 id="permissionresultallow">
  `PermissionResultAllow`
</h3>

指示应允许工具调用的结果。

```python theme={null}
@dataclass
class PermissionResultAllow:
    behavior: Literal["allow"] = "allow"
    updated_input: dict[str, Any] | None = None
    updated_permissions: list[PermissionUpdate] | None = None
```

| 字段                    | 类型                               | 默认值       | 描述                |
| :-------------------- | :------------------------------- | :-------- | :---------------- |
| `behavior`            | `Literal["allow"]`               | `"allow"` | 必须是 "allow"       |
| `updated_input`       | `dict[str, Any] \| None`         | `None`    | 要使用的修改后的输入而不是原始输入 |
| `updated_permissions` | `list[PermissionUpdate] \| None` | `None`    | 要应用的权限更新          |

<h3 id="permissionresultdeny">
  `PermissionResultDeny`
</h3>

指示应拒绝工具调用的结果。

```python theme={null}
@dataclass
class PermissionResultDeny:
    behavior: Literal["deny"] = "deny"
    message: str = ""
    interrupt: bool = False
```

| 字段          | 类型                | 默认值      | 描述           |
| :---------- | :---------------- | :------- | :----------- |
| `behavior`  | `Literal["deny"]` | `"deny"` | 必须是 "deny"   |
| `message`   | `str`             | `""`     | 解释为什么拒绝工具的消息 |
| `interrupt` | `bool`            | `False`  | 是否中断当前执行     |

<h3 id="permissionupdate">
  `PermissionUpdate`
</h3>

用于以编程方式更新权限的配置。

```python theme={null}
@dataclass
class PermissionUpdate:
    type: Literal[
        "addRules",
        "replaceRules",
        "removeRules",
        "setMode",
        "addDirectories",
        "removeDirectories",
    ]
    rules: list[PermissionRuleValue] | None = None
    behavior: Literal["allow", "deny", "ask"] | None = None
    mode: PermissionMode | None = None
    directories: list[str] | None = None
    destination: (
        Literal["userSettings", "projectSettings", "localSettings", "session"] | None
    ) = None
```

| 字段            | 类型                                        | 描述              |
| :------------ | :---------------------------------------- | :-------------- |
| `type`        | `Literal[...]`                            | 权限更新操作的类型       |
| `rules`       | `list[PermissionRuleValue] \| None`       | 用于添加/替换/移除操作的规则 |
| `behavior`    | `Literal["allow", "deny", "ask"] \| None` | 基于规则的操作的行为      |
| `mode`        | `PermissionMode \| None`                  | setMode 操作的模式   |
| `directories` | `list[str] \| None`                       | 用于添加/移除目录操作的目录  |
| `destination` | `Literal[...] \| None`                    | 应用权限更新的位置       |

<h3 id="permissionrulevalue">
  `PermissionRuleValue`
</h3>

要在权限更新中添加、替换或移除的规则。

```python theme={null}
@dataclass
class PermissionRuleValue:
    tool_name: str
    rule_content: str | None = None
```

<h3 id="toolspreset">
  `ToolsPreset`
</h3>

使用 Claude Code 的默认工具集的预设工具配置。

```python theme={null}
class ToolsPreset(TypedDict):
    type: Literal["preset"]
    preset: Literal["claude_code"]
```

<h3 id="thinkingconfig">
  `ThinkingConfig`
</h3>

控制扩展思考行为。三种配置的联合：

```python theme={null}
ThinkingDisplay = Literal["summarized", "omitted"]


class ThinkingConfigAdaptive(TypedDict):
    type: Literal["adaptive"]
    display: NotRequired[ThinkingDisplay]


class ThinkingConfigEnabled(TypedDict):
    type: Literal["enabled"]
    budget_tokens: int
    display: NotRequired[ThinkingDisplay]


class ThinkingConfigDisabled(TypedDict):
    type: Literal["disabled"]


ThinkingConfig = ThinkingConfigAdaptive | ThinkingConfigEnabled | ThinkingConfigDisabled
```

| 变体         | 字段                                 | 描述               |
| :--------- | :--------------------------------- | :--------------- |
| `adaptive` | `type`, `display`                  | Claude 自适应决定何时思考 |
| `enabled`  | `type`, `budget_tokens`, `display` | 启用具有特定令牌预算的思考    |
| `disabled` | `type`                             | 禁用思考             |

可选的 `display` 字段控制思考文本是否返回为 `"summarized"` 或 `"omitted"`。在 Claude Opus 4.7 及更高版本上，API 默认值为 `"omitted"`，因此设置 `"summarized"` 以在 [`ThinkingBlock`](#thinkingblock) 输出中接收思考内容。

因为这些是 `TypedDict` 类，它们在运行时是普通字典。要么将它们构造为字典字面量，要么调用类作为构造函数；两者都产生 `dict`。使用 `config["budget_tokens"]` 访问字段，而不是 `config.budget_tokens`：

```python theme={null}
from claude_agent_sdk import ClaudeAgentOptions, ThinkingConfigEnabled

# Option 1: dict literal (recommended, no import needed)
options = ClaudeAgentOptions(thinking={"type": "enabled", "budget_tokens": 20000})

# Option 2: constructor-style (returns a plain dict)
config = ThinkingConfigEnabled(type="enabled", budget_tokens=20000)
print(config["budget_tokens"])  # 20000
# config.budget_tokens would raise AttributeError
```

<h3 id="sdkbeta">
  `SdkBeta`
</h3>

SDK 测试功能的字面类型。

```python theme={null}
SdkBeta = Literal["context-1m-2025-08-07"]
```

与 `ClaudeAgentOptions` 中的 `betas` 字段一起使用以启用测试功能。

<Warning>
  `context-1m-2025-08-07` 测试版自 2026 年 4 月 30 日起已停用。使用 Claude Sonnet 4.5 或 Sonnet 4 传递此标头无效，超过标准 200k 令牌上下文窗口的请求返回错误。要使用 1M 令牌上下文窗口，请迁移到 [Claude Sonnet 5、Claude Sonnet 4.6、Claude Opus 4.6、Claude Opus 4.7 或 Claude Opus 4.8](https://platform.claude.com/docs/en/about-claude/models/overview)，它们以标准定价包括 1M 上下文，无需测试版标头。
</Warning>

<h3 id="mcpsdkserverconfig">
  `McpSdkServerConfig`
</h3>

使用 `create_sdk_mcp_server()` 创建的 SDK MCP 服务器的配置。

```python theme={null}
class McpSdkServerConfig(TypedDict):
    type: Literal["sdk"]
    name: str
    instance: Any  # MCP Server instance
```

<h3 id="mcpserverconfig">
  `McpServerConfig`
</h3>

MCP 服务器配置的联合类型。

```python theme={null}
McpServerConfig = (
    McpStdioServerConfig | McpSSEServerConfig | McpHttpServerConfig | McpSdkServerConfig
)
```

<h4 id="mcpstdioserverconfig">
  `McpStdioServerConfig`
</h4>

```python theme={null}
class McpStdioServerConfig(TypedDict):
    type: NotRequired[Literal["stdio"]]  # Optional for backwards compatibility
    command: str
    args: NotRequired[list[str]]
    env: NotRequired[dict[str, str]]
```

<h4 id="mcpsseserverconfig">
  `McpSSEServerConfig`
</h4>

```python theme={null}
class McpSSEServerConfig(TypedDict):
    type: Literal["sse"]
    url: str
    headers: NotRequired[dict[str, str]]
```

<h4 id="mcphttpserverconfig">
  `McpHttpServerConfig`
</h4>

```python theme={null}
class McpHttpServerConfig(TypedDict):
    type: Literal["http"]
    url: str
    headers: NotRequired[dict[str, str]]
```

<h3 id="mcpserverstatusconfig">
  `McpServerStatusConfig`
</h3>

由 [`get_mcp_status()`](#methods) 报告的 MCP 服务器的配置。这是所有 [`McpServerConfig`](#mcpserverconfig) 传输变体加上用于通过 claude.ai 代理的服务器的仅输出 `claudeai-proxy` 变体的联合。

```python theme={null}
McpServerStatusConfig = (
    McpStdioServerConfig
    | McpSSEServerConfig
    | McpHttpServerConfig
    | McpSdkServerConfigStatus
    | McpClaudeAIProxyServerConfig
)
```

`McpSdkServerConfigStatus` 是 [`McpSdkServerConfig`](#mcpsdkserverconfig) 的可序列化形式，仅包含 `type`（`"sdk"`）和 `name`（`str`）字段；进程内 `instance` 被省略。`McpClaudeAIProxyServerConfig` 具有 `type`（`"claudeai-proxy"`）、`url`（`str`）和 `id`（`str`）字段。

<h3 id="mcpstatusresponse">
  `McpStatusResponse`
</h3>

来自 [`ClaudeSDKClient.get_mcp_status()`](#methods) 的响应。在 `mcpServers` 键下包装服务器状态列表。

```python theme={null}
class McpStatusResponse(TypedDict):
    mcpServers: list[McpServerStatus]
```

<h3 id="mcpserverstatus">
  `McpServerStatus`
</h3>

连接的 MCP 服务器的状态，包含在 [`McpStatusResponse`](#mcpstatusresponse) 中。

```python theme={null}
class McpServerStatus(TypedDict):
    name: str
    status: McpServerConnectionStatus  # "connected" | "failed" | "needs-auth" | "pending" | "disabled"
    serverInfo: NotRequired[McpServerInfo]
    error: NotRequired[str]
    config: NotRequired[McpServerStatusConfig]
    scope: NotRequired[str]
    tools: NotRequired[list[McpToolInfo]]
```

| 字段           | 类型                                                    | 描述                                                                                                                  |
| :----------- | :---------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------ |
| `name`       | `str`                                                 | 服务器名称                                                                                                               |
| `status`     | `str`                                                 | `"connected"`、`"failed"`、`"needs-auth"`、`"pending"` 或 `"disabled"` 之一                                               |
| `serverInfo` | `dict`（可选）                                            | 服务器名称和版本（`{"name": str, "version": str}`）                                                                           |
| `error`      | `str`（可选）                                             | 服务器连接失败时的错误消息                                                                                                       |
| `config`     | [`McpServerStatusConfig`](#mcpserverstatusconfig)（可选） | 服务器配置。与 [`McpServerConfig`](#mcpserverconfig) 形状相同（stdio、SSE、HTTP 或 SDK），加上通过 claude.ai 连接的服务器的 `claudeai-proxy` 变体 |
| `scope`      | `str`（可选）                                             | 配置范围                                                                                                                |
| `tools`      | `list`（可选）                                            | 此服务器提供的工具，每个都有 `name`、`description` 和 `annotations` 字段                                                              |

<h3 id="sdkpluginconfig">
  `SdkPluginConfig`
</h3>

SDK 中加载插件的配置。

```python theme={null}
class SdkPluginConfig(TypedDict):
    type: Literal["local"]
    path: str
```

| 字段     | 类型                 | 描述                       |
| :----- | :----------------- | :----------------------- |
| `type` | `Literal["local"]` | 必须是 `"local"`（目前仅支持本地插件） |
| `path` | `str`              | 插件目录的绝对或相对路径             |

**示例：**

```python theme={null}
plugins = [
    {"type": "local", "path": "./my-plugin"},
    {"type": "local", "path": "/absolute/path/to/plugin"},
]
```

有关创建和使用插件的完整信息，见 [Plugins](/docs/zh-CN/agent-sdk/plugins)。

<h2 id="message-types">
  消息类型
</h2>

<h3 id="message">
  `Message`
</h3>

所有可能消息的联合类型。

```python theme={null}
Message = (
    UserMessage
    | AssistantMessage
    | SystemMessage
    | ResultMessage
    | StreamEvent
    | RateLimitEvent
)
```

<h3 id="usermessage">
  `UserMessage`
</h3>

用户输入消息。

```python theme={null}
@dataclass
class UserMessage:
    content: str | list[ContentBlock]
    uuid: str | None = None
    parent_tool_use_id: str | None = None
    tool_use_result: dict[str, Any] | None = None
```

| 字段                   | 类型                          | 描述                     |
| :------------------- | :-------------------------- | :--------------------- |
| `content`            | `str \| list[ContentBlock]` | 消息内容为文本或内容块            |
| `uuid`               | `str \| None`               | 唯一消息标识符                |
| `parent_tool_use_id` | `str \| None`               | 如果此消息是工具结果响应，则为工具使用 ID |
| `tool_use_result`    | `dict[str, Any] \| None`    | 工具结果数据（如果适用）           |

<h3 id="assistantmessage">
  `AssistantMessage`
</h3>

带有内容块的助手响应消息。

```python theme={null}
@dataclass
class AssistantMessage:
    content: list[ContentBlock]
    model: str
    parent_tool_use_id: str | None = None
    error: AssistantMessageError | None = None
    usage: dict[str, Any] | None = None
    message_id: str | None = None
```

| 字段                   | 类型                                                           | 描述                                                          |
| :------------------- | :----------------------------------------------------------- | :---------------------------------------------------------- |
| `content`            | `list[ContentBlock]`                                         | 响应中的内容块列表                                                   |
| `model`              | `str`                                                        | 生成响应的模型                                                     |
| `parent_tool_use_id` | `str \| None`                                                | 如果这是嵌套响应，则为工具使用 ID                                          |
| `error`              | [`AssistantMessageError`](#assistantmessageerror) ` \| None` | 如果响应遇到错误，则为错误类型                                             |
| `usage`              | `dict[str, Any] \| None`                                     | 每条消息的令牌使用情况（与 [`ResultMessage.usage`](#resultmessage) 相同的键） |
| `message_id`         | `str \| None`                                                | API 消息 ID。来自一个轮次的多条消息共享相同的 ID                               |

<h3 id="assistantmessageerror">
  `AssistantMessageError`
</h3>

助手消息的可能错误类型。

```python theme={null}
AssistantMessageError = Literal[
    "authentication_failed",
    "billing_error",
    "rate_limit",
    "invalid_request",
    "server_error",
    "max_output_tokens",
    "unknown",
]
```

<h3 id="systemmessage">
  `SystemMessage`
</h3>

带有元数据的系统消息。

```python theme={null}
@dataclass
class SystemMessage:
    subtype: str
    data: dict[str, Any]
```

<h3 id="resultmessage">
  `ResultMessage`
</h3>

带有成本和使用信息的最终结果消息。

```python theme={null}
@dataclass
class ResultMessage:
    subtype: str
    duration_ms: int
    duration_api_ms: int
    is_error: bool
    num_turns: int
    session_id: str
    stop_reason: str | None = None
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    result: str | None = None
    structured_output: Any = None
    model_usage: dict[str, Any] | None = None
    permission_denials: list[Any] | None = None
    deferred_tool_use: DeferredToolUse | None = None
    errors: list[str] | None = None
    api_error_status: int | None = None
    uuid: str | None = None
```

`subtype` 字段确定填充哪些其他字段。它是 `"success"`、`"error_during_execution"`、`"error_max_turns"`、`"error_max_budget_usd"` 或 `"error_max_structured_output_retries"` 之一。Python 数据类将所有变体展平为一种形状，因此不适用于返回的子类型的字段为 `None`。

当对话以错误结束时，多个字段会携带诊断详情：

* `is_error`：当对话以错误状态结束时为 `True`。在 `error_*` 子类型上始终为 `True`。在 `subtype="success"` 上，当最终模型请求失败时为 `True`，这意味着代理循环完成但最后一个 API 调用返回了错误。
* `api_error_status`：终止 API 错误的 HTTP 状态代码。当轮次结束时没有错误时为 `None`。仅在 `subtype="success"` 上填充。
* `result`：在 `subtype="success"` 上为最终助手消息的文本，或在 `error_*` 子类型上为 `None`。当 `subtype="success"` 且 `is_error=True` 时，如果可用，此字段保存 API 错误字符串，但可能为空，因此请检查 `api_error_status` 和前面的 `AssistantMessage` 内容以获取详情。
* `errors`：循环级别的错误字符串，例如最大轮次消息。仅在 `error_*` 子类型上填充。

`usage` 字典在存在时包含以下键：

| 键                             | 类型    | 描述                                                                                                                |
| ----------------------------- | ----- | ----------------------------------------------------------------------------------------------------------------- |
| `input_tokens`                | `int` | 顶级代理循环消耗的输入令牌。[子代理令牌不包括在内](/docs/zh-CN/agent-sdk/cost-tracking#get-the-total-cost-of-a-query)；使用 `model_usage` 进行整树计费。 |
| `output_tokens`               | `int` | 顶级代理循环生成的输出令牌。子代理令牌不包括在内。                                                                                         |
| `cache_creation_input_tokens` | `int` | 用于创建新缓存条目的令牌。                                                                                                     |
| `cache_read_input_tokens`     | `int` | 从现有缓存条目读取的令牌。                                                                                                     |

`model_usage` 字典将模型名称映射到每个模型的使用情况。内部字典键使用 camelCase，因为该值从底层 CLI 进程未修改地传递，匹配 TypeScript [`ModelUsage`](/docs/zh-CN/agent-sdk/typescript#modelusage) 类型：

| 键                          | 类型      | 描述                                                                       |
| -------------------------- | ------- | ------------------------------------------------------------------------ |
| `inputTokens`              | `int`   | 此模型的输入令牌。                                                                |
| `outputTokens`             | `int`   | 此模型的输出令牌。                                                                |
| `cacheReadInputTokens`     | `int`   | 此模型的缓存读取令牌。                                                              |
| `cacheCreationInputTokens` | `int`   | 此模型的缓存创建令牌。                                                              |
| `webSearchRequests`        | `int`   | 此模型进行的网络搜索请求。                                                            |
| `costUSD`                  | `float` | 此模型的估计成本（美元），客户端计算。见 [跟踪成本和使用](/docs/zh-CN/agent-sdk/cost-tracking) 了解计费注意事项。 |
| `contextWindow`            | `int`   | 此模型的上下文窗口大小。                                                             |
| `maxOutputTokens`          | `int`   | 此模型的最大输出令牌限制。                                                            |

<h3 id="streamevent">
  `StreamEvent`
</h3>

流式事件，用于流式传输期间的部分消息更新。仅在 `ClaudeAgentOptions` 中 `include_partial_messages=True` 时接收。通过 `from claude_agent_sdk.types import StreamEvent` 导入。

```python theme={null}
@dataclass
class StreamEvent:
    uuid: str
    session_id: str
    event: dict[str, Any]  # The raw Claude API stream event
    parent_tool_use_id: str | None = None
```

| 字段                   | 类型               | 描述                                                                               |
| :------------------- | :--------------- | :------------------------------------------------------------------------------- |
| `uuid`               | `str`            | 此事件的唯一标识符                                                                        |
| `session_id`         | `str`            | 会话标识符                                                                            |
| `event`              | `dict[str, Any]` | 原始 Claude API 流事件数据                                                              |
| `parent_tool_use_id` | `str \| None`    | 始终为 `None`。流事件仅为主会话发出。对于子代理归属，请使用完整消息，例如 [`AssistantMessage`](#assistantmessage) |

<h3 id="ratelimitevent">
  `RateLimitEvent`
</h3>

当速率限制状态更改时发出（例如，从 `"allowed"` 到 `"allowed_warning"`）。使用此来在用户达到硬限制之前警告他们，或在状态为 `"rejected"` 时退避。

```python theme={null}
@dataclass
class RateLimitEvent:
    rate_limit_info: RateLimitInfo
    uuid: str
    session_id: str
```

| 字段                | 类型                                | 描述       |
| :---------------- | :-------------------------------- | :------- |
| `rate_limit_info` | [`RateLimitInfo`](#ratelimitinfo) | 当前速率限制状态 |
| `uuid`            | `str`                             | 唯一事件标识符  |
| `session_id`      | `str`                             | 会话标识符    |

<h3 id="ratelimitinfo">
  `RateLimitInfo`
</h3>

由 [`RateLimitEvent`](#ratelimitevent) 携带的速率限制状态。

```python theme={null}
RateLimitStatus = Literal["allowed", "allowed_warning", "rejected"]
RateLimitType = Literal[
    "five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet", "overage"
]


@dataclass
class RateLimitInfo:
    status: RateLimitStatus
    resets_at: int | None = None
    rate_limit_type: RateLimitType | None = None
    utilization: float | None = None
    overage_status: RateLimitStatus | None = None
    overage_resets_at: int | None = None
    overage_disabled_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
```

| 字段                        | 类型                        | 描述                                                  |
| :------------------------ | :------------------------ | :-------------------------------------------------- |
| `status`                  | `RateLimitStatus`         | 当前状态。`"allowed_warning"` 表示接近限制；`"rejected"` 表示达到限制 |
| `resets_at`               | `int \| None`             | 速率限制窗口重置的 Unix 时间戳                                  |
| `rate_limit_type`         | `RateLimitType \| None`   | 哪个速率限制窗口适用                                          |
| `utilization`             | `float \| None`           | 消耗的速率限制的分数（0.0 到 1.0）                               |
| `overage_status`          | `RateLimitStatus \| None` | 按需付费超额使用的状态（如果适用）                                   |
| `overage_resets_at`       | `int \| None`             | 超额窗口重置的 Unix 时间戳                                    |
| `overage_disabled_reason` | `str \| None`             | 为什么超额不可用，如果状态为 `"rejected"`                         |
| `raw`                     | `dict[str, Any]`          | 来自 CLI 的完整原始字典，包括上面未建模的字段                           |

<h3 id="taskstartedmessage">
  `TaskStartedMessage`
</h3>

当后台任务启动时发出。后台任务是在主轮次之外跟踪的任何内容：后台 Bash 命令、[Monitor](#monitor) 监视、通过 Agent 工具生成的子代理或远程代理。`task_type` 字段告诉你是哪一个。此命名与 `Task` 到 `Agent` 工具重命名无关。

```python theme={null}
@dataclass
class TaskStartedMessage(SystemMessage):
    task_id: str
    description: str
    uuid: str
    session_id: str
    tool_use_id: str | None = None
    task_type: str | None = None
```

| 字段            | 类型            | 描述                                                                              |
| :------------ | :------------ | :------------------------------------------------------------------------------ |
| `task_id`     | `str`         | 任务的唯一标识符                                                                        |
| `description` | `str`         | 任务的描述                                                                           |
| `uuid`        | `str`         | 唯一消息标识符                                                                         |
| `session_id`  | `str`         | 会话标识符                                                                           |
| `tool_use_id` | `str \| None` | 关联的工具使用 ID                                                                      |
| `task_type`   | `str \| None` | 哪种后台任务：`"local_bash"` 用于后台 Bash 和 Monitor 监视，`"local_agent"` 或 `"remote_agent"` |

<h3 id="taskusage">
  `TaskUsage`
</h3>

后台任务的令牌和计时数据。

```python theme={null}
class TaskUsage(TypedDict):
    total_tokens: int
    tool_uses: int
    duration_ms: int
```

<h3 id="taskprogressmessage">
  `TaskProgressMessage`
</h3>

定期为运行的后台任务发出进度更新。

```python theme={null}
@dataclass
class TaskProgressMessage(SystemMessage):
    task_id: str
    description: str
    usage: TaskUsage
    uuid: str
    session_id: str
    tool_use_id: str | None = None
    last_tool_name: str | None = None
```

| 字段               | 类型            | 描述             |
| :--------------- | :------------ | :------------- |
| `task_id`        | `str`         | 任务的唯一标识符       |
| `description`    | `str`         | 当前状态描述         |
| `usage`          | `TaskUsage`   | 此任务迄今为止的令牌使用情况 |
| `uuid`           | `str`         | 唯一消息标识符        |
| `session_id`     | `str`         | 会话标识符          |
| `tool_use_id`    | `str \| None` | 关联的工具使用 ID     |
| `last_tool_name` | `str \| None` | 任务使用的最后一个工具的名称 |

<h3 id="tasknotificationmessage">
  `TaskNotificationMessage`
</h3>

当后台任务完成、失败或停止时发出。后台任务包括 `run_in_background` Bash 命令、Monitor 监视和后台子代理。

```python theme={null}
@dataclass
class TaskNotificationMessage(SystemMessage):
    task_id: str
    status: TaskNotificationStatus  # "completed" | "failed" | "stopped"
    output_file: str
    summary: str
    uuid: str
    session_id: str
    tool_use_id: str | None = None
    usage: TaskUsage | None = None
```

| 字段            | 类型                       | 描述                                        |
| :------------ | :----------------------- | :---------------------------------------- |
| `task_id`     | `str`                    | 任务的唯一标识符                                  |
| `status`      | `TaskNotificationStatus` | `"completed"`、`"failed"` 或 `"stopped"` 之一 |
| `output_file` | `str`                    | 任务输出文件的路径                                 |
| `summary`     | `str`                    | 任务结果的摘要                                   |
| `uuid`        | `str`                    | 唯一消息标识符                                   |
| `session_id`  | `str`                    | 会话标识符                                     |
| `tool_use_id` | `str \| None`            | 关联的工具使用 ID                                |
| `usage`       | `TaskUsage \| None`      | 任务的最终令牌使用情况                               |

<h2 id="content-block-types">
  内容块类型
</h2>

<h3 id="contentblock">
  `ContentBlock`
</h3>

所有内容块的联合类型。

```python theme={null}
ContentBlock = TextBlock | ThinkingBlock | ToolUseBlock | ToolResultBlock
```

<h3 id="textblock">
  `TextBlock`
</h3>

文本内容块。

```python theme={null}
@dataclass
class TextBlock:
    text: str
```

<h3 id="thinkingblock">
  `ThinkingBlock`
</h3>

思考内容块（用于具有思考能力的模型）。

```python theme={null}
@dataclass
class ThinkingBlock:
    thinking: str
    signature: str
```

<h3 id="tooluseblock">
  `ToolUseBlock`
</h3>

工具使用请求块。

```python theme={null}
@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
```

<h3 id="toolresultblock">
  `ToolResultBlock`
</h3>

工具执行结果块。

```python theme={null}
@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: str | list[dict[str, Any]] | None = None
    is_error: bool | None = None
```

<h2 id="error-types">
  错误类型
</h2>

<h3 id="claudesdkerror">
  `ClaudeSDKError`
</h3>

所有 SDK 错误的基础异常类。

```python theme={null}
class ClaudeSDKError(Exception):
    """Base error for Claude SDK."""
```

<h3 id="clinotfounderror">
  `CLINotFoundError`
</h3>

当 Claude Code CLI 未安装或找不到时引发。

```python theme={null}
class CLINotFoundError(CLIConnectionError):
    def __init__(
        self, message: str = "Claude Code not found", cli_path: str | None = None
    ):
        """
        Args:
            message: Error message (default: "Claude Code not found")
            cli_path: Optional path to the CLI that was not found
        """
```

<h3 id="cliconnectionerror">
  `CLIConnectionError`
</h3>

当连接到 Claude Code 失败时引发。

```python theme={null}
class CLIConnectionError(ClaudeSDKError):
    """Failed to connect to Claude Code."""
```

<h3 id="processerror">
  `ProcessError`
</h3>

当 Claude Code 进程失败时引发。

```python theme={null}
class ProcessError(ClaudeSDKError):
    def __init__(
        self, message: str, exit_code: int | None = None, stderr: str | None = None
    ):
        self.exit_code = exit_code
        self.stderr = stderr
```

<h3 id="clijsondecodeerror">
  `CLIJSONDecodeError`
</h3>

当 JSON 解析失败时引发。

```python theme={null}
class CLIJSONDecodeError(ClaudeSDKError):
    def __init__(self, line: str, original_error: Exception):
        """
        Args:
            line: The line that failed to parse
            original_error: The original JSON decode exception
        """
        self.line = line
        self.original_error = original_error
```

<h2 id="hook-types">
  Hook 类型
</h2>

有关使用 hooks 的综合指南，包括示例和常见模式，见 [Hooks 指南](/docs/zh-CN/agent-sdk/hooks)。

<h3 id="hookevent">
  `HookEvent`
</h3>

支持的 hook 事件类型。

```python theme={null}
HookEvent = Literal[
    "PreToolUse",  # Called before tool execution
    "PostToolUse",  # Called after tool execution
    "PostToolUseFailure",  # Called when a tool execution fails
    "UserPromptSubmit",  # Called when user submits a prompt
    "Stop",  # Called when stopping execution
    "SubagentStop",  # Called when a subagent stops
    "PreCompact",  # Called before message compaction
    "Notification",  # Called for notification events
    "SubagentStart",  # Called when a subagent starts
    "PermissionRequest",  # Called when a permission decision is needed
]
```

<Note>
  TypeScript SDK 支持 Python 中尚未提供的其他 hook 事件：`SessionStart`、`SessionEnd`、`Setup`、`TeammateIdle`、`TaskCompleted`、`ConfigChange`、`WorktreeCreate`、`WorktreeRemove`、`PostToolBatch` 和 `MessageDisplay`。
</Note>

<h3 id="hookcallback">
  `HookCallback`
</h3>

hook 回调函数的类型定义。

```python theme={null}
HookCallback = Callable[[HookInput, str | None, HookContext], Awaitable[HookJSONOutput]]
```

参数：

* `input`：强类型 hook 输入，具有基于 `hook_event_name` 的判别联合（见 [`HookInput`](#hookinput)）
* `tool_use_id`：可选工具使用标识符（用于工具相关的 hooks）
* `context`：带有附加信息的 hook 上下文

返回可能包含以下内容的 [`HookJSONOutput`](#hookjsonoutput)：

* `decision`：`"block"` 以阻止操作
* `systemMessage`：显示给用户的警告消息
* `hookSpecificOutput`：hook 特定的输出数据

<h3 id="hookcontext">
  `HookContext`
</h3>

传递给 hook 回调的上下文信息。

```python theme={null}
class HookContext(TypedDict):
    signal: Any | None  # Future: abort signal support
```

<h3 id="hookmatcher">
  `HookMatcher`
</h3>

用于将 hooks 匹配到特定事件或工具的配置。

```python theme={null}
@dataclass
class HookMatcher:
    matcher: str | None = (
        None  # Tool name or pattern to match (e.g., "Bash", "Write|Edit")
    )
    hooks: list[HookCallback] = field(
        default_factory=list
    )  # List of callbacks to execute
    timeout: float | None = (
        None  # Timeout in seconds for all hooks in this matcher (default: 60)
    )
```

<h3 id="hookinput">
  `HookInput`
</h3>

所有 hook 输入类型的联合类型。实际类型取决于 `hook_event_name` 字段。

```python theme={null}
HookInput = (
    PreToolUseHookInput
    | PostToolUseHookInput
    | PostToolUseFailureHookInput
    | UserPromptSubmitHookInput
    | StopHookInput
    | SubagentStopHookInput
    | PreCompactHookInput
    | NotificationHookInput
    | SubagentStartHookInput
    | PermissionRequestHookInput
)
```

<h3 id="basehookinput">
  `BaseHookInput`
</h3>

所有 hook 输入类型中存在的基础字段。

```python theme={null}
class BaseHookInput(TypedDict):
    session_id: str
    transcript_path: str
    cwd: str
    permission_mode: NotRequired[str]
```

| 字段                | 类型        | 描述        |
| :---------------- | :-------- | :-------- |
| `session_id`      | `str`     | 当前会话标识符   |
| `transcript_path` | `str`     | 会话记录文件的路径 |
| `cwd`             | `str`     | 当前工作目录    |
| `permission_mode` | `str`（可选） | 当前权限模式    |

<h3 id="pretoolusehookinput">
  `PreToolUseHookInput`
</h3>

`PreToolUse` hook 事件的输入数据。

```python theme={null}
class PreToolUseHookInput(BaseHookInput):
    hook_event_name: Literal["PreToolUse"]
    tool_name: str
    tool_input: dict[str, Any]
    tool_use_id: str
    agent_id: NotRequired[str]
    agent_type: NotRequired[str]
```

| 字段                | 类型                      | 描述                       |
| :---------------- | :---------------------- | :----------------------- |
| `hook_event_name` | `Literal["PreToolUse"]` | 始终为 "PreToolUse"         |
| `tool_name`       | `str`                   | 即将执行的工具的名称               |
| `tool_input`      | `dict[str, Any]`        | 工具的输入参数                  |
| `tool_use_id`     | `str`                   | 此工具使用的唯一标识符              |
| `agent_id`        | `str`（可选）               | 子代理标识符，当 hook 在子代理内触发时存在 |
| `agent_type`      | `str`（可选）               | 子代理类型，当 hook 在子代理内触发时存在  |

<h3 id="posttoolusehookinput">
  `PostToolUseHookInput`
</h3>

`PostToolUse` hook 事件的输入数据。

```python theme={null}
class PostToolUseHookInput(BaseHookInput):
    hook_event_name: Literal["PostToolUse"]
    tool_name: str
    tool_input: dict[str, Any]
    tool_response: Any
    tool_use_id: str
    agent_id: NotRequired[str]
    agent_type: NotRequired[str]
```

| 字段                | 类型                       | 描述                       |
| :---------------- | :----------------------- | :----------------------- |
| `hook_event_name` | `Literal["PostToolUse"]` | 始终为 "PostToolUse"        |
| `tool_name`       | `str`                    | 已执行的工具的名称                |
| `tool_input`      | `dict[str, Any]`         | 使用的输入参数                  |
| `tool_response`   | `Any`                    | 工具执行的响应                  |
| `tool_use_id`     | `str`                    | 此工具使用的唯一标识符              |
| `agent_id`        | `str`（可选）                | 子代理标识符，当 hook 在子代理内触发时存在 |
| `agent_type`      | `str`（可选）                | 子代理类型，当 hook 在子代理内触发时存在  |

<h3 id="posttoolusefailurehookinput">
  `PostToolUseFailureHookInput`
</h3>

`PostToolUseFailure` hook 事件的输入数据。当工具执行失败时调用。

```python theme={null}
class PostToolUseFailureHookInput(BaseHookInput):
    hook_event_name: Literal["PostToolUseFailure"]
    tool_name: str
    tool_input: dict[str, Any]
    tool_use_id: str
    error: str
    is_interrupt: NotRequired[bool]
    agent_id: NotRequired[str]
    agent_type: NotRequired[str]
```

| 字段                | 类型                              | 描述                       |
| :---------------- | :------------------------------ | :----------------------- |
| `hook_event_name` | `Literal["PostToolUseFailure"]` | 始终为 "PostToolUseFailure" |
| `tool_name`       | `str`                           | 失败的工具的名称                 |
| `tool_input`      | `dict[str, Any]`                | 使用的输入参数                  |
| `tool_use_id`     | `str`                           | 此工具使用的唯一标识符              |
| `error`           | `str`                           | 失败执行的错误消息                |
| `is_interrupt`    | `bool`（可选）                      | 失败是否由中断引起                |
| `agent_id`        | `str`（可选）                       | 子代理标识符，当 hook 在子代理内触发时存在 |
| `agent_type`      | `str`（可选）                       | 子代理类型，当 hook 在子代理内触发时存在  |

<h3 id="userpromptsubmithookinput">
  `UserPromptSubmitHookInput`
</h3>

`UserPromptSubmit` hook 事件的输入数据。

```python theme={null}
class UserPromptSubmitHookInput(BaseHookInput):
    hook_event_name: Literal["UserPromptSubmit"]
    prompt: str
```

| 字段                | 类型                            | 描述                     |
| :---------------- | :---------------------------- | :--------------------- |
| `hook_event_name` | `Literal["UserPromptSubmit"]` | 始终为 "UserPromptSubmit" |
| `prompt`          | `str`                         | 用户提交的提示                |

<h3 id="stophookinput">
  `StopHookInput`
</h3>

`Stop` hook 事件的输入数据。

```python theme={null}
class StopHookInput(BaseHookInput):
    hook_event_name: Literal["Stop"]
    stop_hook_active: bool
```

| 字段                 | 类型                | 描述             |
| :----------------- | :---------------- | :------------- |
| `hook_event_name`  | `Literal["Stop"]` | 始终为 "Stop"     |
| `stop_hook_active` | `bool`            | stop hook 是否活跃 |

<h3 id="subagentstophookinput">
  `SubagentStopHookInput`
</h3>

`SubagentStop` hook 事件的输入数据。

```python theme={null}
class SubagentStopHookInput(BaseHookInput):
    hook_event_name: Literal["SubagentStop"]
    stop_hook_active: bool
    agent_id: str
    agent_transcript_path: str
    agent_type: str
```

| 字段                      | 类型                        | 描述                 |
| :---------------------- | :------------------------ | :----------------- |
| `hook_event_name`       | `Literal["SubagentStop"]` | 始终为 "SubagentStop" |
| `stop_hook_active`      | `bool`                    | stop hook 是否活跃     |
| `agent_id`              | `str`                     | 子代理的唯一标识符          |
| `agent_transcript_path` | `str`                     | 子代理的记录文件路径         |
| `agent_type`            | `str`                     | 子代理的类型             |

<h3 id="precompacthookinput">
  `PreCompactHookInput`
</h3>

`PreCompact` hook 事件的输入数据。

```python theme={null}
class PreCompactHookInput(BaseHookInput):
    hook_event_name: Literal["PreCompact"]
    trigger: Literal["manual", "auto"]
    custom_instructions: str | None
```

| 字段                    | 类型                          | 描述               |
| :-------------------- | :-------------------------- | :--------------- |
| `hook_event_name`     | `Literal["PreCompact"]`     | 始终为 "PreCompact" |
| `trigger`             | `Literal["manual", "auto"]` | 什么触发了压缩          |
| `custom_instructions` | `str \| None`               | 压缩的自定义说明         |

<h3 id="notificationhookinput">
  `NotificationHookInput`
</h3>

`Notification` hook 事件的输入数据。

```python theme={null}
class NotificationHookInput(BaseHookInput):
    hook_event_name: Literal["Notification"]
    message: str
    title: NotRequired[str]
    notification_type: str
```

| 字段                  | 类型                        | 描述                 |
| :------------------ | :------------------------ | :----------------- |
| `hook_event_name`   | `Literal["Notification"]` | 始终为 "Notification" |
| `message`           | `str`                     | 通知消息内容             |
| `title`             | `str`（可选）                 | 通知标题               |
| `notification_type` | `str`                     | 通知类型               |

<h3 id="subagentstarthookinput">
  `SubagentStartHookInput`
</h3>

`SubagentStart` hook 事件的输入数据。

```python theme={null}
class SubagentStartHookInput(BaseHookInput):
    hook_event_name: Literal["SubagentStart"]
    agent_id: str
    agent_type: str
```

| 字段                | 类型                         | 描述                  |
| :---------------- | :------------------------- | :------------------ |
| `hook_event_name` | `Literal["SubagentStart"]` | 始终为 "SubagentStart" |
| `agent_id`        | `str`                      | 子代理的唯一标识符           |
| `agent_type`      | `str`                      | 子代理的类型              |

<h3 id="permissionrequesthookinput">
  `PermissionRequestHookInput`
</h3>

`PermissionRequest` hook 事件的输入数据。允许 hooks 以编程方式处理权限决策。

```python theme={null}
class PermissionRequestHookInput(BaseHookInput):
    hook_event_name: Literal["PermissionRequest"]
    tool_name: str
    tool_input: dict[str, Any]
    permission_suggestions: NotRequired[list[Any]]
    agent_id: NotRequired[str]
    agent_type: NotRequired[str]
```

| 字段                       | 类型                             | 描述                       |
| :----------------------- | :----------------------------- | :----------------------- |
| `hook_event_name`        | `Literal["PermissionRequest"]` | 始终为 "PermissionRequest"  |
| `tool_name`              | `str`                          | 请求权限的工具的名称               |
| `tool_input`             | `dict[str, Any]`               | 工具的输入参数                  |
| `permission_suggestions` | `list[Any]`（可选）                | 来自 CLI 的建议权限更新           |
| `agent_id`               | `str`（可选）                      | 子代理标识符，当 hook 在子代理内触发时存在 |
| `agent_type`             | `str`（可选）                      | 子代理类型，当 hook 在子代理内触发时存在  |

<h3 id="hookjsonoutput">
  `HookJSONOutput`
</h3>

hook 回调返回值的联合类型。

```python theme={null}
HookJSONOutput = AsyncHookJSONOutput | SyncHookJSONOutput
```

<h4 id="synchookjsonoutput">
  `SyncHookJSONOutput`
</h4>

具有控制和决策字段的同步 hook 输出。

```python theme={null}
class SyncHookJSONOutput(TypedDict):
    # Control fields
    continue_: NotRequired[bool]  # Whether to proceed (default: True)
    suppressOutput: NotRequired[bool]  # Hide stdout from transcript
    stopReason: NotRequired[str]  # Message when continue is False

    # Decision fields
    decision: NotRequired[Literal["block"]]
    systemMessage: NotRequired[str]  # Warning message for user
    reason: NotRequired[str]  # Feedback for Claude

    # Hook-specific output
    hookSpecificOutput: NotRequired[HookSpecificOutput]
```

<Note>
  在 Python 代码中使用 `continue_`（带下划线）。发送到 CLI 时会自动转换为 `continue`。
</Note>

<h4 id="hookspecificoutput">
  `HookSpecificOutput`
</h4>

包含 hook 事件名称和事件特定字段的 `TypedDict`。形状取决于 `hookEventName` 值。有关每个 hook 事件的可用字段的完整详情，见 [使用 hooks 控制执行](/docs/zh-CN/agent-sdk/hooks#outputs)。

事件特定输出类型的判别联合。`hookEventName` 字段确定哪些字段有效。

```python theme={null}
class PreToolUseHookSpecificOutput(TypedDict):
    hookEventName: Literal["PreToolUse"]
    permissionDecision: NotRequired[Literal["allow", "deny", "ask", "defer"]]
    permissionDecisionReason: NotRequired[str]
    updatedInput: NotRequired[dict[str, Any]]
    additionalContext: NotRequired[str]


class PostToolUseHookSpecificOutput(TypedDict):
    hookEventName: Literal["PostToolUse"]
    additionalContext: NotRequired[str]
    updatedToolOutput: NotRequired[Any]
    updatedMCPToolOutput: NotRequired[Any]  # Deprecated: use updatedToolOutput, which works for all tools


class PostToolUseFailureHookSpecificOutput(TypedDict):
    hookEventName: Literal["PostToolUseFailure"]
    additionalContext: NotRequired[str]


class UserPromptSubmitHookSpecificOutput(TypedDict):
    hookEventName: Literal["UserPromptSubmit"]
    additionalContext: NotRequired[str]


class NotificationHookSpecificOutput(TypedDict):
    hookEventName: Literal["Notification"]
    additionalContext: NotRequired[str]


class SubagentStartHookSpecificOutput(TypedDict):
    hookEventName: Literal["SubagentStart"]
    additionalContext: NotRequired[str]


class PermissionRequestHookSpecificOutput(TypedDict):
    hookEventName: Literal["PermissionRequest"]
    decision: dict[str, Any]


HookSpecificOutput = (
    PreToolUseHookSpecificOutput
    | PostToolUseHookSpecificOutput
    | PostToolUseFailureHookSpecificOutput
    | UserPromptSubmitHookSpecificOutput
    | NotificationHookSpecificOutput
    | SubagentStartHookSpecificOutput
    | PermissionRequestHookSpecificOutput
)
```

<h4 id="asynchookjsonoutput">
  `AsyncHookJSONOutput`
</h4>

延迟 hook 执行的异步 hook 输出。

```python theme={null}
class AsyncHookJSONOutput(TypedDict):
    async_: Literal[True]  # Set to True to defer execution
    asyncTimeout: NotRequired[int]  # Timeout in milliseconds
```

<Note>
  在 Python 代码中使用 `async_`（带下划线）。发送到 CLI 时会自动转换为 `async`。
</Note>

<h3 id="hook-usage-example">
  Hook 使用示例
</h3>

此示例注册两个 hooks：一个阻止危险的 bash 命令（如 `rm -rf /`），另一个记录所有工具使用以进行审计。安全 hook 仅在 Bash 命令上运行（通过 `matcher`），而日志 hook 在所有工具上运行。

```python theme={null}
from claude_agent_sdk import query, ClaudeAgentOptions, HookMatcher, HookContext
from typing import Any


async def validate_bash_command(
    input_data: dict[str, Any], tool_use_id: str | None, context: HookContext
) -> dict[str, Any]:
    """Validate and potentially block dangerous bash commands."""
    if input_data["tool_name"] == "Bash":
        command = input_data["tool_input"].get("command", "")
        if "rm -rf /" in command:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "Dangerous command blocked",
                }
            }
    return {}


async def log_tool_use(
    input_data: dict[str, Any], tool_use_id: str | None, context: HookContext
) -> dict[str, Any]:
    """Log all tool usage for auditing."""
    print(f"Tool used: {input_data.get('tool_name')}")
    return {}


options = ClaudeAgentOptions(
    hooks={
        "PreToolUse": [
            HookMatcher(
                matcher="Bash", hooks=[validate_bash_command], timeout=120
            ),  # 2 min for validation
            HookMatcher(
                hooks=[log_tool_use]
            ),  # Applies to all tools (default 60s timeout)
        ],
        "PostToolUse": [HookMatcher(hooks=[log_tool_use])],
    }
)

async for message in query(prompt="Analyze this codebase", options=options):
    print(message)
```

<h2 id="tool-input/output-types">
  工具输入/输出类型
</h2>

所有内置 Claude Code 工具的输入/输出模式文档。虽然 Python SDK 不将这些导出为类型，但它们代表消息中工具输入和输出的结构。

<h3 id="agent">
  Agent
</h3>

**工具名称：** `Agent`（之前为 `Task`，仍然接受作为别名）

**输入：**

```python theme={null}
{
    "description": str,  # 任务的简短描述（3-5 个单词）
    "prompt": str,  # 代理要执行的任务
    "subagent_type": str,  # 要使用的专门代理的类型
}
```

**输出：**

```python theme={null}
{
    "result": str,  # 来自子代理的最终结果
    "usage": dict | None,  # 令牌使用统计
    "total_cost_usd": float | None,  # 以美元计的估计总成本
    "duration_ms": int | None,  # 执行持续时间（毫秒）
}
```

<h3 id="askuserquestion">
  AskUserQuestion
</h3>

**工具名称：** `AskUserQuestion`

在执行期间向用户提出澄清问题。见 [处理批准和用户输入](/docs/zh-CN/agent-sdk/user-input#handle-clarifying-questions) 了解使用详情。

**输入：**

```python theme={null}
{
    "questions": [  # 要向用户提出的问题（1-4 个问题）
        {
            "question": str,  # 要向用户提出的完整问题
            "header": str,  # 显示为芯片/标签的非常简短的标签（最多 12 个字符）
            "options": [  # 可用的选择（2-4 个选项）
                {
                    "label": str,  # 此选项的显示文本（1-5 个单词）
                    "description": str,  # 此选项含义的说明
                }
            ],
            "multiSelect": bool,  # 设置为 true 以允许多个选择
        }
    ],
    "answers": dict[str, str | list[str]] | None,
    # 由权限系统填充的用户答案。多选
    # 答案可能是标签列表或逗号连接的字符串
}
```

**输出：**

```python theme={null}
{
    "questions": [  # 被提出的问题
        {
            "question": str,
            "header": str,
            "options": [{"label": str, "description": str}],
            "multiSelect": bool,
        }
    ],
    "answers": dict[str, str],  # 将问题文本映射到答案字符串
    # 多选答案以逗号分隔
}
```

<h3 id="bash">
  Bash
</h3>

**工具名称：** `Bash`

**输入：**

```python theme={null}
{
    "command": str,  # 要执行的命令
    "timeout": int | None,  # 可选的超时时间（毫秒）（最大 600000；更高的值被限制为最大值）
    "description": str | None,  # 清晰、简洁的描述（5-10 个单词）
    "run_in_background": bool | None,  # 设置为 true 以在后台运行
}
```

**输出：**

```python theme={null}
{
    "output": str,  # 合并的 stdout 和 stderr 输出
    "exitCode": int,  # 命令的退出代码
    "killed": bool | None,  # 命令是否因超时而被杀死
    "shellId": str | None,  # 后台进程的 Shell ID
}
```

<h3 id="monitor">
  Monitor
</h3>

**工具名称：** `Monitor`

运行后台源并将每个事件传递给 Claude，以便它可以做出反应而无需轮询：`command` 运行脚本并每个 stdout 行发出一个事件，`ws` 打开 WebSocket 并每个文本帧发出一个事件。恰好提供 `command` 或 `ws` 中的一个。

当 Monitor 运行命令时，它遵循与 Bash 相同的权限规则；WebSocket 监视会单独提示批准。`ws` 源需要 Claude Code v2.1.195 或更高版本。见 [Monitor 工具参考](/docs/zh-CN/tools-reference#monitor-tool) 了解行为和提供商可用性。

**输入：**

```python theme={null}
{
    "command": str | None,  # Shell 脚本；每个 stdout 行是一个事件，退出结束监视
    "ws": dict | None,  # WebSocket 源：{"url": str, "protocols": list[str] | None}；每个文本帧是一个事件
    "description": str,  # 在通知中显示的简短描述
    "timeout_ms": int | None,  # 在此截止时间后杀死（默认 300000，最大 3600000）
    "persistent": bool | None,  # 在会话的生命周期内运行；使用 TaskStop 停止
}
```

**输出：**

```python theme={null}
{
    "taskId": str,  # 后台监视任务的 ID
    "timeoutMs": int,  # 超时截止时间（毫秒）（持久时为 0）
    "persistent": bool | None,  # 当运行到 TaskStop 或会话结束时为 True
}
```

<h3 id="edit">
  Edit
</h3>

**工具名称：** `Edit`

**输入：**

```python theme={null}
{
    "file_path": str,  # 要修改的文件的绝对路径
    "old_string": str,  # 要替换的文本
    "new_string": str,  # 替换为的文本
    "replace_all": bool | None,  # 替换所有出现（默认 False）
}
```

**输出：**

```python theme={null}
{
    "message": str,  # 确认消息
    "replacements": int,  # 进行的替换次数
    "file_path": str,  # 被编辑的文件路径
}
```

<h3 id="read">
  Read
</h3>

**工具名称：** `Read`

**输入：**

```python theme={null}
{
    "file_path": str,  # 要读取的文件的绝对路径
    "offset": int | None,  # 开始读取的行号
    "limit": int | None,  # 要读取的行数
}
```

**输出（文本文件）：**

```python theme={null}
{
    "content": str,  # 带行号的文件内容
    "total_lines": int,  # 文件中的总行数
    "lines_returned": int,  # 实际返回的行数
}
```

**输出（图像）：**

```python theme={null}
{
    "image": str,  # Base64 编码的图像数据
    "mime_type": str,  # 图像 MIME 类型
    "file_size": int,  # 文件大小（字节）
}
```

<h3 id="write">
  Write
</h3>

**工具名称：** `Write`

**输入：**

```python theme={null}
{
    "file_path": str,  # 要写入的文件的绝对路径
    "content": str,  # 要写入文件的内容
}
```

**输出：**

```python theme={null}
{
    "message": str,  # 成功消息
    "bytes_written": int,  # 写入的字节数
    "file_path": str,  # 被写入的文件路径
}
```

<h3 id="glob">
  Glob
</h3>

**工具名称：** `Glob`

**输入：**

```python theme={null}
{
    "pattern": str,  # 用于匹配文件的 glob 模式
    "path": str | None,  # 要搜索的目录（默认为 cwd）
}
```

**输出：**

```python theme={null}
{
    "matches": list[str],  # 匹配的文件路径数组
    "count": int,  # 找到的匹配数
    "search_path": str,  # 使用的搜索目录
}
```

<h3 id="grep">
  Grep
</h3>

**工具名称：** `Grep`

**输入：**

```python theme={null}
{
    "pattern": str,  # 正则表达式模式
    "path": str | None,  # 要搜索的文件或目录
    "glob": str | None,  # 用于过滤文件的 glob 模式
    "type": str | None,  # 要搜索的文件类型
    "output_mode": str | None,  # "content"、"files_with_matches" 或 "count"
    "-i": bool | None,  # 不区分大小写的搜索
    "-n": bool | None,  # 显示行号
    "-B": int | None,  # 每个匹配前显示的行数
    "-A": int | None,  # 每个匹配后显示的行数
    "-C": int | None,  # 每个匹配前后显示的行数
    "head_limit": int | None,  # 将输出限制为前 N 行/条目
    "multiline": bool | None,  # 启用多行模式
}
```

**输出（content 模式）：**

```python theme={null}
{
    "matches": [
        {
            "file": str,
            "line_number": int | None,
            "line": str,
            "before_context": list[str] | None,
            "after_context": list[str] | None,
        }
    ],
    "total_matches": int,
}
```

**输出（files\_with\_matches 模式）：**

```python theme={null}
{
    "files": list[str],  # 包含匹配的文件
    "count": int,  # 包含匹配的文件数
}
```

<h3 id="notebookedit">
  NotebookEdit
</h3>

**工具名称：** `NotebookEdit`

**输入：**

```python theme={null}
{
    "notebook_path": str,  # Jupyter 笔记本的绝对路径
    "cell_id": str | None,  # 要编辑的单元格的 ID
    "new_source": str,  # 单元格的新源代码
    "cell_type": "code" | "markdown" | None,  # 单元格的类型
    "edit_mode": "replace" | "insert" | "delete" | None,  # 编辑操作类型
}
```

**输出：**

```python theme={null}
{
    "message": str,  # 成功消息
    "edit_type": "replaced" | "inserted" | "deleted",  # 执行的编辑类型
    "cell_id": str | None,  # 受影响的单元格 ID
    "total_cells": int,  # 编辑后笔记本中的总单元格数
}
```

<h3 id="webfetch">
  WebFetch
</h3>

**工具名称：** `WebFetch`

**输入：**

```python theme={null}
{
    "url": str,  # 要从中获取内容的 URL
    "prompt": str,  # 在获取的内容上运行的提示
}
```

**输出：**

```python theme={null}
{
    "bytes": int,  # 获取的内容大小（字节）
    "code": int,  # HTTP 响应代码
    "codeText": str,  # HTTP 响应代码文本
    "result": str,  # 通过将提示应用于内容得到的处理结果
    "durationMs": int,  # 获取和处理内容的时间（毫秒）
    "url": str,  # 被获取的 URL
}
```

<h3 id="websearch">
  WebSearch
</h3>

**工具名称：** `WebSearch`

**输入：**

```python theme={null}
{
    "query": str,  # 要使用的搜索查询
    "allowed_domains": list[str] | None,  # 仅包含来自这些域的结果
    "blocked_domains": list[str] | None,  # 永远不包含来自这些域的结果
}
```

**输出：**

```python theme={null}
{
    "query": str,  # 搜索查询
    "results": list[str | {"tool_use_id": str, "content": list[{"title": str, "url": str}]}],
    "durationSeconds": float,  # 搜索持续时间（秒）
}
```

<h3 id="todowrite">
  TodoWrite
</h3>

**工具名称：** `TodoWrite`

<Note>
  自 Claude Code v2.1.142 起，`TodoWrite` 默认被禁用。改用 `TaskCreate`、`TaskGet`、`TaskUpdate` 和 `TaskList`。见 [迁移到 Task 工具](/docs/zh-CN/agent-sdk/todo-tracking#migrate-to-task-tools) 更新您的监视代码，或设置 `CLAUDE_CODE_ENABLE_TASKS=0` 以恢复到 `TodoWrite`。
</Note>

**输入：**

```python theme={null}
{
    "todos": [
        {
            "content": str,  # 任务描述
            "status": "pending" | "in_progress" | "completed",  # 任务状态
            "activeForm": str,  # 描述的活跃形式
        }
    ]
}
```

**输出：**

```python theme={null}
{
    "message": str,  # 成功消息
    "stats": {"total": int, "pending": int, "in_progress": int, "completed": int},
}
```

<h3 id="taskcreate">
  TaskCreate
</h3>

**工具名称：** `TaskCreate`

**输入：**

```python theme={null}
{
    "subject": str,  # 简短的任务标题
    "description": str,  # 详细的任务正文
    "activeForm": str | None,  # 进行中时显示的现在时标签
    "metadata": dict | None,  # 任意调用者元数据
}
```

**输出：**

```python theme={null}
{
    "task": {"id": str, "subject": str},  # 创建的任务及其分配的 ID
}
```

<h3 id="taskupdate">
  TaskUpdate
</h3>

**工具名称：** `TaskUpdate`

**输入：**

```python theme={null}
{
    "taskId": str,  # 要修补的任务的 ID
    "status": Literal["pending", "in_progress", "completed", "deleted"] | None,
    "subject": str | None,
    "description": str | None,
    "activeForm": str | None,
    "addBlocks": list[str] | None,  # 此任务现在阻止的任务 ID
    "addBlockedBy": list[str] | None,  # 现在阻止此任务的任务 ID
    "owner": str | None,
    "metadata": dict | None,
}
```

**输出：**

```python theme={null}
{
    "success": bool,
    "taskId": str,
    "updatedFields": list[str],  # 更改的字段名称
    "error": str | None,
    "statusChange": {"from": str, "to": str} | None,
}
```

<h3 id="taskget">
  TaskGet
</h3>

**工具名称：** `TaskGet`

**输入：**

```python theme={null}
{
    "taskId": str,  # 要读取的任务的 ID
}
```

**输出：**

```python theme={null}
{
    "task": {
        "id": str,
        "subject": str,
        "description": str,
        "status": Literal["pending", "in_progress", "completed"],
        "blocks": list[str],
        "blockedBy": list[str],
    } | None,  # 当 ID 未找到时为 None
}
```

<h3 id="tasklist">
  TaskList
</h3>

**工具名称：** `TaskList`

**输入：**

```python theme={null}
{}
```

**输出：**

```python theme={null}
{
    "tasks": [
        {
            "id": str,
            "subject": str,
            "status": Literal["pending", "in_progress", "completed"],
            "owner": str | None,
            "blockedBy": list[str],
        }
    ],
}
```

<h3 id="bashoutput">
  BashOutput
</h3>

**工具名称：** `BashOutput`

**输入：**

```python theme={null}
{
    "bash_id": str,  # 后台 shell 的 ID
    "filter": str | None,  # 用于过滤输出行的可选正则表达式
}
```

**输出：**

```python theme={null}
{
    "output": str,  # 自上次检查以来的新输出
    "status": "running" | "completed" | "failed",  # 当前 shell 状态
    "exitCode": int | None,  # 完成时的退出代码
}
```

<h3 id="killbash">
  KillBash
</h3>

**工具名称：** `KillBash`

**输入：**

```python theme={null}
{
    "shell_id": str  # 要杀死的后台 shell 的 ID
}
```

**输出：**

```python theme={null}
{
    "message": str,  # 成功消息
    "shell_id": str,  # 被杀死的 shell 的 ID
}
```

<h3 id="exitplanmode">
  ExitPlanMode
</h3>

**工具名称：** `ExitPlanMode`

**输入：**

```python theme={null}
{
    "plan": str  # 用户要运行以获得批准的计划
}
```

**输出：**

```python theme={null}
{
    "message": str,  # 确认消息
    "approved": bool | None,  # 用户是否批准了计划
}
```

<h3 id="listmcpresources">
  ListMcpResources
</h3>

**工具名称：** `ListMcpResourcesTool`

**输入：**

```python theme={null}
{
    "server": str | None  # 可选的服务器名称以按其过滤资源
}
```

**输出：**

```python theme={null}
{
    "resources": [
        {
            "uri": str,
            "name": str,
            "description": str | None,
            "mimeType": str | None,
            "server": str,
        }
    ],
    "total": int,
}
```

<h3 id="readmcpresource">
  ReadMcpResource
</h3>

**工具名称：** `ReadMcpResourceTool`

**输入：**

```python theme={null}
{
    "server": str,  # MCP 服务器名称
    "uri": str,  # 要读取的资源 URI
}
```

**输出：**

```python theme={null}
{
    "contents": [
        {"uri": str, "mimeType": str | None, "text": str | None, "blob": str | None}
    ],
    "server": str,
}
```

<h2 id="advanced-features-with-claudesdkclient">
  ClaudeSDKClient 的高级功能
</h2>

<h3 id="building-a-continuous-conversation-interface">
  构建持续对话界面
</h3>

```python theme={null}
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
)
import asyncio


class ConversationSession:
    """Maintains a single conversation session with Claude."""

    def __init__(self, options: ClaudeAgentOptions | None = None):
        self.client = ClaudeSDKClient(options)
        self.turn_count = 0

    async def start(self):
        await self.client.connect()
        print("Starting conversation session. Claude will remember context.")
        print(
            "Commands: 'exit' to quit, 'interrupt' to stop current task, 'new' for new session"
        )

        while True:
            user_input = input(f"\n[Turn {self.turn_count + 1}] You: ")

            if user_input.lower() == "exit":
                break
            elif user_input.lower() == "interrupt":
                await self.client.interrupt()
                print("Task interrupted!")
                continue
            elif user_input.lower() == "new":
                # Disconnect and reconnect for a fresh session
                await self.client.disconnect()
                await self.client.connect()
                self.turn_count = 0
                print("Started new conversation session (previous context cleared)")
                continue

            # Send message - the session retains all previous messages
            await self.client.query(user_input)
            self.turn_count += 1

            # Process response
            print(f"[Turn {self.turn_count}] Claude: ", end="")
            async for message in self.client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(block.text, end="")
            print()  # New line after response

        await self.client.disconnect()
        print(f"Conversation ended after {self.turn_count} turns.")


async def main():
    options = ClaudeAgentOptions(
        allowed_tools=["Read", "Write", "Bash"], permission_mode="acceptEdits"
    )
    session = ConversationSession(options)
    await session.start()


# Example conversation:
# Turn 1 - You: "Create a file called hello.py"
# Turn 1 - Claude: "I'll create a hello.py file for you..."
# Turn 2 - You: "What's in that file?"
# Turn 2 - Claude: "The hello.py file I just created contains..." (remembers!)
# Turn 3 - You: "Add a main function to it"
# Turn 3 - Claude: "I'll add a main function to hello.py..." (knows which file!)

asyncio.run(main())
```

<h3 id="using-hooks-for-behavior-modification">
  使用 Hooks 进行行为修改
</h3>

```python theme={null}
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    HookMatcher,
    HookContext,
)
import asyncio
from typing import Any


async def pre_tool_logger(
    input_data: dict[str, Any], tool_use_id: str | None, context: HookContext
) -> dict[str, Any]:
    """Log all tool usage before execution."""
    tool_name = input_data.get("tool_name", "unknown")
    print(f"[PRE-TOOL] About to use: {tool_name}")

    # You can modify or block the tool execution here
    if tool_name == "Bash" and "rm -rf" in str(input_data.get("tool_input", {})):
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "Dangerous command blocked",
            }
        }
    return {}


async def post_tool_logger(
    input_data: dict[str, Any], tool_use_id: str | None, context: HookContext
) -> dict[str, Any]:
    """Log results after tool execution."""
    tool_name = input_data.get("tool_name", "unknown")
    print(f"[POST-TOOL] Completed: {tool_name}")
    return {}


async def user_prompt_modifier(
    input_data: dict[str, Any], tool_use_id: str | None, context: HookContext
) -> dict[str, Any]:
    """Add context to user prompts."""
    original_prompt = input_data.get("prompt", "")

    # Add a timestamp as additional context for Claude to see
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": f"[Submitted at {timestamp}] Original prompt: {original_prompt}",
        }
    }


async def main():
    options = ClaudeAgentOptions(
        hooks={
            "PreToolUse": [
                HookMatcher(hooks=[pre_tool_logger]),
                HookMatcher(matcher="Bash", hooks=[pre_tool_logger]),
            ],
            "PostToolUse": [HookMatcher(hooks=[post_tool_logger])],
            "UserPromptSubmit": [HookMatcher(hooks=[user_prompt_modifier])],
        },
        allowed_tools=["Read", "Write", "Bash"],
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query("List files in current directory")

        async for message in client.receive_response():
            # Hooks will automatically log tool usage
            pass


asyncio.run(main())
```

<h3 id="real-time-progress-monitoring">
  实时进度监控
</h3>

```python theme={null}
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ToolUseBlock,
    ToolResultBlock,
    TextBlock,
)
import asyncio


async def monitor_progress():
    options = ClaudeAgentOptions(
        allowed_tools=["Write", "Bash"], permission_mode="acceptEdits"
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query("Create 5 Python files with different sorting algorithms")

        # Monitor progress in real-time
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        if block.name == "Write":
                            file_path = block.input.get("file_path", "")
                            print(f"Creating: {file_path}")
                    elif isinstance(block, ToolResultBlock):
                        print("Completed tool execution")
                    elif isinstance(block, TextBlock):
                        print(f"Claude says: {block.text[:100]}...")

        print("Task completed!")


asyncio.run(monitor_progress())
```

<h2 id="example-usage">
  示例用法
</h2>

<h3 id="basic-file-operations-using-query">
  基本文件操作（使用 query）
</h3>

```python theme={null}
from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, ToolUseBlock
import asyncio


async def create_project():
    options = ClaudeAgentOptions(
        allowed_tools=["Read", "Write", "Bash"],
        permission_mode="acceptEdits",
        cwd="/home/user/project",
    )

    async for message in query(
        prompt="Create a Python project structure with setup.py", options=options
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    print(f"Using tool: {block.name}")


asyncio.run(create_project())
```

<h3 id="error-handling">
  错误处理
</h3>

```python theme={null}
from claude_agent_sdk import query, CLINotFoundError, ProcessError, CLIJSONDecodeError

try:
    async for message in query(prompt="Hello"):
        print(message)
except CLINotFoundError:
    print(
        "Claude Code CLI not found. Try reinstalling: pip install --force-reinstall claude-agent-sdk"
    )
except ProcessError as e:
    print(f"Process failed with exit code: {e.exit_code}")
except CLIJSONDecodeError as e:
    print(f"Failed to parse response: {e}")
```

<h3 id="streaming-mode-with-client">
  使用客户端的流式模式
</h3>

```python theme={null}
from claude_agent_sdk import ClaudeSDKClient
import asyncio


async def interactive_session():
    async with ClaudeSDKClient() as client:
        # Send initial message
        await client.query("What's the weather like?")

        # Process responses
        async for msg in client.receive_response():
            print(msg)

        # Send follow-up
        await client.query("Tell me more about that")

        # Process follow-up response
        async for msg in client.receive_response():
            print(msg)


asyncio.run(interactive_session())
```

<h3 id="using-custom-tools-with-claudesdkclient">
  使用 ClaudeSDKClient 的自定义工具
</h3>

```python theme={null}
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    tool,
    create_sdk_mcp_server,
    AssistantMessage,
    TextBlock,
)
import asyncio
from typing import Any


# Define custom tools with @tool decorator
@tool("calculate", "Perform mathematical calculations", {"expression": str})
async def calculate(args: dict[str, Any]) -> dict[str, Any]:
    try:
        result = eval(args["expression"], {"__builtins__": {}})
        return {"content": [{"type": "text", "text": f"Result: {result}"}]}
    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "is_error": True,
        }


@tool("get_time", "Get current time", {})
async def get_time(args: dict[str, Any]) -> dict[str, Any]:
    from datetime import datetime

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {"content": [{"type": "text", "text": f"Current time: {current_time}"}]}


async def main():
    # Create SDK MCP server with custom tools
    my_server = create_sdk_mcp_server(
        name="utilities", version="1.0.0", tools=[calculate, get_time]
    )

    # Configure options with the server
    options = ClaudeAgentOptions(
        mcp_servers={"utils": my_server},
        allowed_tools=["mcp__utils__calculate", "mcp__utils__get_time"],
    )

    # Use ClaudeSDKClient for interactive tool usage
    async with ClaudeSDKClient(options=options) as client:
        await client.query("What's 123 * 456?")

        # Process calculation response
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"Calculation: {block.text}")

        # Follow up with time query
        await client.query("What time is it now?")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"Time: {block.text}")


asyncio.run(main())
```

<h2 id="sandbox-configuration">
  沙箱配置
</h2>

<h3 id="sandboxsettings">
  `SandboxSettings`
</h3>

沙箱行为的配置。使用此来启用命令沙箱和以编程方式配置网络限制。

```python theme={null}
class SandboxSettings(TypedDict, total=False):
    enabled: bool
    autoAllowBashIfSandboxed: bool
    excludedCommands: list[str]
    allowUnsandboxedCommands: bool
    network: SandboxNetworkConfig
    ignoreViolations: SandboxIgnoreViolations
    enableWeakerNestedSandbox: bool
```

| 属性                          | 类型                                                    | 默认值     | 描述                                                                                                                               |
| :-------------------------- | :---------------------------------------------------- | :------ | :------------------------------------------------------------------------------------------------------------------------------- |
| `enabled`                   | `bool`                                                | `False` | 为命令执行启用沙箱模式                                                                                                                      |
| `autoAllowBashIfSandboxed`  | `bool`                                                | `True`  | 启用沙箱时自动批准 bash 命令                                                                                                                |
| `excludedCommands`          | `list[str]`                                           | `[]`    | 始终绕过沙箱限制的命令（例如 `["docker"]`）。这些自动运行沙箱外，无需模型参与                                                                                    |
| `allowUnsandboxedCommands`  | `bool`                                                | `True`  | 允许模型请求在沙箱外运行命令。当为 `True` 时，模型可以在工具输入中设置 `dangerouslyDisableSandbox`，这会回退到 [权限系统](#permissions-fallback-for-unsandboxed-commands) |
| `network`                   | [`SandboxNetworkConfig`](#sandboxnetworkconfig)       | `None`  | 网络特定的沙箱配置                                                                                                                        |
| `ignoreViolations`          | [`SandboxIgnoreViolations`](#sandboxignoreviolations) | `None`  | 配置要忽略的沙箱违规                                                                                                                       |
| `enableWeakerNestedSandbox` | `bool`                                                | `False` | 启用较弱的嵌套沙箱以实现兼容性                                                                                                                  |

<Note>
  沙箱取决于平台支持，在 Linux 上，需要 `bubblewrap` 和 `socat` 等工具。默认情况下，当 `enabled` 为 `True` 但沙箱无法启动时，命令在沙箱外运行，并在 stderr 上显示警告。此默认值与 TypeScript SDK 不同，后者中 `failIfUnavailable` 默认为 `true`。

  在沙箱设置中设置 `"failIfUnavailable": True` 以改为停止。该键尚未在 `SandboxSettings` 上声明，但 SDK 会将其转发给 Claude Code，后者会遵守它。然后 `query()` 报告一个 `ResultMessage`，其 `subtype="error_during_execution"` 和 `errors` 中的原因。监视该子类型，而不是期望 `query()` 在生成消息之前引发。
</Note>

<h4 id="example-usage-2">
  示例用法
</h4>

```python theme={null}
from claude_agent_sdk import query, ClaudeAgentOptions, SandboxSettings

sandbox_settings: SandboxSettings = {
    "enabled": True,
    "autoAllowBashIfSandboxed": True,
    "network": {"allowLocalBinding": True},
}

async for message in query(
    prompt="Build and test my project",
    options=ClaudeAgentOptions(sandbox=sandbox_settings),
):
    print(message)
```

<Warning>
  **Unix socket 安全性**：`allowUnixSockets` 选项可以授予对强大系统服务的访问权限。例如，允许 `/var/run/docker.sock` 实际上通过 Docker API 授予完整的主机系统访问权限，绕过沙箱隔离。仅允许严格必要的 Unix sockets，并理解每个的安全含义。
</Warning>

<h3 id="sandboxnetworkconfig">
  `SandboxNetworkConfig`
</h3>

沙箱模式的网络特定配置。这些设置适用于当父 [`SandboxSettings`](#sandboxsettings) 中的 `enabled` 为 `True` 时的沙箱化 Bash 命令。它们不限制 WebFetch 工具，该工具改用 [权限规则](/docs/zh-CN/permissions#webfetch)。

```python theme={null}
class SandboxNetworkConfig(TypedDict, total=False):
    allowedDomains: list[str]
    deniedDomains: list[str]
    allowManagedDomainsOnly: bool
    allowUnixSockets: list[str]
    allowAllUnixSockets: bool
    allowLocalBinding: bool
    allowMachLookup: list[str]
    httpProxyPort: int
    socksProxyPort: int
```

| 属性                        | 类型          | 默认值     | 描述                                                           |
| :------------------------ | :---------- | :------ | :----------------------------------------------------------- |
| `allowedDomains`          | `list[str]` | `[]`    | 沙箱化进程可以访问的域名                                                 |
| `deniedDomains`           | `list[str]` | `[]`    | 沙箱化进程无法访问的域名。优先于 `allowedDomains`                            |
| `allowManagedDomainsOnly` | `bool`      | `False` | 仅限托管设置：在托管设置中设置时，忽略来自非托管设置源的 `allowedDomains`。通过 SDK 选项设置时无效 |
| `allowUnixSockets`        | `list[str]` | `[]`    | 进程可以访问的 Unix socket 路径（例如 Docker socket）                     |
| `allowAllUnixSockets`     | `bool`      | `False` | 允许访问所有 Unix sockets                                          |
| `allowLocalBinding`       | `bool`      | `False` | 允许进程绑定到本地端口（例如开发服务器）                                         |
| `allowMachLookup`         | `list[str]` | `[]`    | 仅限 macOS：允许的 XPC/Mach 服务名称。支持尾部通配符                           |
| `httpProxyPort`           | `int`       | `None`  | 网络请求的 HTTP 代理端口                                              |
| `socksProxyPort`          | `int`       | `None`  | 网络请求的 SOCKS 代理端口                                             |

<Note>
  内置沙箱代理基于请求的主机名强制执行网络允许列表，不会终止或检查 TLS 流量，因此 [域名前置](https://en.wikipedia.org/wiki/Domain_fronting) 等技术可能会绕过它。有关详细信息，请参阅 [沙箱安全限制](/docs/zh-CN/sandboxing#security-limitations)，以及 [安全部署](/docs/zh-CN/agent-sdk/secure-deployment#traffic-forwarding) 以配置 TLS 终止代理。
</Note>

<h3 id="sandboxignoreviolations">
  `SandboxIgnoreViolations`
</h3>

用于忽略特定沙箱违规的配置。

```python theme={null}
class SandboxIgnoreViolations(TypedDict, total=False):
    file: list[str]
    network: list[str]
```

| 属性        | 类型          | 默认值  | 描述           |
| :-------- | :---------- | :--- | :----------- |
| `file`    | `list[str]` | `[]` | 要忽略违规的文件路径模式 |
| `network` | `list[str]` | `[]` | 要忽略违规的网络模式   |

<h3 id="permissions-fallback-for-unsandboxed-commands">
  沙箱外命令的权限回退
</h3>

当 `allowUnsandboxedCommands` 启用时，模型可以通过在工具输入中设置 `dangerouslyDisableSandbox: True` 来请求在沙箱外运行命令。这些请求回退到现有权限系统，意味着你的 `can_use_tool` 处理程序将被调用，允许你实现自定义授权逻辑。

<Note>
  **`excludedCommands` vs `allowUnsandboxedCommands`：**

  * `excludedCommands`：始终自动绕过沙箱的命令的静态列表（例如 `["docker"]`）。模型对此无控制权。
  * `allowUnsandboxedCommands`：让模型在运行时通过在工具输入中设置 `dangerouslyDisableSandbox: True` 来决定是否请求沙箱外执行。
</Note>

```python theme={null}
from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)


async def can_use_tool(
    tool: str, input: dict, context: ToolPermissionContext
) -> PermissionResultAllow | PermissionResultDeny:
    # Check if the model is requesting to bypass the sandbox
    if tool == "Bash" and input.get("dangerouslyDisableSandbox"):
        # The model is requesting to run this command outside the sandbox
        print(f"Unsandboxed command requested: {input.get('command')}")

        if is_command_authorized(input.get("command")):
            return PermissionResultAllow()
        return PermissionResultDeny(
            message="Command not authorized for unsandboxed execution"
        )
    return PermissionResultAllow()


# Required: dummy hook keeps the stream open for can_use_tool
async def dummy_hook(input_data, tool_use_id, context):
    return {"continue_": True}


async def prompt_stream():
    yield {
        "type": "user",
        "message": {"role": "user", "content": "Deploy my application"},
    }


async def main():
    async for message in query(
        prompt=prompt_stream(),
        options=ClaudeAgentOptions(
            sandbox={
                "enabled": True,
                "allowUnsandboxedCommands": True,  # Model can request unsandboxed execution
            },
            permission_mode="default",
            can_use_tool=can_use_tool,
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[dummy_hook])]},
        ),
    ):
        print(message)
```

此模式使你能够：

* **审计模型请求**：记录模型何时请求沙箱外执行
* **实现允许列表**：仅允许特定命令在沙箱外运行
* **添加批准工作流**：需要显式授权以进行特权操作

<Warning>
  使用 `dangerouslyDisableSandbox: True` 运行的命令具有完整的系统访问权限。确保你的 `can_use_tool` 处理程序仔细验证这些请求。

  如果 `permission_mode` 设置为 `bypassPermissions` 且 `allow_unsandboxed_commands` 启用，模型可以自主执行沙箱外的命令，无需任何批准提示。此组合实际上允许模型无声地逃离沙箱隔离。
</Warning>

<h2 id="see-also">
  另见
</h2>

* [SDK 概述](/docs/zh-CN/agent-sdk/overview) - 一般 SDK 概念
* [TypeScript SDK 参考](/docs/zh-CN/agent-sdk/typescript) - TypeScript SDK 文档
* [CLI 参考](/docs/zh-CN/cli-reference) - 命令行界面
* [常见工作流](/docs/zh-CN/common-workflows) - 分步指南
