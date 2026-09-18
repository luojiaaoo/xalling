import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  FileTextOutlined,
  LoadingOutlined,
  MessageOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import { Think, ThoughtChain } from "@ant-design/x";

import type { ChatStreamEvent } from "../bridge/client";
import { ChatMarkdown } from "./ChatMarkdown";

type TraceStatus = "error" | "running" | "success";

type ContentTraceItem = {
  content: string;
  finishedAt?: number;
  key: string;
  kind: "output" | "thinking";
  startedAt: number;
  status: TraceStatus;
};

type ToolCall = {
  key: string;
  name: string;
  plan?: string;
  status: TraceStatus;
  summary: string;
  taskIds?: string[];
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

type AgentTraceProps = {
  elapsedSeconds: number;
  expanded: boolean;
  expandedItemKeys: string[];
  externalOutputKey?: string;
  failed: boolean;
  items: AgentTraceItem[];
  loading: boolean;
  onExpandedChange: (expanded: boolean) => void;
  onItemExpandedChange: (key: string, expanded: boolean) => void;
  workingSeconds?: number;
};

function completeStatus(
  item: AgentTraceItem,
  status: "error" | "success",
  finishedAt: number,
): AgentTraceItem {
  if (item.kind === "tools") {
    const calls = item.calls.map((call) => {
      const callStatus = call.status === "running" ? status : call.status;
      return {
        ...call,
        status: callStatus,
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

function applyChatStreamEventAtLevel(
  items: AgentTraceItem[],
  event: ChatStreamEvent,
): AgentTraceItem[] {
  const parsedTime = Date.parse(event.created_at);
  const now = Number.isFinite(parsedTime) ? parsedTime : Date.now();
  const data = event.data;
  const streamUuid = typeof data.stream_uuid === "string" ? data.stream_uuid : event.id;
  const index = typeof data.index === "number" ? data.index : 0;
  const messageId = typeof data.message_id === "string" ? data.message_id : undefined;
  const messageUuid = typeof data.message_uuid === "string" ? data.message_uuid : event.id;
  const blockId = typeof data.block_id === "string"
    ? data.block_id
    : `${streamUuid}:${index}`;
  const isThinking = event.event.startsWith("assistant.thinking")
    || event.event === "subagent.thinking.completed";
  const contentKey = event.event.endsWith(".completed")
    ? `${messageId ?? messageUuid}:completed:${isThinking ? "thinking" : "reply"}`
    : `${blockId}:${isThinking ? "thinking" : "reply"}`;

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
          startedAt: now,
          status: "running",
        },
      ];
    }
    return items;
  }

  if (event.event === "assistant.thinking.delta" || event.event === "assistant.reply.delta") {
    const kind = isThinking ? "thinking" : "output";
    const text = isThinking
      ? (typeof data.thinking === "string" ? data.thinking : "")
      : (typeof data.text === "string" ? data.text : "");
    const existingIndex = items.findIndex((item) => item.key === contentKey);
    if (existingIndex === -1) {
      return [
        ...items,
        {
          content: text,
          key: contentKey,
          kind,
          startedAt: now,
          status: "running",
        },
      ];
    }
    return items.map((item, index) => (
      index === existingIndex && item.kind !== "tools"
        ? { ...item, content: `${item.content}${text}` }
        : item
    ));
  }

  if (event.event === "assistant.thinking.stopped" || event.event === "assistant.reply.stopped") {
    return items.map((item) => (
      item.key === contentKey ? completeStatus(item, "success", now) : item
    ));
  }

  if (event.event.endsWith(".reply.completed") || event.event.endsWith(".thinking.completed")) {
    const content = isThinking
      ? (typeof data.thinking === "string" ? data.thinking : "")
      : (typeof data.text === "string" ? data.text : "");
    const kind = isThinking ? "thinking" : "output";
    const completedMessageIds = [messageId, messageUuid]
      .filter((value): value is string => typeof value === "string");
    if (
      !content
      || items.some((item) => (
        item.kind === kind
        && completedMessageIds.some((id) => item.key.startsWith(`${id}:`))
      ))
    ) {
      return items;
    }
    return [
      ...items,
      {
        content,
        finishedAt: now,
        key: contentKey,
        kind,
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
    const input = typeof data.input === "object" && data.input !== null
      ? data.input
      : data;
    const rawSummary = JSON.stringify(input);
    const summary = rawSummary.length > 180 ? `${rawSummary.slice(0, 177)}...` : rawSummary;
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
        return item;
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
        const status: TraceStatus = running ? "running" : terminal;
        const completedStatus: "error" | "success" = terminal === "error" ? "error" : "success";
        return {
          ...call,
          status,
          taskIds: taskIds.length ? taskIds : undefined,
          trace: running ? call.trace : finishAgentTrace(call.trace, completedStatus, now),
        };
      });
      if (calls === item.calls || !calls.some((call, index) => call !== item.calls[index])) {
        return item;
      }
      const groupStatus: TraceStatus = calls.some((call) => call.status === "error")
        ? "error"
        : calls.some((call) => call.status === "running") ? "running" : "success";
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
        const nextStatus: TraceStatus = deferredAgentCompletion ? "running" : status;
        return {
          ...call,
          status: nextStatus,
          trace: deferredAgentCompletion
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

function applyNestedChatStreamEvent(
  items: AgentTraceItem[],
  parentToolId: string,
  event: ChatStreamEvent,
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
          trace: applyChatStreamEventAtLevel(call.trace, event),
        };
      }
      if (!call.trace.length) {
        return call;
      }
      const nested = applyNestedChatStreamEvent(call.trace, parentToolId, event);
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

export function applyChatStreamEvent(
  items: AgentTraceItem[],
  event: ChatStreamEvent,
): AgentTraceItem[] {
  if (event.parent_tool_use_id !== null) {
    return applyNestedChatStreamEvent(
      items,
      event.parent_tool_use_id,
      event,
    ).items;
  }
  return applyChatStreamEventAtLevel(items, event);
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

function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${seconds} 秒`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes} 分 ${remainingSeconds} 秒`;
}

function itemDuration(item: AgentTraceItem): string {
  const end = item.finishedAt ?? Date.now();
  const seconds = Math.max(1, Math.round((end - item.startedAt) / 1000));
  return formatDuration(seconds);
}

function toolLabel(name: string): string {
  const labels: Record<string, string> = {
    Bash: "执行命令",
    PowerShell: "执行命令",
    Edit: "编辑文件",
    Agent: "子代理",
    Glob: "查找文件",
    Grep: "搜索内容",
    Read: "读取文件",
    WebFetch: "读取网页",
    WebSearch: "搜索网页",
    Write: "写入文件",
    ExitPlanMode: "确认计划",
  };
  return labels[name] ?? "调用工具";
}

function toolStatus(status: TraceStatus): string {
  if (status === "running") {
    return "执行中";
  }
  return status === "error" ? "执行失败" : "已完成";
}

function isAgentTool(name: string): boolean {
  return name === "Agent" || name === "Task";
}

type TraceTimelineProps = {
  expandedItemKeys: string[];
  items: AgentTraceItem[];
  loading: boolean;
  nested?: boolean;
  onItemExpandedChange: (key: string, expanded: boolean) => void;
  showDurations: boolean;
};

function TraceTimeline({
  expandedItemKeys,
  items,
  loading,
  nested = false,
  onItemExpandedChange,
  showDurations,
}: TraceTimelineProps) {
  return (
    <div
      aria-live={nested ? undefined : "polite"}
      className={`agent-trace-timeline${nested ? " agent-trace-timeline-nested" : ""}`}
    >
      {!items.length && (
        loading ? (
          <div
            aria-label="等待 Claude 响应"
            className="agent-trace-empty agent-trace-waiting"
            role="status"
          >
            <LoadingOutlined spin />
          </div>
        ) : (
          <div className="agent-trace-empty">没有中途工作记录</div>
        )
      )}
      {items.map((item) => {
        const itemExpanded = expandedItemKeys.includes(item.key);
        if (item.kind === "thinking") {
          return (
            <Think
              blink={item.status === "running"}
              className="agent-trace-thinking"
              destroyOnHidden
              expanded={itemExpanded}
              key={item.key}
              loading={item.status === "running"}
              onExpand={(nextExpanded) => onItemExpandedChange(item.key, nextExpanded)}
              title={showDurations ? `思考 · ${itemDuration(item)}` : "思考"}
            >
              {item.content
                ? <ChatMarkdown content={item.content} streaming={item.status === "running"} />
                : <div className="agent-trace-empty">模型未返回可展示的思考摘要</div>}
            </Think>
          );
        }
        if (item.kind === "output") {
          return (
            <section
              className={`agent-trace-output${nested ? " agent-trace-output-nested" : ""}`}
              key={item.key}
            >
              <div className="agent-trace-output-title">
                <MessageOutlined />
                <span>{nested ? "子代理输出" : "输出"}</span>
              </div>
              <ChatMarkdown content={item.content} streaming={item.status === "running"} />
            </section>
          );
        }
        if (item.kind !== "tools") {
          return null;
        }

        const callsRunning = item.status === "running";
        const expandedCallKeys = item.calls
          .filter((call) => expandedItemKeys.includes(call.key))
          .map((call) => call.key);
        return (
          <Think
            className="agent-trace-tools"
            destroyOnHidden
            expanded={itemExpanded}
            icon={<ToolOutlined />}
            key={item.key}
            loading={callsRunning}
            onExpand={(nextExpanded) => onItemExpandedChange(item.key, nextExpanded)}
            title={`工具 · ${item.calls.length} 次调用${
              showDurations ? ` · ${itemDuration(item)}` : ""
            }`}
          >
            <ThoughtChain
              expandedKeys={expandedCallKeys}
              items={item.calls.map((call) => {
                const expandable = (
                  isAgentTool(call.name)
                  || call.trace.length > 0
                  || Boolean(call.plan)
                );
                return {
                  blink: call.status === "running",
                  collapsible: expandable,
                  content: expandable ? (
                    <div className="agent-subtrace">
                      {call.plan && (
                        <section className="agent-tool-plan">
                          <div className="agent-tool-plan-heading">
                            <FileTextOutlined />
                            <span>执行计划</span>
                          </div>
                          <ChatMarkdown content={call.plan} streaming={false} />
                        </section>
                      )}
                      {call.trace.length ? (
                        <TraceTimeline
                          expandedItemKeys={expandedItemKeys}
                          items={call.trace}
                          loading={call.status === "running"}
                          nested
                          onItemExpandedChange={onItemExpandedChange}
                          showDurations={showDurations}
                        />
                      ) : !call.plan ? (
                        <div className="agent-subtrace-empty">
                          {call.status === "running" && <LoadingOutlined spin />}
                          <span>
                            {call.status === "running"
                              ? "等待子代理返回内部轨迹…"
                              : "子代理没有返回可展示的内部轨迹"}
                          </span>
                        </div>
                      ) : null}
                    </div>
                  ) : undefined,
                  description: (
                    <span className="agent-tool-description">
                      <code>{call.name}</code>
                      {call.summary && <span>{call.summary}</span>}
                      <span className={`agent-tool-status agent-tool-status-${call.status}`}>
                        {toolStatus(call.status)}
                      </span>
                    </span>
                  ),
                  key: call.key,
                  status: call.status === "running" ? "loading" as const : call.status,
                  title: toolLabel(call.name),
                };
              })}
              line="solid"
              onExpand={(nextExpandedKeys) => {
                for (const call of item.calls) {
                  if (!isAgentTool(call.name) && !call.trace.length && !call.plan) {
                    continue;
                  }
                  const wasExpanded = expandedCallKeys.includes(call.key);
                  const nextExpanded = nextExpandedKeys.includes(call.key);
                  if (wasExpanded !== nextExpanded) {
                    onItemExpandedChange(call.key, nextExpanded);
                  }
                }
              }}
            />
          </Think>
        );
      })}
    </div>
  );
}

export function AgentTrace({
  elapsedSeconds,
  expanded,
  expandedItemKeys,
  externalOutputKey,
  failed,
  items,
  loading,
  onExpandedChange,
  onItemExpandedChange,
  workingSeconds,
}: AgentTraceProps) {
  const visibleItems = externalOutputKey
    ? items.filter((item) => item.key !== externalOutputKey)
    : items;
  const completedTitle = failed ? "执行失败" : "已工作";
  const showDurations = loading || workingSeconds !== undefined;
  const title = loading
    ? `工作中 ${formatDuration(elapsedSeconds)}`
    : workingSeconds === undefined
      ? completedTitle
      : `${completedTitle} ${formatDuration(workingSeconds)}`;
  const completedIcon = failed ? <CloseCircleOutlined /> : <CheckCircleOutlined />;

  return (
    <Think
      blink={loading}
      className="agent-trace"
      classNames={{ content: "agent-trace-content", status: "agent-trace-header" }}
      destroyOnHidden
      expanded={expanded}
      icon={completedIcon}
      loading={loading}
      onExpand={onExpandedChange}
      title={title}
    >
      <TraceTimeline
        expandedItemKeys={expandedItemKeys}
        items={visibleItems}
        loading={loading}
        onItemExpandedChange={onItemExpandedChange}
        showDurations={showDurations}
      />
    </Think>
  );
}
