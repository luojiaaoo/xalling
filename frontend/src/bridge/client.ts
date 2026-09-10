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
  get_model_groups: () => Promise<ModelGroup[]>;
  get_model_sites: () => Promise<ModelSite[]>;
  save_model_site: (
    originalName: string | null,
    name: string,
    apiUrl: string,
    apiKey: string,
    models: ModelConfig[],
  ) => Promise<void>;
  delete_model_site: (name: string) => Promise<void>;
  get_current_model: () => Promise<ModelSelection | null>;
  set_current_model: (site: string, model: string) => Promise<void>;
  send_chat_message: (
    prompt: string,
    projectPath: string | null,
    sessionId: string | null,
    effort: ChatEffort,
    permissionMode: ChatPermissionMode,
  ) => Promise<ChatReply>;
  list_chat_sessions: () => Promise<ChatSessionSummary[]>;
  get_chat_session: (sessionId: string) => Promise<ChatSessionHistory>;
  stop_chat_message: () => Promise<boolean>;
  respond_chat_permission: (
    permissionId: string,
    allowed: boolean,
    answers: ChatPermissionAnswers | null,
  ) => Promise<boolean>;
  get_current_theme: () => Promise<string>;
  set_current_theme: (name: string) => Promise<void>;
  report_frontend_error: (
    kind: string,
    message: string,
    stack: string | null,
  ) => Promise<void>;
};

export type ModelGroup = {
  name: string;
  models: ModelConfig[];
};

export type ModelConfig = {
  name: string;
  image_vision: boolean;
};

export type ModelSite = {
  name: string;
  api_url: string;
  api_key: string;
  models: ModelConfig[];
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

export type ChatEffort = "low" | "medium" | "high" | "max";

export type ChatPermissionMode =
  | "default"
  | "acceptEdits"
  | "plan"
  | "auto"
  | "bypassPermissions";

export type ChatReply = {
  content: string;
  final_output_block_id: string | null;
  session_id: string;
  stopped?: boolean;
};

export type ChatSessionSummary = {
  created_at: number | null;
  last_modified: number;
  project_name: string;
  project_path: string;
  session_id: string;
  title: string;
};

type ChatHistoryUserMessage = {
  content: string;
  key: string;
  role: "user";
};

type ChatHistoryAssistantMessage = {
  content: string;
  final_output_block_id: string | null;
  key: string;
  role: "assistant";
  trace_events: ChatStreamEvent[];
};

export type ChatHistoryMessage =
  | ChatHistoryUserMessage
  | ChatHistoryAssistantMessage;

export type ChatSessionHistory = ChatSessionSummary & {
  messages: ChatHistoryMessage[];
};

type ChatContentEvent = {
  block_id: string;
  type:
    | "thinking_start"
    | "thinking_complete"
    | "output_start"
    | "output_complete";
};

type ChatContentDeltaEvent = {
  block_id: string;
  text: string;
  type: "thinking_delta" | "output_delta";
};

type ChatToolStartEvent = {
  group_id: string;
  name: string;
  summary: string;
  tool_id: string;
  type: "tool_start";
};

type ChatToolCompleteEvent = {
  status: "error" | "success";
  tool_id: string;
  type: "tool_complete";
};

export type ChatPermissionRequestEvent = {
  blocked_path: string;
  description: string;
  display_name: string;
  input: Record<string, unknown>;
  permission_id: string;
  title: string;
  tool_name: string;
  type: "permission_request";
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

export type ChatAskUserQuestionRequestEvent = Omit<
  ChatPermissionRequestEvent,
  "input" | "tool_name"
> & {
  input: {
    answers?: ChatPermissionAnswers | null;
    questions: ChatUserQuestion[];
  };
  tool_name: "AskUserQuestion";
};

export type ChatStreamEvent =
  | ChatContentEvent
  | ChatContentDeltaEvent
  | ChatToolStartEvent
  | ChatToolCompleteEvent
  | ChatPermissionRequestEvent;

const CHAT_STREAM_EVENT = "xalling:chat-event";

function isChatStreamEvent(value: unknown): value is ChatStreamEvent {
  if (
    typeof value !== "object"
    || value === null
    || !("type" in value)
    || typeof value.type !== "string"
  ) {
    return false;
  }
  if (value.type === "tool_start") {
    return (
      "group_id" in value
      && typeof value.group_id === "string"
      && "tool_id" in value
      && typeof value.tool_id === "string"
      && "name" in value
      && typeof value.name === "string"
      && "summary" in value
      && typeof value.summary === "string"
    );
  }
  if (value.type === "permission_request") {
    return (
      "permission_id" in value
      && typeof value.permission_id === "string"
      && "tool_name" in value
      && typeof value.tool_name === "string"
      && "title" in value
      && typeof value.title === "string"
      && "display_name" in value
      && typeof value.display_name === "string"
      && "description" in value
      && typeof value.description === "string"
      && "blocked_path" in value
      && typeof value.blocked_path === "string"
      && "input" in value
      && typeof value.input === "object"
      && value.input !== null
      && !Array.isArray(value.input)
    );
  }
  if (value.type === "tool_complete") {
    return (
      "tool_id" in value
      && typeof value.tool_id === "string"
      && "status" in value
      && (value.status === "success" || value.status === "error")
    );
  }
  if (
    value.type === "thinking_delta"
    || value.type === "output_delta"
  ) {
    return (
      "block_id" in value
      && typeof value.block_id === "string"
      && "text" in value
      && typeof value.text === "string"
    );
  }
  return (
    value.type === "thinking_start"
    || value.type === "thinking_complete"
    || value.type === "output_start"
    || value.type === "output_complete"
  ) && "block_id" in value && typeof value.block_id === "string";
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
  const questions = request.input.questions;
  return request.tool_name === "AskUserQuestion"
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

async function getBridgeApi(): Promise<PyWebviewApi | undefined> {
  if (window.pywebview?.api) {
    return window.pywebview.api;
  }

  if (window.location.protocol === "file:") {
    await new Promise<void>((resolve) => {
      window.addEventListener("pywebviewready", () => resolve(), { once: true });
    });
  }

  return window.pywebview?.api;
}

export async function getModelGroups(): Promise<ModelGroup[]> {
  const api = await getBridgeApi();
  return (await api?.get_model_groups()) ?? [];
}

export async function getModelSites(): Promise<ModelSite[]> {
  const api = await getBridgeApi();
  return (await api?.get_model_sites()) ?? [];
}

export async function saveModelSite(
  originalName: string | null,
  name: string,
  apiUrl: string,
  apiKey: string,
  models: ModelConfig[],
): Promise<void> {
  const api = await getBridgeApi();
  if (!api) {
    throw new Error("桌面应用桥接尚未准备好");
  }
  await api.save_model_site(originalName, name, apiUrl, apiKey, models);
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
  sessionId: string | null,
  effort: ChatEffort,
  permissionMode: ChatPermissionMode,
  onEvent?: (event: ChatStreamEvent) => void,
): Promise<ChatReply> {
  const api = await getBridgeApi();
  if (!api) {
    throw new Error("桌面应用桥接尚未准备好");
  }

  const handleStreamEvent: EventListener = (event) => {
    const detail = (event as CustomEvent<unknown>).detail;
    if (isChatStreamEvent(detail)) {
      onEvent?.(detail);
    }
  };
  window.addEventListener(CHAT_STREAM_EVENT, handleStreamEvent);
  try {
    return await api.send_chat_message(
      prompt,
      projectPath,
      sessionId,
      effort,
      permissionMode,
    );
  } finally {
    window.removeEventListener(CHAT_STREAM_EVENT, handleStreamEvent);
  }
}

export async function listChatSessions(): Promise<ChatSessionSummary[]> {
  const api = await getBridgeApi();
  return (await api?.list_chat_sessions()) ?? [];
}

export async function getChatSession(sessionId: string): Promise<ChatSessionHistory> {
  const api = await getBridgeApi();
  if (!api) {
    throw new Error("桌面应用桥接尚未准备好");
  }
  return api.get_chat_session(sessionId);
}

export async function stopChatMessage(): Promise<boolean> {
  const api = await getBridgeApi();
  if (!api) {
    throw new Error("桌面应用桥接尚未准备好");
  }
  return api.stop_chat_message();
}

export async function respondChatPermission(
  permissionId: string,
  allowed: boolean,
  answers?: ChatPermissionAnswers,
): Promise<boolean> {
  const api = await getBridgeApi();
  if (!api) {
    throw new Error("桌面应用桥接尚未准备好");
  }
  return api.respond_chat_permission(permissionId, allowed, answers ?? null);
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

export async function reportFrontendError(
  kind: string,
  message: string,
  stack: string | null,
): Promise<void> {
  // 静默上报：桥接不可用（如纯浏览器调试）时直接丢弃，不能再产生新错误
  const api = await getBridgeApi();
  await api?.report_frontend_error(kind, message, stack);
}
