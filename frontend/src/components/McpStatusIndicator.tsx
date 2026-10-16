import { ApiOutlined, LoadingOutlined, ReloadOutlined } from "@ant-design/icons";
import { Badge, Button, Popover } from "antd";
import { useEffect, useState } from "react";

import { getMcpStatus, type McpServerStatus, type McpStatus } from "../api/client";

const statusLabels = {
  connected: { badge: "success", label: "已加载" },
  pending: { badge: "processing", label: "加载中" },
  failed: { badge: "error", label: "加载失败" },
  "needs-auth": { badge: "warning", label: "需要认证" },
  disabled: { badge: "default", label: "已禁用" },
} as const;

function serverStatus(status: McpServerStatus["status"]) {
  return statusLabels[status] ?? { badge: "default", label: "未知状态" };
}

export function McpStatusIndicator({ sessionId, busy }: { sessionId: string; busy: boolean }) {
  const [status, setStatus] = useState<McpStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let disposed = false;
    let timer: number | undefined;
    const refresh = async () => {
      setLoading(true);
      let pending = false;
      try {
        const result = await getMcpStatus(sessionId);
        if (disposed) return;
        setStatus(result);
        setFailed(false);
        pending = result?.servers.some((server) => server.status === "pending") ?? false;
      } catch {
        if (disposed) return;
        setStatus(null);
        setFailed(true);
      } finally {
        if (!disposed) {
          setLoading(false);
          if (busy || open || pending) timer = window.setTimeout(() => void refresh(), 3_000);
        }
      }
    };
    void refresh();
    return () => {
      disposed = true;
      window.clearTimeout(timer);
    };
  }, [sessionId, busy, open, revision]);

  const servers = status?.servers ?? [];
  const connected = servers.filter((server) => server.status === "connected").length;
  const hasFailure = failed || servers.some((server) => ["failed", "needs-auth"].includes(server.status));
  const pending = servers.some((server) => server.status === "pending");
  const label = failed ? "MCP 获取失败"
    : status ? `MCP ${connected}/${servers.length}`
    : loading || busy ? "MCP 加载中" : "MCP 未启动";
  const badge = hasFailure ? "error" : pending || (!status && (busy || loading)) ? "processing"
    : connected > 0 ? "success" : "default";

  return (
    <Popover
      content={(
        <div className="mcp-status-card">
          <div className="mcp-status-heading">
            <strong>MCP 加载情况</strong>
            <Button
              aria-label="刷新 MCP 状态"
              icon={<ReloadOutlined />}
              loading={loading}
              onClick={() => setRevision((value) => value + 1)}
              size="small"
              type="text"
            />
          </div>
          <div className="mcp-status-summary" role="status">
            {failed ? "暂时无法获取 MCP 状态，请刷新重试。"
              : status ? `已加载 ${connected} / ${servers.length} 个服务`
              : loading || busy ? "正在等待会话初始化…"
              : "当前会话尚未启动，发送消息后将显示实际加载情况。"}
          </div>
          {status && servers.length === 0 && (
            <div className="mcp-status-summary">当前会话未加载 MCP 服务。</div>
          )}
          {servers.length > 0 && (
            <ul className="mcp-status-list" aria-label="MCP 服务列表">
              {servers.map((server) => {
                const state = serverStatus(server.status);
                return (
                  <li key={server.name}>
                    <div className="mcp-status-server">
                      <span className="mcp-status-name">{server.name}</span>
                      <Badge status={state.badge} text={state.label} />
                    </div>
                    {server.status === "connected" && (
                      <span className="mcp-status-tools">
                        {server.tool_count === null ? "工具数量暂不可用" : `${server.tool_count} 个工具`}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
      open={open}
      onOpenChange={setOpen}
      placement="topRight"
      trigger="click"
    >
      <Button
        aria-label={`查看 MCP 加载情况：${label}`}
        aria-expanded={open}
        className="mcp-status-indicator"
        icon={!status && loading ? <LoadingOutlined spin /> : <ApiOutlined />}
        type="text"
      >
        <Badge status={badge} />
        {label}
      </Button>
    </Popover>
  );
}
