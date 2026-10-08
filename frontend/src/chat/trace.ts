import type { ChatRenderEvent } from "../api/client";

export type TraceStatus = "error" | "running" | "success";

type ContentTraceItem = {
  content: string;
  finishedAt?: number;
  key: string;
  kind: "output" | "thinking";
  modelTurnId: string | null;
  startedAt: number;
  status: TraceStatus;
};

type ToolCall = {
  key: string;
  name: string;
  output?: string;
  plan?: string;
  status: TraceStatus;
  summary: string;
  taskIds?: string[];
  taskFailed?: boolean;
  trace: AgentTraceItem[];
};

type ToolTraceItem = {
  calls: ToolCall[];
  finishedAt?: number;
  key: string;
  kind: "tools";
  startedAt: number;
  status: TraceStatus;
};

export type AgentTraceItem = ContentTraceItem | ToolTraceItem;

function completeStatus(
  item: AgentTraceItem,
  status: "error" | "success",
  finishedAt: number,
): AgentTraceItem {
  if (item.kind === "tools") {
    const calls = item.calls.map((call) => {
      const callStatus = call.taskFailed ? "error" : call.status === "running" ? status : call.status;
      return {
        ...call,
        status: callStatus,
        taskIds: undefined,
        trace: finishAgentTrace(call.trace, callStatus, finishedAt),
      };
    });
    return {
      ...item,
      calls,
      finishedAt: item.finishedAt ?? finishedAt,
      status: calls.some((call) => call.status === "error") ? "error" : "success",
    };
  }
  return item.status === "running"
    ? { ...item, finishedAt, status }
    : item;
}

function applyRenderEventAtLevel(
  items: AgentTraceItem[],
  event: ChatRenderEvent,
): AgentTraceItem[] {
  const parsedTime = Date.parse(event.created_at);
  const now = Number.isFinite(parsedTime) ? parsedTime : Date.now();
  const data = event.data;
  const traceId = typeof data.trace_id === "string" ? data.trace_id : event.id;
  const isThinking = event.event.startsWith("assistant.thinking")
    || event.event === "subagent.thinking.completed";
  const contentKey = `${traceId}:${isThinking ? "thinking" : "reply"}`;

  if (event.event === "assistant.thinking.started" || event.event === "assistant.reply.started") {
    const kind = isThinking ? "thinking" : "output";
    const existingIndex = items.findIndex((item) => item.key === contentKey);
    if (existingIndex === -1) {
      return [
        ...items,
        {
          content: "",
          key: contentKey,
          kind,
          modelTurnId: event.model_turn_id,
          startedAt: now,
          status: "running",
        },
      ];
    }
    return items;
  }

  if (event.event === "assistant.thinking.delta" || event.event === "assistant.reply.delta") {
    const kind = isThinking ? "thinking" : "output";
    const text = typeof data.text === "string" ? data.text : "";
    const existingIndex = items.findIndex((item) => item.key === contentKey);
    if (existingIndex === -1) {
      return [
        ...items,
        {
          content: text,
          key: contentKey,
          kind,
          modelTurnId: event.model_turn_id,
          startedAt: now,
          status: "running",
        },
      ];
    }
    return items.map((item, index) => (
      index === existingIndex && item.kind !== "tools"
        ? item.status === "running" ? { ...item, content: `${item.content}${text}` } : item
        : item
    ));
  }

  if (event.event === "assistant.thinking.stopped" || event.event === "assistant.reply.stopped") {
    return items.map((item) => (
      item.key === contentKey ? completeStatus(item, "success", now) : item
    ));
  }

  if (event.event.endsWith(".reply.completed") || event.event.endsWith(".thinking.completed")) {
    const content = typeof data.text === "string" ? data.text : "";
    const kind = isThinking ? "thinking" : "output";
    const existingIndex = items.findIndex((item) => item.key === contentKey);
    if (existingIndex !== -1) return items.map((item, index) => (
      index === existingIndex && item.kind !== "tools"
        ? { ...item, content, finishedAt: item.finishedAt ?? now, status: "success" }
        : item
    ));
    if (!content) return items;
    return [
      ...items,
      {
        content,
        finishedAt: now,
        key: contentKey,
        kind,
        modelTurnId: event.model_turn_id,
        startedAt: now,
        status: "success",
      },
    ];
  }

  const requestedEvents = new Set([
    "tool.requested",
    "subagent.tool.requested",
    "subagent.started",
    "ask_user.requested",
    "plan.approval.requested",
    "server_tool.requested",
  ]);
  if (requestedEvents.has(event.event)) {
    const toolId = typeof data.tool_id === "string" ? data.tool_id : event.id;
    const name = typeof data.name === "string"
      ? data.name
      : typeof data.tool_name === "string"
        ? data.tool_name
        : event.event;
    const summary = typeof data.summary === "string" ? data.summary : "";
    const plan = typeof data.plan === "string" && data.plan.trim()
      ? data.plan.trim()
      : undefined;
    const toolCall: ToolCall = {
      key: toolId,
      name,
      plan,
      status: "running",
      summary,
      trace: [],
    };
    const modelTurnId = event.model_turn_id ?? event.id;
    const groupKey = `tools:${event.turn_id}:${modelTurnId}:${event.parent_tool_use_id ?? "main"}`;
    const groupIndex = items.findIndex((item) => item.key === groupKey);
    if (groupIndex === -1) {
      return [
        ...items,
        {
          calls: [toolCall],
          key: groupKey,
          kind: "tools",
          startedAt: now,
          status: "running",
        },
      ];
    }
    return items.map((item, itemIndex) => {
      if (itemIndex !== groupIndex || item.kind !== "tools") {
        return item;
      }
      if (item.calls.some((call) => call.key === toolId)) {
        return { ...item, calls: item.calls.map((call) => call.key === toolId
          ? { ...call, name, summary, plan: plan ?? call.plan } : call) };
      }
      return {
        ...item,
        calls: [...item.calls, toolCall],
        finishedAt: undefined,
        status: "running",
      };
    });
  }

  if (
    event.event === "task.started"
    || event.event === "task.progress"
    || event.event === "task.completed"
    || event.event === "task.updated"
  ) {
    const taskId = typeof data.task_id === "string" ? data.task_id : undefined;
    if (!taskId) {
      return items;
    }
    const toolId = typeof data.tool_use_id === "string" ? data.tool_use_id : undefined;
    const patchData = typeof data.patch === "object" && data.patch !== null
      ? data.patch as Record<string, unknown>
      : undefined;
    const rawStatus = typeof data.status === "string"
      ? data.status
      : typeof patchData?.status === "string" ? patchData.status : undefined;
    const terminal: "error" | "success" | undefined = event.event === "task.completed"
      ? rawStatus !== "failed" && rawStatus !== "stopped"
        ? "success"
        : "error"
      : rawStatus === "completed" || rawStatus === "failed"
        || rawStatus === "stopped" || rawStatus === "killed"
        ? rawStatus === "completed" ? "success" : "error"
        : undefined;
    const running = terminal === undefined;
    let changed = false;
    const nextItems = items.map((item) => {
      if (item.kind !== "tools") {
        return item;
      }
      const calls = item.calls.map((call) => {
        const matches = (toolId !== undefined && call.key === toolId)
          || call.taskIds?.includes(taskId) === true;
        if (!matches) {
          return call;
        }
        changed = true;
        const taskIds = running
          ? [...new Set([...(call.taskIds ?? []), taskId])]
          : (call.taskIds ?? []).filter((id) => id !== taskId);
        const taskFailed = call.taskFailed || terminal === "error";
        const status: TraceStatus = taskIds.length ? "running" : taskFailed ? "error" : terminal ?? "running";
        const completedStatus: "error" | "success" = taskFailed ? "error" : "success";
        return {
          ...call,
          status,
          taskIds: taskIds.length ? taskIds : undefined,
          taskFailed,
          trace: status === "running" ? call.trace : finishAgentTrace(call.trace, completedStatus, now),
        };
      });
      if (calls === item.calls || !calls.some((call, index) => call !== item.calls[index])) {
        return item;
      }
      const groupStatus: TraceStatus = calls.some((call) => call.status === "running")
        ? "running" : calls.some((call) => call.status === "error") ? "error" : "success";
      return {
        ...item,
        calls,
        finishedAt: calls.some((call) => call.status === "running") ? undefined : now,
        status: groupStatus,
      };
    });
    return changed ? nextItems : items;
  }

  const completedEvents = new Set([
    "tool.completed",
    "subagent.tool.completed",
    "subagent.completed",
    "ask_user.completed",
    "plan.approval.completed",
    "server_tool.completed",
  ]);
  if (completedEvents.has(event.event)) {
    const toolId = typeof data.tool_id === "string" ? data.tool_id : "";
    const status: "error" | "success" = data.is_error === true ? "error" : "success";
    return items.map((item) => {
      if (item.kind !== "tools") {
        return item;
      }
      const callIndex = item.calls.findIndex((call) => call.key === toolId);
      if (callIndex === -1) {
        return item;
      }
      const calls = item.calls.map((call) => {
        if (call.key !== toolId) {
          return call;
        }

        // For Agent/Task, ``subagent.completed`` is the tool-result/launch
        // acknowledgement.  Background tasks can continue after that result,
        // and the SDK does not always include tool_use_id on their lifecycle
        // messages, so this event cannot safely be treated as final completion.
        // Keep the call running until a terminal task.* event arrives, or until
        // turn.completed finishes any still-running trace as a final fallback.
        const deferredAgentCompletion = (
          event.event === "subagent.completed"
          && isAgentTool(call.name)
          && data.is_error !== true
        );
        const nextStatus: TraceStatus = deferredAgentCompletion || call.taskIds?.length
          ? "running" : status;
        return {
          ...call,
          status: nextStatus,
          output: formatToolOutput(data.output) || call.output,
          trace: nextStatus === "running"
            ? call.trace
            : finishAgentTrace(call.trace, status, now),
        };
      });
      if (calls.every((call) => call.status !== "running")) {
        return {
          ...item,
          calls,
          finishedAt: now,
          status: calls.some((call) => call.status === "error") ? "error" : "success",
        };
      }
      return { ...item, calls };
    });
  }

  return items;
}

function formatToolOutput(value: unknown): string {
  if (typeof value === "string") return value;
  if (value == null) return "";
  if (Array.isArray(value)) return value.map((item) => (
    item && typeof item === "object" && "text" in item
      ? String(item.text) : JSON.stringify(item, null, 2)
  )).join("\n\n");
  return `\`\`\`json\n${JSON.stringify(value, null, 2)}\n\`\`\``;
}

export function hasTraceTool(items: AgentTraceItem[], toolId: string): boolean {
  return items.some((item) => item.kind === "tools"
    && item.calls.some((call) => call.key === toolId || hasTraceTool(call.trace, toolId)));
}

function applyNestedRenderEvent(
  items: AgentTraceItem[],
  parentToolId: string,
  event: ChatRenderEvent,
): { applied: boolean; items: AgentTraceItem[] } {
  let applied = false;
  const nextItems = items.map((item) => {
    if (item.kind !== "tools") {
      return item;
    }
    const calls = item.calls.map((call) => {
      if (call.key === parentToolId) {
        applied = true;
        return {
          ...call,
          trace: applyRenderEventAtLevel(call.trace, event),
        };
      }
      if (!call.trace.length) {
        return call;
      }
      const nested = applyNestedRenderEvent(call.trace, parentToolId, event);
      if (!nested.applied) {
        return call;
      }
      applied = true;
      return { ...call, trace: nested.items };
    });
    return applied ? { ...item, calls } : item;
  });
  return { applied, items: applied ? nextItems : items };
}

export function applyRenderEvent(
  items: AgentTraceItem[],
  event: ChatRenderEvent,
): AgentTraceItem[] {
  if (event.parent_tool_use_id !== null) {
    return applyNestedRenderEvent(
      items,
      event.parent_tool_use_id,
      event,
    ).items;
  }
  return applyRenderEventAtLevel(items, event);
}

export function stripExitPlanContent(
  content: string,
  items: AgentTraceItem[],
): string {
  let result = content;
  for (const item of items) {
    if (item.kind !== "tools") {
      continue;
    }
    for (const call of item.calls) {
      if (call.name !== "ExitPlanMode" || !call.plan) {
        continue;
      }
      const planIndex = result.indexOf(call.plan);
      if (planIndex !== -1) {
        result = `${result.slice(0, planIndex)}${result.slice(planIndex + call.plan.length)}`;
      }
    }
  }
  return result.trim();
}

export function finishAgentTrace(
  items: AgentTraceItem[],
  status: "error" | "success",
  finishedAt = Date.now(),
): AgentTraceItem[] {
  return items.map((item) => completeStatus(item, status, finishedAt));
}

export function isAgentTool(name: string): boolean {
  return name === "Agent" || name === "Task";
}

