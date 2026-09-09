import {
  CheckCircleOutlined,
  CloseCircleOutlined,
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
  status: TraceStatus;
  summary: string;
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
    const calls = item.calls.map((call) => (
      call.status === "running" ? { ...call, status } : call
    ));
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

export function applyChatStreamEvent(
  items: AgentTraceItem[],
  event: ChatStreamEvent,
): AgentTraceItem[] {
  const now = Date.now();

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
    const toolCall: ToolCall = {
      key: event.tool_id,
      name: event.name,
      status: "running",
      summary: event.summary,
    };
    const groupIndex = items.findIndex((item) => item.key === event.group_id);
    if (groupIndex === -1) {
      return [
        ...items,
        {
          calls: [toolCall],
          key: event.group_id,
          kind: "tools",
          startedAt: now,
          status: "running",
        },
      ];
    }
    return items.map((item, index) => {
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
      const calls = item.calls.map((call) => (
        call.key === event.tool_id ? { ...call, status: event.status } : call
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

export function finishAgentTrace(
  items: AgentTraceItem[],
  status: "error" | "success",
): AgentTraceItem[] {
  const finishedAt = Date.now();
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
    Edit: "编辑文件",
    Glob: "查找文件",
    Grep: "搜索内容",
    Read: "读取文件",
    WebFetch: "读取网页",
    WebSearch: "搜索网页",
    Write: "写入文件",
  };
  return labels[name] ?? "调用工具";
}

function toolStatus(status: TraceStatus): string {
  if (status === "running") {
    return "执行中";
  }
  return status === "error" ? "执行失败" : "已完成";
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
  workingSeconds = 1,
}: AgentTraceProps) {
  const visibleItems = externalOutputKey
    ? items.filter((item) => item.key !== externalOutputKey)
    : items;
  const title = loading
    ? `工作中 ${formatDuration(elapsedSeconds)}`
    : `${failed ? "执行失败" : "已工作"} ${formatDuration(workingSeconds)}`;
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
      <div className="agent-trace-timeline" aria-live="polite">
        {!visibleItems.length && (
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
        {visibleItems.map((item) => {
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
                title={`思考 · ${itemDuration(item)}`}
              >
                {item.content
                  ? <ChatMarkdown content={item.content} streaming={item.status === "running"} />
                  : <div className="agent-trace-empty">模型未返回可展示的思考摘要</div>}
              </Think>
            );
          }
          if (item.kind === "output") {
            return (
              <section className="agent-trace-output" key={item.key}>
                <div className="agent-trace-output-title">
                  <MessageOutlined />
                  <span>输出</span>
                </div>
                <ChatMarkdown content={item.content} streaming={item.status === "running"} />
              </section>
            );
          }
          if (item.kind !== "tools") {
            return null;
          }

          const callsRunning = item.status === "running";
          return (
            <Think
              className="agent-trace-tools"
              destroyOnHidden
              expanded={itemExpanded}
              icon={<ToolOutlined />}
              key={item.key}
              loading={callsRunning}
              onExpand={(nextExpanded) => onItemExpandedChange(item.key, nextExpanded)}
              title={`工具 · ${item.calls.length} 次调用 · ${itemDuration(item)}`}
            >
              <ThoughtChain
                items={item.calls.map((call) => ({
                  key: call.key,
                  title: toolLabel(call.name),
                  description: (
                    <span className="agent-tool-description">
                      <code>{call.name}</code>
                      {call.summary && <span>{call.summary}</span>}
                      <span className={`agent-tool-status agent-tool-status-${call.status}`}>
                        {toolStatus(call.status)}
                      </span>
                    </span>
                  ),
                  status: call.status === "running" ? "loading" : call.status,
                }))}
                line="solid"
              />
            </Think>
          );
        })}
      </div>
    </Think>
  );
}
