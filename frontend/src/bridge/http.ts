/** Authenticated same-origin calls to typed FastAPI routes. */
import { notifyBridgeError } from "./bridgeMessage";
import { connectEvents, connectionToken, TransportDisconnectedError } from "./websocket";

type RequestOptions = {
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  timeoutMs?: number;
  silent?: boolean;
};

const inFlight = new Set<AbortController>();

window.addEventListener("xalling:transport-disconnected", () => {
  for (const controller of inFlight) {
    controller.abort(new TransportDisconnectedError("本机服务连接已断开，正在恢复会话"));
  }
});

window.addEventListener("beforeunload", () => {
  for (const controller of inFlight) controller.abort(new Error("应用正在关闭"));
});

export async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    // Open the event channel before work can request tool permissions.
    await connectEvents();
    const url = new URL(path, window.location.origin);
    for (const [key, value] of Object.entries(options.query ?? {})) {
      if (value !== null && value !== undefined) url.searchParams.set(key, String(value));
    }
    inFlight.add(controller);
    timer = setTimeout(() => controller.abort(new Error("后端响应超时，请查看操作状态")), options.timeoutMs ?? 5 * 60 * 1000);
    const response = await fetch(url, {
      method,
      credentials: "same-origin",
      headers: { Authorization: `Bearer ${connectionToken()}`, "Content-Type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: controller.signal,
    });
    const result: unknown = await response.json();
    if (!response.ok) {
      const detail = typeof result === "object" && result !== null && "detail" in result ? result.detail : null;
      const message = typeof detail === "string" ? detail : Array.isArray(detail)
        ? detail.map((item: { msg?: string }) => item.msg ?? "参数无效").join("；")
        : `后端调用失败（${response.status}）`;
      throw new Error(message);
    }
    return result as T;
  } catch (error) {
    const failure: unknown = controller.signal.aborted ? controller.signal.reason : error;
    if (!options.silent) notifyBridgeError(path, failure);
    throw failure;
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    inFlight.delete(controller);
  }
}
