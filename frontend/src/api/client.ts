export type ApiProtocol = "anthropic" | "chat" | "responses";

import { TRANSPORT_READY_EVENT } from "./websocket";
import { request } from "./http";
export { TransportDisconnectedError } from "./websocket";

type ApplicationApi = {
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
    modelSite?: string | null,
    model?: string | null,
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
  delete_scheduled_task: (
    taskId: string,
    projectPath: string | null,
  ) => Promise<ScheduledTaskSummary>;
  search_chat_sessions: (query: string) => Promise<ChatSearchMatch[]>;
  get_chat_session: (
    projectPath: string | null,
    sessionId: string,
    effort: ChatEffort,
    permissionMode: ChatPermissionMode,
  ) => Promise<ChatSessionHistory>;
  get_active_chat: (sessionId: string, includeCompleted?: boolean) => Promise<ActiveChat | null>;
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
  model: string;
  model_site?: string;
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
  model?: ModelSelection | null;
  effort?: ChatEffort;
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
  running: boolean;
  covered_event_ids?: string[];
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
  // The Python adapter owns SDK -> UI normalization. Raw envelopes are
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
    decoded.session_id = envelope.session_id;
  }
  return isChatRenderEvent(decoded) ? decoded : null;
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

export async function minimizeWindow(): Promise<void> {
  const api = applicationApi;
  await api.minimize_window();
}

export async function toggleMaximizeWindow(): Promise<boolean> {
  const api = applicationApi;
  return (await api.toggle_maximize_window()).maximized;
}

export async function closeWindow(): Promise<void> {
  const api = applicationApi;
  await api.close_window();
}

export async function resizeWindow(width: number, height: number, edge: string): Promise<void> {
  const api = applicationApi;
  await api.resize_window(width, height, edge);
}

export async function selectProjectFolder(): Promise<ProjectFolder | null> {
  const api = applicationApi;
  return (await api.select_project_folder()) ?? null;
}

export async function getHomeFolder(): Promise<ProjectFolder | null> {
  const api = applicationApi;
  return (await api.get_home_folder()) ?? null;
}

export async function searchProjectFiles(
  projectPath: string,
  query: string,
  limit = 30,
): Promise<ProjectFileMatch[]> {
  const api = applicationApi;
  return (await api.search_project_files(projectPath, query, limit)) ?? [];
}

export async function saveAttachment(
  filename: string,
  data: string,
): Promise<{ path: string; name: string }> {
  const api = applicationApi;
  return api.save_attachment(filename, data);
}

export async function getCommands(
  sessionId: string,
  projectPath: string | null,
  effort: ChatEffort,
  permissionMode: ChatPermissionMode,
): Promise<ClaudeCommand[]> {
  const api = applicationApi;
  return (
    (await api.get_commands(sessionId, projectPath, effort, permissionMode)) ?? []
  );
}

export async function getAllowedCommandNames(): Promise<string[]> {
  const api = applicationApi;
  return (await api.get_allowed_command_names()) ?? [];
}

export async function getSkills(
  sessionId: string,
  projectPath: string | null,
  effort: ChatEffort,
  permissionMode: ChatPermissionMode,
): Promise<ClaudeCommand[]> {
  const api = applicationApi;
  return (
    (await api.get_skills(sessionId, projectPath, effort, permissionMode)) ?? []
  );
}

const applicationApi: ApplicationApi = {
  minimize_window: () => request("POST", "/api/window/minimize"),
  toggle_maximize_window: () => request("POST", "/api/window/maximize"),
  close_window: () => request("POST", "/api/window/close"),
  resize_window: (width, height, edge) => request("POST", "/api/window/resize", { body: { width, height, edge } }),
  select_project_folder: () => request("POST", "/api/window/project-folder"),
  get_home_folder: () => request("GET", "/api/window/home-folder"),
  search_project_files: (project_path, query, limit = 30) => request("GET", "/api/files/search", { query: { project_path, query, limit } }),
  save_attachment: (filename, data) => request("POST", "/api/files/attachments", { body: { filename, data } }),
  get_commands: (session_id, project_path, effort, permission_mode) => request("POST", "/api/commands/list", { body: { session_id, project_path, effort, permission_mode } }),
  get_allowed_command_names: () => request("GET", "/api/commands/allowed"),
  get_skills: (session_id, project_path, effort, permission_mode) => request("POST", "/api/commands/skills", { body: { session_id, project_path, effort, permission_mode } }),
  get_model_groups: () => request("GET", "/api/models/groups"),
  get_model_sites: () => request("GET", "/api/models/sites"),
  fetch_model_names: (api_url, api_key) => request("POST", "/api/models/remote-names", { body: { api_url, api_key } }),
  save_model_site: (original_name, name, api_url, api_key, models, api_protocol = "anthropic") => request("PUT", "/api/models/sites", { body: { original_name, name, api_url, api_key, models, api_protocol } }),
  delete_model_site: (name) => request("DELETE", "/api/models/sites", { query: { name } }),
  get_current_model: () => request("GET", "/api/models/current"),
  set_current_model: (site, model) => request("PUT", "/api/models/current", { body: { site, model } }),
  send_chat_message: (prompt, project_path, session_id, effort, permission_mode, model_site = null, model = null) => request("POST", "/api/chat/messages", { body: { prompt, project_path, session_id, effort, permission_mode, model_site, model }, timeoutMs: 24 * 60 * 60 * 1000 }),
  set_chat_permission_mode: (session_id, permission_mode, project_path, effort) => request("PUT", "/api/chat/permission-mode", { body: { session_id, permission_mode, project_path, effort } }),
  list_chat_sessions: () => request("GET", "/api/chat/sessions"),
  list_scheduled_tasks: (project_path) => request("GET", "/api/chat/scheduled-tasks", { query: { project_path } }),
  list_all_scheduled_tasks: () => request("GET", "/api/chat/all-scheduled-tasks"),
  delete_scheduled_task: (task_id, project_path) => request("DELETE", `/api/chat/scheduled-tasks/${encodeURIComponent(task_id)}`, { query: { project_path } }),
  search_chat_sessions: (query) => request("GET", "/api/chat/search", { query: { query } }),
  get_chat_session: (project_path, session_id, effort, permission_mode) => request("POST", "/api/chat/history", { body: { project_path, session_id, effort, permission_mode } }),
  get_active_chat: (session_id, include_completed = false) => request("GET", `/api/chat/sessions/${encodeURIComponent(session_id)}/active`, { query: { include_completed } }),
  get_context_usage: (session_id) => request("GET", `/api/chat/sessions/${encodeURIComponent(session_id)}/context`),
  stop_chat_message: (session_id) => request("POST", "/api/chat/stop", { body: { session_id } }),
  close_chat_client: (session_id) => request("POST", "/api/chat/close", { body: { session_id } }),
  respond_chat_permission: (permission_id, allowed, answers, feedback, execution_mode) => request("POST", "/api/chat/permissions", { body: { permission_id, allowed, answers, feedback, execution_mode } }),
  get_current_theme: () => request("GET", "/api/theme"),
  set_current_theme: (name) => request("PUT", "/api/theme", { body: { name } }),
  list_tutorials: () => request("GET", "/api/tutorials"),
  get_tutorial: (tutorial_id) => request("GET", `/api/tutorials/${encodeURIComponent(tutorial_id)}`),
  report_frontend_error: (kind, message, stack) => request("POST", "/api/logs/frontend", { body: { kind, message, stack }, silent: true }),
};


export async function getModelGroups(): Promise<ModelGroup[]> {
  const api = applicationApi;
  return (await api.get_model_groups()) ?? [];
}

export async function getModelSites(): Promise<ModelSite[]> {
  const api = applicationApi;
  return (await api.get_model_sites()) ?? [];
}

export async function fetchModelNames(
  apiUrl: string,
  apiKey: string,
): Promise<string[]> {
  const api = applicationApi;
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
  const api = applicationApi;
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
  const api = applicationApi;
  await api.delete_model_site(name);
}

export async function getCurrentModel(): Promise<ModelSelection | null> {
  const api = applicationApi;
  return (await api.get_current_model()) ?? null;
}

export async function setCurrentModel(site: string, model: string): Promise<void> {
  const api = applicationApi;
  await api.set_current_model(site, model);
}

export async function sendChatMessage(
  prompt: string,
  projectPath: string | null,
  sessionId: string,
  effort: ChatEffort,
  permissionMode: ChatPermissionMode,
  model: ModelSelection | null = null,
): Promise<ChatReply> {
  const api = applicationApi;

  return api.send_chat_message(
    prompt,
    projectPath,
    sessionId,
    effort,
    permissionMode,
    model?.site ?? null,
    model?.model ?? null,
  );
}

export async function setChatPermissionMode(
  sessionId: string,
  permissionMode: ChatPermissionMode,
  projectPath: string | null,
  effort: ChatEffort,
): Promise<boolean> {
  const api = applicationApi;
  return api.set_chat_permission_mode(
    sessionId,
    permissionMode,
    projectPath,
    effort,
  );
}

export async function listChatSessions(): Promise<ChatSessionSummary[]> {
  const api = applicationApi;
  return (await api.list_chat_sessions()) ?? [];
}

export async function listScheduledTasks(
  projectPath: string | null,
): Promise<ScheduledTaskSummary[]> {
  const api = applicationApi;
  return (await api.list_scheduled_tasks(projectPath)) ?? [];
}

export async function listAllScheduledTasks(): Promise<ScheduledTaskSummary[]> {
  const api = applicationApi;
  return (await api.list_all_scheduled_tasks()) ?? [];
}

export async function deleteScheduledTask(
  taskId: string,
  projectPath: string | null,
): Promise<ScheduledTaskSummary> {
  const api = applicationApi;
  return api.delete_scheduled_task(taskId, projectPath);
}

export async function searchChatSessions(query: string): Promise<ChatSearchMatch[]> {
  const api = applicationApi;
  return (await api.search_chat_sessions(query)) ?? [];
}

export async function getChatSession(
  sessionId: string,
  projectPath: string | null,
  effort: ChatEffort,
  permissionMode: ChatPermissionMode,
): Promise<ChatSessionHistory> {
  const api = applicationApi;
  const result = await api.get_chat_session(projectPath, sessionId, effort, permissionMode);
  return {
    ...result,
    events: decodeEventList(result.render_events ?? result.events),
  };
}

export async function getActiveChat(
  sessionId: string, includeCompleted = false,
): Promise<ActiveChat | null> {
  const api = applicationApi;
  const result = await api.get_active_chat(sessionId, includeCompleted);
  return result
    ? { ...result, events: decodeEventList(result.render_events ?? result.events) }
    : null;
}

export async function getContextUsage(sessionId: string): Promise<ContextUsage | null> {
  const api = applicationApi;
  return (await api.get_context_usage(sessionId)) ?? null;
}

export function subscribeChatEvents(
  sessionId: string,
  onEvent: (event: ChatRenderEvent) => void,
  onRecovered?: (snapshot: ActiveChat | null) => void,
): () => void {
  let disposed = false;
  let recovering = false;
  let buffered: ChatRenderEvent[] = [];
  let recoveryGeneration = 0;
  let coveredIds = new Set<string>();
  const handleStreamEvent: EventListener = (event) => {
    const detail = (event as CustomEvent<unknown>).detail;
    const renderEvent = decodeChatRenderEvent(detail);
    if (renderEvent?.session_id === sessionId) {
      if (recovering) buffered.push(renderEvent);
      else onEvent(renderEvent);
    }
  };
  const recover = (event: Event) => {
    if (!(event as CustomEvent<{ reconnected: boolean }>).detail?.reconnected) return;
    const generation = ++recoveryGeneration;
    recovering = true;
    void getActiveChat(sessionId, true).then((snapshot) => {
      if (!disposed && generation === recoveryGeneration) {
        coveredIds = new Set(snapshot?.covered_event_ids ?? snapshot?.events.map((item) => item.id) ?? []);
        snapshot?.events.forEach(onEvent);
        onRecovered?.(snapshot);
      }
    }).catch(() => undefined).finally(() => {
      if (generation !== recoveryGeneration) return;
      recovering = false;
      const queued = buffered;
      buffered = [];
      if (!disposed) queued.filter((item) => !coveredIds.has(item.id)).forEach(onEvent);
    });
  };
  window.addEventListener(CHAT_STREAM_EVENT, handleStreamEvent);
  window.addEventListener(TRANSPORT_READY_EVENT, recover);
  return () => {
    disposed = true;
    window.removeEventListener(CHAT_STREAM_EVENT, handleStreamEvent);
    window.removeEventListener(TRANSPORT_READY_EVENT, recover);
  };
}

export async function stopChatMessage(sessionId: string | null): Promise<boolean> {
  const api = applicationApi;
  return api.stop_chat_message(sessionId);
}

export async function closeChatClient(sessionId: string | null): Promise<boolean> {
  const api = applicationApi;
  return (await api.close_chat_client(sessionId)) ?? false;
}

export async function respondChatPermission(
  permissionId: string,
  allowed: boolean,
  answers?: ChatPermissionAnswers,
  feedback?: string,
  executionMode?: ChatPlanExecutionMode,
): Promise<boolean> {
  const api = applicationApi;
  return api.respond_chat_permission(
    permissionId,
    allowed,
    answers ?? null,
    feedback?.trim() || null,
    executionMode ?? null,
  );
}

export async function getCurrentTheme(): Promise<string> {
  const api = applicationApi;
  return (await api.get_current_theme()) ?? "default";
}

export async function setCurrentTheme(name: string): Promise<void> {
  const api = applicationApi;
  await api.set_current_theme(name);
}

export async function listTutorials(): Promise<TutorialSummary[]> {
  const api = applicationApi;
  return (await api.list_tutorials()) ?? [];
}

export async function getTutorial(tutorialId: string): Promise<TutorialDocument | null> {
  const api = applicationApi;
  return (await api.get_tutorial(tutorialId)) ?? null;
}

export async function reportFrontendError(
  kind: string,
  message: string,
  stack: string | null,
): Promise<void> {
  // 上报失败不显示通知，避免日志上报再次触发日志。
  const api = applicationApi;
  await api.report_frontend_error(kind, message, stack);
}
