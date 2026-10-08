import { App, message as staticMessage } from "antd";

// 统一的后端调用异常提示：由 BridgeMessageHost 把带主题上下文的
// message 实例注册进来；组件尚未挂载（或纯浏览器调试）时回退到静态 message。

type BridgeMessageInstance = ReturnType<typeof App.useApp>["message"];

let currentInstance: BridgeMessageInstance | null = null;

export function registerBridgeMessage(
  messageInstance: BridgeMessageInstance,
): () => void {
  currentInstance = messageInstance;
  return () => {
    if (currentInstance === messageInstance) {
      currentInstance = null;
    }
  };
}

const DEDUPE_WINDOW_MS = 3000;

let lastContent = "";
let lastShownAt = 0;

export function formatBridgeError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === "string") {
    return error;
  }
  try {
    return JSON.stringify(error) ?? String(error);
  } catch {
    return String(error);
  }
}

export function notifyBridgeError(action: string, error: unknown): void {
  showBridgeMessage(`Backend(${action}): ${formatBridgeError(error)}`);
}

function showBridgeMessage(content: string): void {
  // 相同异常短时间内只提示一次，避免失败风暴刷屏
  const now = Date.now();
  if (content === lastContent && now - lastShownAt < DEDUPE_WINDOW_MS) {
    return;
  }
  lastContent = content;
  lastShownAt = now;

  const api = currentInstance ?? staticMessage;
  void api.error(content);
}
