import { BarChartOutlined } from "@ant-design/icons";
import { Button, Popover } from "antd";

export type TokenUsageSummary = {
  inputTokens: number;
  outputTokens: number;
  subagentTokens: number;
  totalTokens: number;
};

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

function TokenUsageDetails({ usage }: { usage: TokenUsageSummary }) {
  return (
    <div className="response-usage-card token-usage-card">
      <div className="response-usage-title">
        <strong>Token 总消耗</strong>
      </div>
      <dl className="response-usage-grid">
        <div><dt>主 Agent 输入</dt><dd>{formatTokenCount(usage.inputTokens)}</dd></div>
        <div><dt>主 Agent 输出</dt><dd>{formatTokenCount(usage.outputTokens)}</dd></div>
        <div><dt>子 Agent</dt><dd>{formatTokenCount(usage.subagentTokens)}</dd></div>
        <div><dt>合计</dt><dd>{formatTokenCount(usage.totalTokens)}</dd></div>
      </dl>
    </div>
  );
}

export function TokenUsageIndicator({ usage }: { usage: TokenUsageSummary }) {
  return (
    <Popover
      content={<TokenUsageDetails usage={usage} />}
      mouseEnterDelay={0.1}
      placement="topRight"
    >
      <Button
        aria-label="查看 Token 总消耗"
        className="token-usage-indicator"
        type="text"
      >
        <span className="token-usage-value">
          <BarChartOutlined />
          <span>总 Token {formatTokenCount(usage.totalTokens)}</span>
        </span>
      </Button>
    </Popover>
  );
}
