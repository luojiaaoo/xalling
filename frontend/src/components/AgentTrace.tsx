import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  FileTextOutlined,
  LoadingOutlined,
  MessageOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import { Think, ThoughtChain } from "@ant-design/x";

import { isAgentTool, type AgentTraceItem, type TraceStatus } from "../chat/trace";
import { ChatMarkdown } from "./ChatMarkdown";

type AgentTraceProps = {
  elapsedSeconds: number;
  expanded: boolean;
  expandedItemKeys: string[];
  externalOutputKey?: string;
  externalOutputKeys?: string[];
  failed: boolean;
  items: AgentTraceItem[];
  loading: boolean;
  onExpandedChange: (expanded: boolean) => void;
  onItemExpandedChange: (key: string, expanded: boolean) => void;
  workingSeconds?: number;
};

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
            aria-label="等待响应"
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
                  || Boolean(call.output)
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
                      ) : !call.plan && !call.output ? (
                        <div className="agent-subtrace-empty">
                          {call.status === "running" && <LoadingOutlined spin />}
                          <span>
                            {call.status === "running"
                              ? "等待子代理返回内部轨迹…"
                              : "子代理没有返回可展示的内部轨迹"}
                          </span>
                        </div>
                      ) : null}
                      {call.output && <ChatMarkdown content={call.output} streaming={false} />}
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
                  if (!isAgentTool(call.name) && !call.trace.length && !call.plan && !call.output) {
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
  externalOutputKeys,
  failed,
  items,
  loading,
  onExpandedChange,
  onItemExpandedChange,
  workingSeconds,
}: AgentTraceProps) {
  const outputKeys = externalOutputKeys ?? (externalOutputKey ? [externalOutputKey] : []);
  const visibleItems = outputKeys.length
    ? items.filter((item) => !outputKeys.includes(item.key))
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
