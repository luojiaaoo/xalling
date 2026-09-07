# Xalling

> Your Desktop, Reimagined with AI.

Xalling 是一个本地优先的 AI 桌面工作台：以 Python 管理业务与智能体，以 pywebview 承载 React 界面，并通过安全、直接的 JavaScript–Python 桥接完成交互。它不把本地 HTTP 服务当作前后端中间层。

## 产品方向

界面采用深色、低干扰的桌面工作台风格。参考设计为：左侧常驻导航与项目/任务区，中央保留大面积对话或工作区，输入框位于视觉焦点，快捷任务以轻量卡片呈现。目标是在高信息密度下保持清晰的层级、状态反馈和可操作性。

典型能力包括：

- 新建与管理 AI 任务、项目和会话
- 在统一对话界面中调用本地 Python 能力和智能体
- 将任务进度、统计与趋势以卡片和图表展示
- 为文件、命令等敏感工具调用提供明确的确认与结果反馈

## 架构

```mermaid
flowchart LR
  UI[React + TypeScript<br/>Ant Design / Ant Design X / Charts]
  Bridge[pywebview JS–Python bridge]
  App[Python application<br/>domain services & bridge API]
  Agent[Microsoft Agent Framework<br/>Python agents & workflows]

  UI <--> |window.pywebview.api<br/>controlled evaluate_js callbacks| Bridge
  Bridge <--> App
  App <--> Agent
```

所有业务数据都经 pywebview 的 JS–Python 桥传递；Python 服务不监听 localhost 端口，前端也不通过 `fetch`、Axios、WebSocket 或 SSE 调用本地后端。

## 技术栈

| 层级 | 选型 | 用途 |
| --- | --- | --- |
| 桌面容器 | [pywebview](https://pywebview.flowrl.com/) | 原生窗口、加载本地 Web UI、JS–Python 桥 |
| 后端 | Python 3.12 + `uv` | 领域逻辑、文件与系统能力、桥接 API、测试与依赖管理 |
| 基础 UI | [Ant Design](https://ant.design/components/overview-cn/) | 桌面布局、表单、数据展示、导航和反馈组件 |
| AI UI | [Ant Design X](https://x.ant.design/components/introduce-cn/) | 会话、消息气泡、输入、快捷提示、思考/任务状态等 AI 交互组件 |
| 图表 | [Ant Design Charts](https://charts.ant.design/examples/statistics/line/#basic) | 任务趋势、统计和分析视图；连续数据优先使用折线图 |
| 智能体 | [Microsoft Agent Framework](https://learn.microsoft.com/zh-cn/agent-framework/get-started/your-first-agent?pivots=programming-language-python) | Python 智能体、工具调用、会话记忆与工作流编排 |

Microsoft Agent Framework 在本项目中使用 **Python SDK**；文档中切换到 Go 的示例不适用于本项目的后端实现。

## 通信契约

### 前端调用 Python

Python 通过 `js_api` 暴露 API，前端统一从一个桥接模块调用：

```ts
const result = await window.pywebview.api.create_task({ prompt });
```

桥接调用必须是异步的，并在 UI 中体现加载、成功和错误状态。参数和返回值只使用可 JSON 序列化的数据，避免把底层 Python 对象泄漏到界面。

### Python 推送界面

长任务或智能体流式执行时，Python 使用 `window.evaluate_js(...)` 调用前端预先注册的受控回调。前端将事件归并到状态管理层，再渲染 Ant Design X 的消息、思考链或任务状态。

### 明确禁止

- 不使用 Flask、FastAPI、Django、aiohttp、uvicorn 等方式为 UI 提供业务 HTTP API。
- 不使用 REST、`fetch`、Axios、XHR、WebSocket、SSE 或 localhost 端口在本地前后端间传输业务数据。
- 不将密钥、模型配置或 Python 内部对象传入前端。

### 桥接实现要求

- 前端必须等待 `pywebviewready` 事件后再调用桥接 API。
- Python 通过 `webview.create_window(..., js_api=api)` 暴露职责单一的 API；所有入参须进行类型、长度与权限校验。
- 返回值只使用 JSON 可序列化数据。使用 `evaluate_js` 推送事件时，必须通过受控回调传递已安全编码的数据，避免拼接不受信任的脚本。
- 桥接 API 集中封装在一个前端模块中；业务组件不得散落直接调用 `window.pywebview.api`。

## 项目状态与目录规划

当前仓库已具备 Python 3.12、`uv`、pywebview 及基础窗口骨架。随着界面实现推进，代码按以下边界组织：

```text
main.py                 # 窗口创建和应用生命周期
backend/                # 领域服务、桥接 API、agents/
frontend/               # React + TypeScript 源码
frontend/dist/          # 构建后的本地静态资源
tests/                  # Python 与桥接契约测试
```

前端构建产物由 pywebview 从本地加载；无论开发还是发布，业务交互都保持通过桥接而非 HTTP。

## 实现约定

### 前端

- 优先使用 Ant Design 的 `Layout`、`Menu`、`Card`、`Form`、`Table` 与 `ConfigProvider` 构建可访问、高信息密度的桌面界面。
- AI 对话与任务交互优先使用 Ant Design X 的 `Welcome`、`Conversations`、`Bubble`、`Sender`、`ThoughtChain` 和 `Actions`。
- 图表采用 Ant Design Charts；连续时间趋势优先使用折线图。图表容器必须具有明确宽高，并在页面销毁时释放实例。
- 所有前端代码使用 TypeScript。开发组件前先查询对应版本的官方 API 与示例，不凭记忆猜测属性。

### Python 与智能体

- Python 负责领域服务、桥接 API、智能体运行与敏感能力控制；不得阻塞 pywebview UI 线程。
- 长任务应在受管控的异步或后台执行单元中运行，并通过桥接持续回传状态、增量和最终结果。
- 智能体采用 Microsoft Agent Framework Python SDK。代理、工具、会话/记忆与工作流均封装在 Python 层。
- 工具调用遵循最小权限原则；文件、命令或外部服务操作必须由用户清晰触发，并提供进度、确认和结果反馈。
- 模型端点、密钥和其他敏感配置仅放在环境变量或本地安全配置中，不得进入前端 bundle、源码或日志。

## 快速开始

前置条件：Python 3.12，以及已安装的 [uv](https://docs.astral.sh/uv/)。

```powershell
uv sync
cd frontend
npm install
npm run build
cd ..
uv run python main.py
```

## 开发命令

```powershell
# 静态检查
uv run ruff check .

# 运行测试
uv run pytest

# 检查并构建本地前端资源
cd frontend
npm run check
npm run build
```

修改桥接 API 后，请同时验证：正常调用、非法参数、Python 异常回传，以及长任务状态推送。新增界面时，优先复用 Ant Design 和 Ant Design X 组件，并确保图表容器有明确尺寸。

## 后续实施顺序

1. 建立 `frontend/` 的 React + TypeScript 工程，引入 Ant Design、Ant Design X 与 Ant Design Charts。
2. 将当前内联 HTML 替换为本地构建产物，并实现统一的桥接 API 客户端。
3. 在 `backend/` 中建立领域服务和桥接 API；为契约增加测试。
4. 接入 Microsoft Agent Framework Python SDK，实现可观察、可取消的智能体任务。
5. 落地任务、项目、会话与趋势图等核心工作台界面。
