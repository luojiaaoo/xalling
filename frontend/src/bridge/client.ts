export type ApiProtocol = "anthropic" | "chat" | "responses";

import { notifyBridgeError } from "./bridgeMessage";

type PyWebviewApi = {
  minimize_window: () => Promise<void>;
  toggle_maximize_window: () => Promise<{ maximized: boolean }>;
  close_window: () => Promise<void>;
  resize_window: (width: number, height: number, edge: string) => Promise<void>;
  select_project_folder: () => Promise<ProjectFolder | null>;
  get_home_folder: () => Promise<ProjectFolder>;
  search_project_files: (
    projectPath: string,
    query: string,
    limit?: number,
  ) => Promise<ProjectFileMatch[]>;
  save_attachment: (
    filename: string,
    data: string,
  ) => Promise<{ path: string; name: string }>;
  get_commands: (
    sessionId: string,
    projectPath: string | null,
    effort: ChatEffort,
    permissionMode: ChatPermissionMode,
  ) => Promise<ClaudeCommand[]>;
  get_allowed_command_names: () => Promise<string[]>;
  get_skills: (
    sessionId: string,
    projectPath: string | null,
    effort: ChatEffort,
    permissionMode: ChatPermissionMode,
  ) => Promise<ClaudeCommand[]>;
  get_model_groups: () => Promise<ModelGroup[]>;
  get_model_sites: () => Promise<ModelSite[]>;
  fetch_model_names: (apiUrl: string, apiKey: string) => Promise<string[]>;
  save_model_site: (
    originalName: string | null,
    name: string,
    apiUrl: string,
    apiKey: string,
    models: ModelConfig[],
    apiProtocol?: ApiProtocol,
  ) => Promise<void>;
  delete_model_site: (name: string) => Promise<void>;
  get_current_model: () => Promise<ModelSelection | null>;
  set_current_model: (site: string, model: string) => Promise<void>;
  send_chat_message: (
    prompt: string,
    projectPath: string | null,
    sessionId: string,
    effort: ChatEffort,
    permissionMode: ChatPermissionMode,
  ) => Promise<ChatReply>;
  set_chat_permission_mode: (
    sessionId: string,
    permissionMode: ChatPermissionMode,
    projectPath: string | null,
    effort: ChatEffort,
  ) => Promise<boolean>;
  list_chat_sessions: () => Promise<ChatSessionSummary[]>;
  list_scheduled_tasks: (projectPath: string | null) => Promise<ScheduledTaskSummary[]>;
  list_all_scheduled_tasks: () => Promise<ScheduledTaskSummary[]>;
  search_chat_sessions: (query: string) => Promise<ChatSearchMatch[]>;
  get_chat_session: (
    projectPath: string | null,
    sessionId: string,
    effort: ChatEffort,
    permissionMode: ChatPermissionMode,
  ) => Promise<ChatSessionHistory>;
  get_active_chat: (sessionId: string) => Promise<ActiveChat | null>;
  get_context_usage: (sessionId: string) => Promise<ContextUsage | null>;
  stop_chat_message: (sessionId: string | null) => Promise<boolean>;
  close_chat_client: (sessionId: string | null) => Promise<boolean>;
  respond_chat_permission: (
    permissionId: string,
    allowed: boolean,
    answers: ChatPermissionAnswers | null,
    feedback: string | null,
    executionMode: ChatPlanExecutionMode | null,
  ) => Promise<boolean>;
  get_current_theme: () => Promise<string>;
  set_current_theme: (name: string) => Promise<void>;
  list_tutorials: () => Promise<TutorialSummary[]>;
  get_tutorial: (tutorialId: string) => Promise<TutorialDocument>;
  report_frontend_error: (
    kind: string,
    message: string,
    stack: string | null,
  ) => Promise<void>;
};

// 本地教程：id 为 tutorials 目录下的 Markdown 文件名，标题取自文件首个一级标题
export type TutorialSummary = {
  id: string;
  title: string;
};

export type TutorialDocument = TutorialSummary & {
  content: string;
};

export type ModelGroup = {
  name: string;
  models: ModelConfig[];
};

export type ModelConfig = {
  name: string;
  image_vision: boolean;
  max_context_tokens: number | null;
};

export type ModelSite = {
  name: string;
  api_url: string;
  api_key: string;
  models: ModelConfig[];
  api_protocol: ApiProtocol;
};

export type ModelSelection = {
  site: string;
  model: string;
};

export type ProjectFolder = {
  name: string;
  path: string;
};

export type ProjectFileMatch = {
  name: string;
  path: string;
  relative: string;
  is_dir: boolean;
};

// Claude 运行时暴露的斜杠条目（技能或常规命令，由后端 CommandRouter 返回）
export type ClaudeCommand = {
  name: string;
  description: string;
  argument_hint: string;
  aliases: string[];
};

export type ChatEffort = "low" | "medium" | "high" | "max";

export type ChatPermissionMode =
  | "default"
  | "acceptEdits"
  | "plan"
  | "auto"
  | "bypassPermissions";

export type ChatPlanExecutionMode = "default" | "acceptEdits" | "auto";

export type SubagentUsage = {
  count: number;
  total_tokens: number;
};

export type ChatUsage = {
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
  input_tokens: number;
  model: string | null;
  output_tokens: number;
  stop_reason: string | null;
  subagent_usage?: SubagentUsage | null;
  terminal_reason: string | null;
};

export type ContextUsageCategory = {
  color: string;
  isDeferred?: boolean;
  name: string;
  tokens: number;
};

export type ContextUsage = {
  agents: Record<string, unknown>[];
  categories: ContextUsageCategory[];
  gridRows: Record<string, unknown>[][];
  isAutoCompactEnabled: boolean;
  maxTokens: number;
  mcpTools: Record<string, unknown>[];
  memoryFiles: Record<string, unknown>[];
  model: string;
  percentage: number;
  rawMaxTokens: number;
  totalTokens: number;
};

export type ChatReply = {
  content: string;
  duration_api_ms: number;
  duration_ms: number;
  errors: string[];
  is_error: boolean;
  session_id: string;
  subtype: string;
  usage: ChatUsage;
};

export type ChatSessionSummary = {
  created_at: number | null;
  custom_title: string | null;
  cwd: string | null;
  file_size: number | null;
  first_prompt: string | null;
  git_branch: string | null;
  last_modified: number;
  running?: boolean;
  session_id: string;
  summary: string;
  tag: string | null;
  title: string;
};

export type ScheduledTaskSummary = {
  task_id: string;
  session_id: string;
  title: string;
  prompt: string;
  workspace_path: string;
  permission_mode: string;
  effort: string;
  schedule_type: "interval" | "date" | "cron";
  schedule_value: string;
  created_at: string;
  next_run_time: string | null;
};

/** 一条搜索命中：turn_id + role 可直接定位到统一事件生成的气泡。 */
export type ChatSearchMatch = ChatSessionSummary & {
  event_id: string | null;
  role: "user" | "assistant" | null;
  snippet: string;
  turn_id: string | null;
};

export type ChatSessionHistory = ChatSessionSummary & {
  events: ChatRenderEvent[];
  render_events?: unknown;
  permission_mode?: ChatPermissionMode;
};

export type ChatUserQuestionOption = {
  description: string;
  label: string;
};

export type ChatUserQuestion = {
  header: string;
  multiSelect: boolean;
  options: ChatUserQuestionOption[];
  question: string;
};

export type ChatPermissionAnswers = Record<string, string | string[]>;

export type ChatRenderEvent = {
  created_at: string;
  data: Record<string, unknown>;
  /** @deprecated Use kind. */
  event: string;
  kind: string;
  id: string;
  model_turn_id: string | null;
  parent_tool_use_id: string | null;
  session_id: string | null;
  turn_id: string;
};

export type ChatPermissionRequestEvent = ChatRenderEvent & {
  data: {
    blocked_path: string | null;
    description: string | null;
    display_name: string | null;
    request_id: string;
    suggestions: Record<string, unknown>[];
    title: string | null;
    tool_id: string | null;
    tool_input: Record<string, unknown>;
    tool_name: string;
  };
  kind: "permission.requested";
};

export type ChatAskUserQuestionRequestEvent = ChatPermissionRequestEvent & {
  data: ChatPermissionRequestEvent["data"] & {
    tool_input: {
      answers?: ChatPermissionAnswers | null;
      questions: ChatUserQuestion[];
    };
    tool_name: "AskUserQuestion";
  };
};

export type ActiveChat = {
  events: ChatRenderEvent[];
  render_events?: unknown;
  session_id: string;
};

const CHAT_STREAM_EVENT = "xalling:chat-event";

function isChatRenderEvent(value: unknown): value is ChatRenderEvent {
  return typeof value === "object"
    && value !== null
    && "id" in value
    && typeof value.id === "string"
    && "kind" in value
    && typeof value.kind === "string"
    && "turn_id" in value
    && typeof value.turn_id === "string"
    && "model_turn_id" in value
    && (
      value.model_turn_id === null
      || typeof value.model_turn_id === "string"
    )
    && "data" in value
    && typeof value.data === "object"
    && value.data !== null
    && !Array.isArray(value.data)
    && "created_at" in value
    && typeof value.created_at === "string"
    && "session_id" in value
    && (value.session_id === null || typeof value.session_id === "string")
    && "parent_tool_use_id" in value
    && (
      value.parent_tool_use_id === null
      || typeof value.parent_tool_use_id === "string"
    );
}

type ChatEventEnvelope = {
  render?: unknown;
  session_id?: unknown;
};

function decodeChatRenderEvent(value: unknown): ChatRenderEvent | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const envelope = value as ChatEventEnvelope;
  // The Python bridge owns SDK -> UI normalization. Raw envelopes are
  // intentionally rejected so rendering code cannot depend on SDK payloads.
  if (
    typeof envelope.render !== "object"
    || envelope.render === null
    || !("event" in envelope.render)
    || typeof envelope.render.event !== "string"
  ) {
    return null;
  }
  const render = envelope.render as Omit<ChatRenderEvent, "kind"> & { event: string };
  const decoded = { ...render, kind: render.event };
  if (render.session_id === null && typeof envelope.session_id === "string") {
    return { ...decoded, session_id: envelope.session_id };
  }
  return decoded;
}

function decodeEventList(value: unknown): ChatRenderEvent[] {
  return Array.isArray(value)
    ? value
      .map(decodeChatRenderEvent)
      .filter((event): event is ChatRenderEvent => event !== null)
    : [];
}

export function isPermissionRequestEvent(
  event: ChatRenderEvent,
): event is ChatPermissionRequestEvent {
  const data = event.data;
  return event.kind === "permission.requested"
    && typeof data.request_id === "string"
    && typeof data.tool_name === "string"
    && typeof data.tool_input === "object"
    && data.tool_input !== null
    && !Array.isArray(data.tool_input)
    && Array.isArray(data.suggestions);
}

function isUserQuestionOption(value: unknown): value is ChatUserQuestionOption {
  return typeof value === "object"
    && value !== null
    && "label" in value
    && typeof value.label === "string"
    && "description" in value
    && typeof value.description === "string";
}

function isUserQuestion(value: unknown): value is ChatUserQuestion {
  return typeof value === "object"
    && value !== null
    && "question" in value
    && typeof value.question === "string"
    && "header" in value
    && typeof value.header === "string"
    && "multiSelect" in value
    && typeof value.multiSelect === "boolean"
    && "options" in value
    && Array.isArray(value.options)
    && value.options.every(isUserQuestionOption);
}

export function isAskUserQuestionRequest(
  request: ChatPermissionRequestEvent,
): request is ChatAskUserQuestionRequestEvent {
  const questions = request.data.tool_input.questions;
  return request.data.tool_name === "AskUserQuestion"
    && Array.isArray(questions)
    && questions.length > 0
    && questions.length <= 4
    && questions.every(isUserQuestion);
}

declare global {
  interface Window {
    pywebview?: { api: PyWebviewApi };
  }
}

export async function minimizeWindow(): Promise<void> {
  await window.pywebview?.api.minimize_window();
}

export async function toggleMaximizeWindow(): Promise<boolean> {
  const result = await window.pywebview?.api.toggle_maximize_window();
  return result?.maximized ?? false;
}

export async function closeWindow(): Promise<void> {
  await window.pywebview?.api.close_window();
}

export async function resizeWindow(width: number, height: number, edge: string): Promise<void> {
  await window.pywebview?.api.resize_window(width, height, edge);
}

export async function selectProjectFolder(): Promise<ProjectFolder | null> {
  const api = await getBridgeApi();
  return (await api?.select_project_folder()) ?? null;
}

export async function getHomeFolder(): Promise<ProjectFolder | null> {
  const api = await getBridgeApi();
  return (await api?.get_home_folder()) ?? null;
}

export async function searchProjectFiles(
  projectPath: string,
  query: string,
  limit = 30,
): Promise<ProjectFileMatch[]> {
  const api = await getBridgeApi();
  return (await api?.search_project_files(projectPath, query, limit)) ?? [];
}

export async function saveAttachment(
  filename: string,
  data: string,
): Promise<{ path: string; name: string }> {
  const api = await getBridgeApi();
  if (!api) {
    throw new Error("桌面应用桥接尚未准备好");
  }
  return api.save_attachment(filename, data);
}

export async function getCommands(
  sessionId: string,
  projectPath: string | null,
  effort: ChatEffort,
  permissionMode: ChatPermissionMode,
): Promise<ClaudeCommand[]> {
  const api = await getBridgeApi();
  return (
    (await api?.get_commands(sessionId, projectPath, effort, permissionMode)) ?? []
  );
}

export async function getAllowedCommandNames(): Promise<string[]> {
  const api = await getBridgeApi();
  return (await api?.get_allowed_command_names()) ?? [];
}

export async function getSkills(
  sessionId: string,
  projectPath: string | null,
  effort: ChatEffort,
  permissionMode: ChatPermissionMode,
): Promise<ClaudeCommand[]> {
  const api = await getBridgeApi();
  return (
    (await api?.get_skills(sessionId, projectPath, effort, permissionMode)) ?? []
  );
}

async function getBridgeApi(): Promise<PyWebviewApi | undefined> {
  if (window.pywebview?.api) {
    return withErrorNotifier(window.pywebview.api);
  }

  if (window.location.protocol === "file:") {
    await new Promise<void>((resolve) => {
      window.addEventListener("pywebviewready", () => resolve(), { once: true });
    });
  }

  const api = window.pywebview?.api;
  return api ? withErrorNotifier(api) : undefined;
}

const bridgeApiProxyCache = new WeakMap<PyWebviewApi, PyWebviewApi>();

// 统一包装 js2py 调用：后端抛出的异常先通过 message 提示，再继续向上抛出，
// 保证调用方原有的错误处理逻辑不受影响。report_frontend_error 自身不上浮提示，
// 避免错误上报失败时又触发新的提示形成循环。
function withErrorNotifier(api: PyWebviewApi): PyWebviewApi {
  const cached = bridgeApiProxyCache.get(api);
  if (cached) {
    return cached;
  }
  const proxy = new Proxy(api, {
    get(target, prop, receiver) {
      const value = Reflect.get(target, prop, receiver);
      if (typeof value !== "function" || prop === "report_frontend_error") {
        return value;
      }
      const call = value as unknown as (...args: unknown[]) => unknown;
      return async (...args: unknown[]) => {
        try {
          return await Reflect.apply(call, target, args);
        } catch (error) {
          notifyBridgeError(String(prop), error);
          throw error;
        }
      };
    },
  });
  bridgeApiProxyCache.set(api, proxy);
  return proxy;
}

export async function getModelGroups(): Promise<ModelGroup[]> {
  const api = await getBridgeApi();
  return (await api?.get_model_groups()) ?? [];
}

export async function getModelSites(): Promise<ModelSite[]> {
  const api = await getBridgeApi();
  return (await api?.get_model_sites()) ?? [];
}

export async function fetchModelNames(
  apiUrl: string,
  apiKey: string,
): Promise<string[]> {
  const api = await getBridgeApi();
  if (!api) {
    throw new Error("桌面应用桥接尚未准备好");
  }
  return api.fetch_model_names(apiUrl, apiKey);
}

export async function saveModelSite(
  originalName: string | null,
  name: string,
  apiUrl: string,
  apiKey: string,
  models: ModelConfig[],
  apiProtocol: ApiProtocol = "anthropic",
): Promise<void> {
  const api = await getBridgeApi();
  if (!api) {
    throw new Error("桌面应用桥接尚未准备好");
  }
  await api.save_model_site(
    originalName,
    name,
    apiUrl,
    apiKey,
    models,
    apiProtocol,
  );
}

export async function deleteModelSite(name: string): Promise<void> {
  const api = await getBridgeApi();
  if (!api) {
    throw new Error("桌面应用桥接尚未准备好");
  }
  await api.delete_model_site(name);
}

export async function getCurrentModel(): Promise<ModelSelection | null> {
  const api = await getBridgeApi();
  return (await api?.get_current_model()) ?? null;
}

export async function setCurrentModel(site: string, model: string): Promise<void> {
  const api = await getBridgeApi();
  await api?.set_current_model(site, model);
}

export async function sendChatMessage(
  prompt: string,
  projectPath: string | null,
  sessionId: string,
  effort: ChatEffort,
  permissionMode: ChatPermissionMode,
): Promise<ChatReply> {
  const api = await getBridgeApi();
  if (!api) {
    throw new Error("桌面应用桥接尚未准备好");
  }

  return api.send_chat_message(
    prompt,
    projectPath,
    sessionId,
    effort,
    permissionMode,
  );
}

export async function setChatPermissionMode(
  sessionId: string,
  permissionMode: ChatPermissionMode,
  projectPath: string | null,
  effort: ChatEffort,
): Promise<boolean> {
  const api = await getBridgeApi();
  if (!api) {
    throw new Error("妗岄潰搴旂敤妗ユ帴灏氭湭鍑嗗濂?");
  }
  return api.set_chat_permission_mode(
    sessionId,
    permissionMode,
    projectPath,
    effort,
  );
}

export async function listChatSessions(): Promise<ChatSessionSummary[]> {
  const api = await getBridgeApi();
  return (await api?.list_chat_sessions()) ?? [];
}

export async function listScheduledTasks(
  projectPath: string | null,
): Promise<ScheduledTaskSummary[]> {
  const api = await getBridgeApi();
  return (await api?.list_scheduled_tasks(projectPath)) ?? [];
}

export async function listAllScheduledTasks(): Promise<ScheduledTaskSummary[]> {
  const api = await getBridgeApi();
  return (await api?.list_all_scheduled_tasks()) ?? [];
}

export async function searchChatSessions(query: string): Promise<ChatSearchMatch[]> {
  const api = await getBridgeApi();
  return (await api?.search_chat_sessions(query)) ?? [];
}

export async function getChatSession(
  sessionId: string,
  projectPath: string | null,
  effort: ChatEffort,
  permissionMode: ChatPermissionMode,
): Promise<ChatSessionHistory> {
  const api = await getBridgeApi();
  if (!api) {
    throw new Error("桌面应用桥接尚未准备好");
  }
  const result = await api.get_chat_session(projectPath, sessionId, effort, permissionMode);
  return {
    ...result,
    events: decodeEventList(result.render_events ?? result.events),
  };
}

export async function getActiveChat(sessionId: string): Promise<ActiveChat | null> {
  const api = await getBridgeApi();
  if (!api) {
    throw new Error("桌面应用桥接尚未准备好");
  }
  const result = await api.get_active_chat(sessionId);
  return result
    ? { ...result, events: decodeEventList(result.render_events ?? result.events) }
    : null;
}

export async function getContextUsage(sessionId: string): Promise<ContextUsage | null> {
  const api = await getBridgeApi();
  return (await api?.get_context_usage(sessionId)) ?? null;
}

export function subscribeChatEvents(
  sessionId: string,
  onEvent: (event: ChatRenderEvent) => void,
): () => void {
  const handleStreamEvent: EventListener = (event) => {
    const detail = (event as CustomEvent<unknown>).detail;
    const renderEvent = decodeChatRenderEvent(detail);
    if (renderEvent?.session_id === sessionId) {
      onEvent(renderEvent);
    }
  };
  window.addEventListener(CHAT_STREAM_EVENT, handleStreamEvent);
  return () => window.removeEventListener(CHAT_STREAM_EVENT, handleStreamEvent);
}

export async function stopChatMessage(sessionId: string | null): Promise<boolean> {
  const api = await getBridgeApi();
  if (!api) {
    throw new Error("桌面应用桥接尚未准备好");
  }
  return api.stop_chat_message(sessionId);
}

export async function closeChatClient(sessionId: string | null): Promise<boolean> {
  const api = await getBridgeApi();
  return (await api?.close_chat_client(sessionId)) ?? false;
}

export async function respondChatPermission(
  permissionId: string,
  allowed: boolean,
  answers?: ChatPermissionAnswers,
  feedback?: string,
  executionMode?: ChatPlanExecutionMode,
): Promise<boolean> {
  const api = await getBridgeApi();
  if (!api) {
    throw new Error("桌面应用桥接尚未准备好");
  }
  return api.respond_chat_permission(
    permissionId,
    allowed,
    answers ?? null,
    feedback?.trim() || null,
    executionMode ?? null,
  );
}

export async function getCurrentTheme(): Promise<string> {
  const api = await getBridgeApi();
  return (await api?.get_current_theme()) ?? "default";
}

export async function setCurrentTheme(name: string): Promise<void> {
  const api = await getBridgeApi();
  if (!api) {
    throw new Error("桌面应用桥接尚未准备好");
  }
  await api.set_current_theme(name);
}

export async function listTutorials(): Promise<TutorialSummary[]> {
  const api = await getBridgeApi();
  return (await api?.list_tutorials()) ?? [];
}

export async function getTutorial(tutorialId: string): Promise<TutorialDocument | null> {
  const api = await getBridgeApi();
  return (await api?.get_tutorial(tutorialId)) ?? null;
}

export async function reportFrontendError(
  kind: string,
  message: string,
  stack: string | null,
): Promise<void> {
  // 静默上报：桥接不可用（如纯浏览器调试）时直接丢弃，不能再产生新错误
  const api = await getBridgeApi();
  await api?.report_frontend_error(kind, message, stack);
}
