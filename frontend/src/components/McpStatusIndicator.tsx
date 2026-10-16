import { ApiOutlined, LoadingOutlined } from "@ant-design/icons";
import { Badge, Button, Popover } from "antd";
import { useEffect, useRef, useState } from "react";

import { getMcpStatus, reconnectMcpServer, type McpServerStatus, type McpStatus } from "../api/client";

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
  const [reconnecting, setReconnecting] = useState<Set<string>>(new Set());
  const [reconnectErrors, setReconnectErrors] = useState<Set<string>>(new Set());
  const reconnectRequests = useRef(new Set<string>());

  useEffect(() => {
    const requests = new Set<string>();
    reconnectRequests.current = requests;
    setReconnecting(new Set());
    setReconnectErrors(new Set());
    setStatus(null);
    return () => {
      if (reconnectRequests.current === requests) reconnectRequests.current = new Set();
    };
  }, [sessionId]);

  const reconnect = async (serverName: string) => {
    const requests = reconnectRequests.current;
    if (requests.has(serverName)) return;
    requests.add(serverName);
    setReconnecting(new Set(requests));
    setReconnectErrors((errors) => {
      const next = new Set(errors);
      next.delete(serverName);
      return next;
    });
    try {
      await reconnectMcpServer(sessionId, serverName);
    } catch {
      if (reconnectRequests.current === requests) {
        setReconnectErrors((errors) => new Set(errors).add(serverName));
      }
    } finally {
      requests.delete(serverName);
      if (reconnectRequests.current === requests) {
        setReconnecting(new Set(requests));
        setRevision((value) => value + 1);
      }
    }
  };

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
          </div>
          <div className="mcp-status-summary" role="status">
            {failed ? "暂时无法获取 MCP 状态，正在自动重试。"
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
                      <div className="mcp-status-actions">
                        <Badge status={state.badge} text={state.label} />
                        {(server.status === "failed" || reconnecting.has(server.name)) && (
                          <Button
                            aria-label={`重连 MCP 服务 ${server.name}`}
                            loading={reconnecting.has(server.name)}
                            onClick={() => void reconnect(server.name)}
                            size="small"
                            type="link"
                          >
                            {reconnecting.has(server.name) ? "重连中" : "重连"}
                          </Button>
                        )}
                      </div>
                    </div>
                    {server.status === "failed" && reconnectErrors.has(server.name) && (
                      <div className="mcp-status-error" role="alert">重连失败，请稍后重试。</div>
                    )}
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
