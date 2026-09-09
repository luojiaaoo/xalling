# Claude Agent SDK Python 官方参考索引

本索引用于定位 `official-api-reference.zh-CN.md` 中的完整官方内容。使用标题 ID 或 API 名称搜索，并只读取完成当前任务所需的章节。

## 入门与入口选择

- `installation`：虚拟环境安装、系统 Python 的 externally-managed-environment 限制、概述页链接。
- `choosing-between-query-and-claudesdkclient`：会话、上下文、连接、流式输入、中断、Hook、自定义工具、继续聊天和适用场景的比较。

## 函数

- `query`：签名、参数、异步消息迭代器返回值、带选项示例。
- `tool`：类型安全 MCP 工具装饰器、简单类型映射、JSON Schema、返回类型、示例。
- `toolannotations`：标题与只读、破坏性、幂等、开放世界提示；默认值和安全边界。
- `create_sdk_mcp_server`：进程内 MCP 服务器、版本与工具列表、注册到 `mcp_servers`、允许工具命名。
- `list_sessions`：目录过滤、分页、worktree 行为、`SDKSessionInfo` 全部字段、排序。
- `get_session_messages`：目录搜索、分页、`SessionMessage` 全部字段。
- `get_session_info`：按 UUID 读取单会话元数据及未找到语义。
- `rename_session`：标题追加、幂等性、参数校验、异常。
- `tag_session`：标签设置/清除、Unicode 清理、幂等性、异常。

## 客户端类

- `claudesdkclient`：构造方式、关键特性和全部方法。
- 方法表覆盖连接/断开、查询、接收响应/消息、中断、权限模式、模型切换、MCP 状态、倒回文件和服务器信息。
- 示例覆盖 async context manager、连续对话、流式输入、中断和高级权限控制。

## 配置与核心类型

- `sdkmcptool`、`transport`。
- `claudeagentoptions`：全部字段、类型、默认值与说明；另含慢速/停滞响应处理。
- `outputformat`、`systempromptpreset`、`systempromptfile`。
- `settingsource`：默认行为、为何显式配置、优先级和 `CLAUDE.md`/磁盘设置加载。
- `agentdefinition`、`permissionmode`、`effortlevel`。
- `canusetool`、`toolpermissioncontext`、`permissionresult`、`permissionresultallow`、`permissionresultdeny`、`permissionupdate`、`permissionrulevalue`。
- `toolspreset`、`thinkingconfig`、`sdkbeta`。
- `mcpsdkserverconfig`、`mcpserverconfig`、`mcpstdioserverconfig`、`mcpsseserverconfig`、`mcphttpserverconfig`。
- `mcpserverstatusconfig`、`mcpstatusresponse`、`mcpserverstatus`、`sdkpluginconfig`。

## 消息、内容块与错误

- `message-types`：`Message` 联合及 `UserMessage`、`AssistantMessage`、`AssistantMessageError`、`SystemMessage`、`ResultMessage` 的全部字段。
- 流式/运行状态：`StreamEvent`、`RateLimitEvent`、`RateLimitInfo`、`TaskStartedMessage`、`TaskUsage`、`TaskProgressMessage`、`TaskNotificationMessage`。
- `content-block-types`：`ContentBlock`、`TextBlock`、`ThinkingBlock`、`ToolUseBlock`、`ToolResultBlock`。
- `error-types`：`ClaudeSDKError`、`CLINotFoundError`、`CLIConnectionError`、`ProcessError`、`CLIJSONDecodeError` 的继承关系和字段。

## Hooks

- `hookevent`、`hookcallback`、`hookcontext`、`hookmatcher`、`hookinput`、`basehookinput`。
- 事件输入：`pretoolusehookinput`、`posttoolusehookinput`、`posttoolusefailurehookinput`、`userpromptsubmithookinput`、`stophookinput`、`subagentstophookinput`、`precompacthookinput`、`notificationhookinput`、`subagentstarthookinput`、`permissionrequesthookinput`。
- 输出：`hookjsonoutput`、`synchookjsonoutput`、`hookspecificoutput`、`asynchookjsonoutput`。
- `hook-usage-example`：按工具匹配、阻止危险命令、修改工具输入。

## 内置工具输入/输出

`tool-input/output-types` 逐项给出 TypedDict 定义、字段含义、可选值与输出形状：

- `agent`、`askuserquestion`。
- `bash`、`monitor`、`bashoutput`、`killbash`。
- `edit`、`read`、`write`、`glob`、`grep`、`notebookedit`。
- `webfetch`、`websearch`。
- `todowrite`、`taskcreate`、`taskupdate`、`taskget`、`tasklist`。
- `exitplanmode`。
- `listmcpresources`、`readmcpresource`。

## 高级模式与完整示例

- `advanced-features-with-claudesdkclient`：持续对话界面、使用 Hook 修改行为、实时进度监控。
- `example-usage`：基本文件操作、错误处理、客户端流式模式、客户端自定义工具。

## 沙箱

- `sandboxsettings`：所有设置字段和示例。
- `sandboxnetworkconfig`：网络限制字段。
- `sandboxignoreviolations`：忽略违规的配置形状。
- `permissions-fallback-for-unsandboxed-commands`：`excludedCommands` 与 `allowUnsandboxedCommands` 的差别、`dangerouslyDisableSandbox` 请求、权限回调、dummy Hook 要求和高风险组合警告。

## 精确检索

优先按标题 ID 检索：

```powershell
rg -n '<h[234] id="ID">' references/official-api-reference.zh-CN.md
```

查字段或字面量时直接搜索代码标识符：

```powershell
rg -n 'setting_sources|include_partial_messages|max_turns|bypassPermissions' references/official-api-reference.zh-CN.md
```

找到起始行后，读取到下一个同级标题为止。不要只读命中行，因为默认值、限制、示例和警告通常位于后续段落。

## 补充精确锚点

下列二、三级标题已在上文按主题归类；这里保留其精确 ID，确保官方快照的每个二、三级章节都能直接检索：

- 入口选择：`quick-comparison`、`when-to-use-query-one-off-tasks`、`when-to-use-claudesdkclient-continuous-conversation`。
- 顶层分类：`functions`、`classes`、`types`、`hook-types`、`sandbox-configuration`、`see-also`。
- 消息：`message`、`usermessage`、`assistantmessage`、`assistantmessageerror`、`systemmessage`、`resultmessage`、`streamevent`、`ratelimitevent`、`ratelimitinfo`、`taskstartedmessage`、`taskusage`、`taskprogressmessage`、`tasknotificationmessage`。
- 内容块：`contentblock`、`textblock`、`thinkingblock`、`tooluseblock`、`toolresultblock`。
- 错误：`claudesdkerror`、`clinotfounderror`、`cliconnectionerror`、`processerror`、`clijsondecodeerror`。
- 高级客户端模式：`building-a-continuous-conversation-interface`、`using-hooks-for-behavior-modification`、`real-time-progress-monitoring`。
- 完整示例：`basic-file-operations-using-query`、`error-handling`、`streaming-mode-with-client`、`using-custom-tools-with-claudesdkclient`。
