/** One authenticated socket carries ordered chat events. */
export const TRANSPORT_READY_EVENT = "xalling:transport-ready";
const CHAT_STREAM_EVENT = "xalling:chat-event";

export class TransportDisconnectedError extends Error {}

let socket: WebSocket | null = null;
let connecting: Promise<WebSocket> | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectDelay = 500;
let unloading = false;
let openedOnce = false;

export function connectionToken(): string {
  const key = `xalling:ws-token:${window.location.origin}`;
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const supplied = fragment.get("token");
  if (supplied) {
    sessionStorage.setItem(key, supplied);
    // Keep the launch credential out of links and subsequent navigation.
    history.replaceState(null, "", window.location.pathname + window.location.search);
  }
  const token = supplied ?? sessionStorage.getItem(key);
  if (!token) throw new Error("缺少本地服务连接凭证，请从桌面应用启动");
  return token;
}

function scheduleReconnect(): void {
  if (unloading || reconnectTimer !== null) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    void connectEvents().catch(() => undefined);
  }, reconnectDelay);
  reconnectDelay = Math.min(reconnectDelay * 2, 5000);
}

function receiveMessage(event: MessageEvent<string>): void {
  let value: unknown;
  try {
    value = JSON.parse(event.data);
  } catch {
    socket?.close(1002, "Invalid JSON");
    return;
  }
  if (typeof value !== "object" || value === null || !("type" in value)) return;
  const envelope = value as Record<string, unknown>;
  if (envelope.type === "event" && envelope.event === "chat") {
    window.dispatchEvent(new CustomEvent(CHAT_STREAM_EVENT, { detail: envelope.data }));
    return;
  }
}

export async function connectEvents(): Promise<WebSocket> {
  if (unloading) throw new Error("应用正在关闭");
  if (socket?.readyState === WebSocket.OPEN) return socket;
  if (connecting) return connecting;
  const token = connectionToken();
  const url = new URL("/ws", window.location.href);
  url.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const candidate = new WebSocket(url, ["xalling", `auth.${token}`]);
  socket = candidate;
  const attempt = new Promise<WebSocket>((resolve, reject) => {
    const timeout = setTimeout(() => candidate.close(), 10000);
    candidate.addEventListener("open", () => {
      clearTimeout(timeout);
      reconnectDelay = 500;
      resolve(candidate);
      window.dispatchEvent(new CustomEvent(TRANSPORT_READY_EVENT, {
        detail: { reconnected: openedOnce },
      }));
      openedOnce = true;
    }, { once: true });
    candidate.addEventListener("message", receiveMessage);
    candidate.addEventListener("error", () => {
      clearTimeout(timeout);
      reject(new Error("无法连接本地 WebSocket 服务"));
    }, { once: true });
    candidate.addEventListener("close", (event) => {
      clearTimeout(timeout);
      const error = new TransportDisconnectedError("本地服务连接已断开；正在执行的操作可通过会话恢复查看");
      reject(error);
      if (socket === candidate) {
        socket = null;
        window.dispatchEvent(new CustomEvent("xalling:transport-disconnected", { detail: error }));
        if (event.code !== 1008) scheduleReconnect();
      }
    }, { once: true });
  });
  connecting = attempt;
  try {
    return await attempt;
  } finally {
    if (connecting === attempt) connecting = null;
  }
}

window.addEventListener("beforeunload", () => {
  unloading = true;
  if (reconnectTimer !== null) clearTimeout(reconnectTimer);
  socket?.close();
});
