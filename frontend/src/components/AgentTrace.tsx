import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  FileTextOutlined,
  LoadingOutlined,
  MessageOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import { Think, ThoughtChain } from "@ant-design/x";

import type {
  ChatPermissionRequestEvent,
  ChatStreamEvent,
} from "../bridge/client";
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
  const now = event.timestamp ?? Date.now();

  if (event.type === "thinking_start" || event.type === "output_start") {
    const kind = event.type === "thinking_start" ? "thinking" : "output";
    const existingIndex = items.findIndex((item) => item.key === event.block_id);
    if (existingIndex === -1) {
      return [
        ...items,
        {
          content: "",
          key: event.block_id,
          kind,
          startedAt: now,
          status: "running",
        },
      ];
    }
    return items;
  }

  if (event.type === "thinking_delta" || event.type === "output_delta") {
    const kind = event.type === "thinking_delta" ? "thinking" : "output";
    const existingIndex = items.findIndex((item) => item.key === event.block_id);
    if (existingIndex === -1) {
      return [
        ...items,
        {
          content: event.text,
          key: event.block_id,
          kind,
          startedAt: now,
          status: "running",
        },
      ];
    }
    return items.map((item, index) => (
      index === existingIndex && item.kind !== "tools"
        ? { ...item, content: `${item.content}${event.text}` }
        : item
    ));
  }

  if (event.type === "thinking_complete" || event.type === "output_complete") {
    return items.map((item) => (
      item.key === event.block_id ? completeStatus(item, "success", now) : item
    ));
  }

  if (event.type === "tool_start") {
    const previousItem = items.at(-1);
    const plan = (
      event.name === "ExitPlanMode"
      && previousItem?.kind === "output"
      && previousItem.content.trim()
    ) || undefined;
    const sourceItems = plan ? items.slice(0, -1) : items;
    const toolCall: ToolCall = {
      key: event.tool_id,
      name: event.name,
      plan,
      status: "running",
      summary: event.summary,
      trace: [],
    };
    const groupIndex = sourceItems.findIndex((item) => item.key === event.group_id);
    if (groupIndex === -1) {
      return [
        ...sourceItems,
        {
          calls: [toolCall],
          key: event.group_id,
          kind: "tools",
          startedAt: now,
          status: "running",
        },
      ];
    }
    return sourceItems.map((item, index) => {
      if (index !== groupIndex || item.kind !== "tools") {
        return item;
      }
      if (item.calls.some((call) => call.key === event.tool_id)) {
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

  if (event.type === "tool_complete") {
    return items.map((item) => {
      if (item.kind !== "tools") {
        return item;
      }
      const callIndex = item.calls.findIndex((call) => call.key === event.tool_id);
      if (callIndex === -1) {
        return item;
      }
      const calls = item.calls.map((call) => (
        call.key === event.tool_id
          ? {
              ...call,
              status: event.status,
              trace: finishAgentTrace(call.trace, event.status, now),
            }
          : call
      ));
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
  if (event.parent_tool_id !== undefined) {
    return applyNestedChatStreamEvent(
      items,
      event.parent_tool_id,
      event,
    ).items;
  }
  return applyChatStreamEventAtLevel(items, event);
}

type ExitPlanPermissionUpdate = {
  expandedItemKeys: string[];
  items: AgentTraceItem[];
};

export function applyExitPlanPermission(
  items: AgentTraceItem[],
  event: ChatPermissionRequestEvent,
): ExitPlanPermissionUpdate {
  const rawPlan = event.tool_name === "ExitPlanMode" ? event.input.plan : null;
  const plan = typeof rawPlan === "string" ? rawPlan.trim() : "";
  if (!plan) {
    return { expandedItemKeys: [], items };
  }
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item.kind !== "tools") {
      continue;
    }
    let callIndex = -1;
    for (let candidateIndex = item.calls.length - 1; candidateIndex >= 0; candidateIndex -= 1) {
      if (item.calls[candidateIndex].name === "ExitPlanMode") {
        callIndex = candidateIndex;
        break;
      }
    }
    if (callIndex === -1) {
      continue;
    }
    const call = item.calls[callIndex];
    const calls = item.calls.map((candidate, candidateIndex) => (
      candidateIndex === callIndex ? { ...candidate, plan } : candidate
    ));
    return {
      expandedItemKeys: [item.key, call.key],
      items: items.map((candidate, candidateIndex) => (
        candidateIndex === index ? { ...item, calls } : candidate
      )),
    };
  }
  return { expandedItemKeys: [], items };
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
  return name === "Agent";
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
