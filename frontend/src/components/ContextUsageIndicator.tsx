import { FundOutlined } from "@ant-design/icons";
import { Button, Popover, Progress } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";

import { getContextUsage, type ContextUsage } from "../bridge/client";

type ContextUsageIndicatorProps = {
  busy: boolean;
  sessionId: string;
};

const POLL_INTERVAL_MS = 2_000;

// 与 Workspace 的 formatTokenCount 保持一致的 Token 缩写展示
function formatTokenCount(value: number): string {
  const formatScaled = (scaled: number, unit: "K" | "M" | "亿") => (
    `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(scaled)}${unit}`
  );
  if (value >= 100_000_000) {
    return formatScaled(value / 100_000_000, "亿");
  }
  if (value >= 1_000_000) {
    return formatScaled(value / 1_000_000, "M");
  }
  if (value >= 1_000) {
    return formatScaled(value / 1_000, "K");
  }
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

// 各成份占窗口的百分比，极小值显示为 <0.1%
function formatPercent(value: number): string {
  if (value > 0 && value < 0.1) {
    return "<0.1%";
  }
  return `${value.toFixed(1)}%`;
}

// SDK 返回的 color 字段在此代理环境下不可靠（可能为空或无效 CSS），
// 这里按成份名固定配色，与 Claude Code /context 的配色一致。
const CATEGORY_COLORS: Record<string, string> = {
  "System prompt": "#e8a33d",
  "System tools": "#4f8cff",
  "MCP tools": "#3fb950",
  "Memory files": "#b08968",
  "Skills": "#a86bff",
  "Messages": "#f25c5c",
  "Autocompact buffer": "#38bdf8",
};

function categoryColor(name: string): string {
  return CATEGORY_COLORS[name] ?? "#6d5dfc";
}

// 按成份颜色堆叠的占用进度条；“Free space”不画段，留给容器底色（即剩余色）
function ContextUsageStack({ usage }: { usage: ContextUsage }) {
  const maxTokens = usage.maxTokens > 0 ? usage.maxTokens : 1;
  return (
    <div
      className="context-usage-stack"
      role="img"
      aria-label="上下文占用分布"
    >
      {usage.categories
        .filter((category) => category.name !== "Free space")
        .map((category) => {
          const width = (category.tokens / maxTokens) * 100;
          if (width <= 0) {
            return null;
          }
          return (
            <span
              key={category.name}
              className="context-usage-stack-segment"
              style={{ width: `${width}%`, background: categoryColor(category.name) }}
              title={`${category.name}: ${formatTokenCount(category.tokens)}`}
            />
          );
        })}
    </div>
  );
}

function ContextUsageCard({ usage }: { usage: ContextUsage }) {
  const percentage = Math.round(usage.percentage ?? 0);
  const maxTokens = usage.maxTokens > 0 ? usage.maxTokens : 0;
  return (
    <div className="context-usage-card">
      <div className="context-usage-title">
        <strong>上下文占用</strong>
        <span>{percentage}%</span>
      </div>
      <ContextUsageStack usage={usage} />
      <dl className="context-usage-grid">
        <div><dt>已用</dt><dd>{formatTokenCount(usage.totalTokens ?? 0)}</dd></div>
        <div><dt>上限</dt><dd>{formatTokenCount(usage.maxTokens ?? 0)}</dd></div>
        <div className="context-usage-wide">
          <dt>模型</dt><dd title={usage.model}>{usage.model || "—"}</dd>
        </div>
      </dl>
      {usage.categories.length > 0 && (
        <ul className="context-usage-categories">
          {usage.categories.map((category) => {
            const share = maxTokens > 0 ? (category.tokens / maxTokens) * 100 : 0;
            const isFree = category.name === "Free space";
            return (
              <li key={category.name}>
                <span
                  className={isFree ? "context-usage-dot context-usage-dot-free" : "context-usage-dot"}
                  style={isFree ? undefined : { background: categoryColor(category.name) }}
                />
                <span className="context-usage-category-name">{category.name}</span>
                <span className="context-usage-category-tokens">
                  {formatTokenCount(category.tokens)}
                </span>
                <span className="context-usage-category-share">{formatPercent(share)}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export function ContextUsageIndicator({ busy, sessionId }: ContextUsageIndicatorProps) {
  const [usage, setUsage] = useState<ContextUsage | null>(null);
  const requestIdRef = useRef(0);
  const previousBusyRef = useRef(busy);

  const refresh = useCallback(() => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    void getContextUsage(sessionId)
      .then((result) => {
        if (requestId === requestIdRef.current) {
          setUsage(result);
        }
      })
      .catch(() => {
        if (requestId === requestIdRef.current) {
          setUsage(null);
        }
      });
  }, [sessionId]);

  // 会话切换时立即拉取一次
  useEffect(() => {
    refresh();
  }, [refresh]);

  // 生成中每 2s 轮询；由生成切换为空闲时补拉一次最终占用
  useEffect(() => {
    const previousBusy = previousBusyRef.current;
    previousBusyRef.current = busy;
    if (previousBusy && !busy) {
      refresh();
    }
    const timer = window.setInterval(refresh, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [busy, refresh]);

  const hasData = usage !== null;
  const percentage = Math.round(usage?.percentage ?? 0);

  return (
    <Popover
      content={usage ? <ContextUsageCard usage={usage} /> : null}
      mouseEnterDelay={0.1}
      onOpenChange={(open) => {
        if (open) {
          refresh();
        }
      }}
      placement="topRight"
    >
      <Button
        aria-label="查看上下文占用"
        className="context-usage-indicator"
        type="text"
      >
        {hasData ? (
          <span className="context-usage-value">
            <Progress
              percent={percentage}
              showInfo={false}
              size={20}
              strokeWidth={6}
              type="circle"
            />
            <span>{percentage}%</span>
          </span>
        ) : (
          <span className="context-usage-value">
            <FundOutlined />
            <span>上下文</span>
          </span>
        )}
      </Button>
    </Popover>
  );
}
