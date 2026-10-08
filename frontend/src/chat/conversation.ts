import { isPermissionRequestEvent, type ChatPermissionRequestEvent, type ChatRenderEvent, type ChatUsage, type TurnFileChange } from "../api/client";
import { applyRenderEvent, finishAgentTrace, hasTraceTool, stripExitPlanContent, type AgentTraceItem } from "./trace";

export type ConversationMessage = {
  content: string;
  checkpointId?: string;
  filesRestoredAt?: string;
  fileChanges?: TurnFileChange[];
  expandedTraceItemKeys?: string[];
  finalOutputKey?: string;
  finalOutputKeys?: string[];
  key: string;
  loading?: boolean;
  role: "ai" | "user";
  startedAt?: number;
  status?: "abort" | "error" | "success";
  submissionKey?: string;
  trace?: AgentTraceItem[];
  traceExpanded?: boolean;
  usage?: ChatUsage;
  workingSeconds?: number;
  pendingTraceEvents?: ChatRenderEvent[];
};

export function eventTime(event: ChatRenderEvent): number {
  const time = Date.parse(event.created_at);
  return Number.isFinite(time) ? time : Date.now();
}

export const turnAssistantKey = (id: string): string => `turn-${id}-assistant`;
const turnUserKey = (id: string): string => `turn-${id}-user`;

function lastMessageIndex(messages: ConversationMessage[], matches: (item: ConversationMessage) => boolean): number {
  for (let index = messages.length - 1; index >= 0; index -= 1) if (matches(messages[index])) return index;
  return -1;
}

export function contextCompactionText(event: ChatRenderEvent): string | null {
  if (event.event === "context.compaction.started") return "正在压缩上下文…";
  if (event.event !== "context.compacted") return null;
  const trigger = event.data.trigger === "manual" ? "手动" : "自动";
  const tokens = event.data.pre_tokens;
  return `上下文已${trigger}压缩${typeof tokens === "number"
    ? `（压缩前约 ${tokens.toLocaleString("en-US")} Token）` : ""}`;
}

const toolEvents = new Set([
  "tool.requested", "tool.completed", "subagent.started", "subagent.completed",
  "subagent.tool.requested", "subagent.tool.completed", "ask_user.requested", "ask_user.completed",
  "plan.approval.requested", "plan.approval.completed", "server_tool.requested", "server_tool.completed",
  "task.started", "task.progress", "task.updated", "task.completed",
]);

export function isConversationEvent(event: ChatRenderEvent): boolean {
  return event.event === "turn.started" || event.event === "user.message"
    || event.event === "files.checkpoint" || event.event === "files.restored" || event.event === "files.changed"
    || event.event === "turn.completed" || event.event === "turn.failed"
    || event.event === "turn.proxy.completed" || event.event === "user.proxy.message"
    || /^(assistant|subagent)\.(reply|thinking)\.(started|delta|stopped|completed)$/.test(event.event)
    || toolEvents.has(event.event);
}

function missingTool(trace: AgentTraceItem[], event: ChatRenderEvent): boolean {
  const target = event.parent_tool_use_id
    ?? (event.event.startsWith("task.") ? event.data.tool_use_id : null)
    ?? (event.event.endsWith(".completed") && toolEvents.has(event.event) ? event.data.tool_id : null);
  return typeof target === "string" && !hasTraceTool(trace, target);
}

function updateTrace(message: ConversationMessage, event: ChatRenderEvent): ConversationMessage {
  let trace = message.trace ?? [];
  const pending = [...(message.pendingTraceEvents ?? [])];
  if (missingTool(trace, event)) pending.push(event);
  else trace = applyRenderEvent(trace, event);
  // SDK children and background notifications can arrive before their parent
  // tool packet. Drain newly attachable events without inventing parent tools.
  let changed = true;
  while (changed) {
    changed = false;
    for (let index = 0; index < pending.length;) {
      if (missingTool(trace, pending[index])) { index += 1; continue; }
      trace = applyRenderEvent(trace, pending.splice(index, 1)[0]);
      changed = true;
    }
  }
  return { ...message, trace, pendingTraceEvents: pending.length ? pending : undefined };
}

function applyAssistantEvent(message: ConversationMessage, event: ChatRenderEvent): ConversationMessage {
  let next = updateTrace(message, event);
  const terminal = event.event === "turn.completed" || event.event === "turn.failed";
  const topLevel = event.parent_tool_use_id === null;
  // Late frames may fill in tools/child traces, but final content and status
  // belong to the terminal event, including HTTP-before-WebSocket recovery.
  if (message.status && !terminal) return { ...next, loading: false,
    trace: finishAgentTrace(next.trace ?? [], message.status === "error" ? "error" : "success", eventTime(event)) };
  if (!topLevel) return next;
  if (event.event === "turn.proxy.completed" || event.event === "user.proxy.message") {
    return { ...next, content: "", finalOutputKey: undefined, finalOutputKeys: undefined };
  }
  if (event.event.startsWith("assistant.reply.")) {
    const outputs = (next.trace ?? []).filter((item) => item.kind === "output"
      && item.modelTurnId === event.model_turn_id);
    const keys = outputs.map((item) => item.key);
    next = { ...next, content: stripExitPlanContent(outputs.map((item) => (
      item.kind === "output" ? item.content : ""
    )).filter(Boolean).join("\n\n"), next.trace ?? []),
    finalOutputKey: keys.at(-1), finalOutputKeys: keys };
  }
  if (terminal) {
    const usage = event.data.usage as ChatUsage | undefined;
    const stopped = usage?.stop_reason === "interrupted" || usage?.terminal_reason?.startsWith("aborted");
    const failed = event.event === "turn.failed" || event.data.is_error === true;
    const content = event.event === "turn.failed" ? event.data.message : event.data.content;
    const endedAt = eventTime(event);
    return { ...next,
      content: stripExitPlanContent(typeof content === "string" && content ? content : next.content, next.trace ?? []),
      loading: false, status: stopped ? "abort" : failed ? "error" : "success", usage,
      trace: finishAgentTrace(next.trace ?? [], failed ? "error" : "success", endedAt),
      workingSeconds: next.startedAt === undefined ? undefined
        : Math.max(1, Math.round((endedAt - next.startedAt) / 1000)),
    };
  }
  return { ...next, loading: true };
}

/** Both live delivery and history replay call this same reducer. */
export function reduceConversationEvent(messages: ConversationMessage[], event: ChatRenderEvent): ConversationMessage[] {
  if (event.event === "files.changed") {
    if (event.parent_tool_use_id !== null || !Array.isArray(event.data.files)) return messages;
    const fileChanges = event.data.files as TurnFileChange[];
    return messages.map((item) => item.key === turnAssistantKey(event.turn_id) ? { ...item, fileChanges } : item);
  }
  if (event.event === "files.checkpoint" || event.event === "files.restored") {
    const checkpointId = event.data.checkpoint_id;
    if (event.parent_tool_use_id !== null || typeof checkpointId !== "string") return messages;
    return messages.map((item) => (item.key === turnUserKey(event.turn_id)
      || item.key === turnAssistantKey(event.turn_id) || item.checkpointId === checkpointId)
      ? { ...item, checkpointId, filesRestoredAt: event.event === "files.restored" ? event.created_at : item.filesRestoredAt }
      : item);
  }
  if (!isConversationEvent(event)) return messages;
  const assistantKey = turnAssistantKey(event.turn_id);
  if (event.event === "user.message") {
    const userKey = turnUserKey(event.turn_id);
    if (messages.some((item) => item.key === userKey)) return messages;
    const content = typeof event.data.content === "string" ? event.data.content : "";
    const optimistic = lastMessageIndex(messages, (item) => item.role === "user" && item.key.startsWith("user-"));
    if (optimistic !== -1) return messages.map((item, index) => index === optimistic
      ? { ...item, key: userKey, content } : item);
    const assistantIndex = messages.findIndex((item) => item.key === assistantKey);
    const next = [...messages];
    next.splice(assistantIndex === -1 ? next.length : assistantIndex, 0,
      { key: userKey, content, role: "user", status: "success" });
    return next;
  }
  let index = messages.findIndex((item) => item.key === assistantKey);
  if (index === -1 && event.event === "turn.started") {
    index = lastMessageIndex(messages, (item) => item.role === "ai" && item.loading === true && item.key.startsWith("assistant-"));
  }
  const next = [...messages];
  if (index === -1) {
    index = next.length;
    next.push({ content: "", key: assistantKey, role: "ai", loading: true,
      startedAt: eventTime(event), trace: [], expandedTraceItemKeys: [], traceExpanded: false });
  }
  if (event.event === "turn.started") {
    if (next[index].status) return messages;
    next[index] = { ...next[index], key: assistantKey, startedAt: eventTime(event) };
  } else next[index] = applyAssistantEvent(next[index], event);
  return next;
}

export function conversationFromEvents(events: ChatRenderEvent[]): ConversationMessage[] {
  let messages: ConversationMessage[] = [];
  const seen = new Set<string>();
  for (const event of events) {
    if (seen.has(event.id)) continue;
    seen.add(event.id);
    messages = reduceConversationEvent(messages, event);
  }
  return messages;
}

export function pendingPermissionsFromEvents(events: ChatRenderEvent[]): ChatPermissionRequestEvent[] {
  const pending = new Map<string, ChatPermissionRequestEvent>();
  const closed = new Set<string>();
  for (const event of events) {
    if (isPermissionRequestEvent(event) && !closed.has(event.turn_id)) pending.set(event.data.request_id, event);
    if (event.event === "permission.resolved") pending.delete(String(event.data.request_id));
    if (event.event === "turn.completed" || event.event === "turn.failed") {
      closed.add(event.turn_id);
      for (const [id, request] of pending) if (request.turn_id === event.turn_id) pending.delete(id);
    }
  }
  return [...pending.values()];
}
