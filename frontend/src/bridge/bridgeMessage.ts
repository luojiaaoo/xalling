import { App, message as staticMessage } from "antd";

// 桥接层统一的 js2py 异常提示：由 BridgeMessageHost 把带主题上下文的
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

declare global {
  interface Window {
    __xallingNotifyPy2JsError?: (action: string, error: string) => void;
  }
}

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
  showBridgeMessage(`后端调用失败（${action}）：${formatBridgeError(error)}`);
}

// py2js 方向：安装到 window 上供 Python evaluate_js 回调，
// Python 执行 JS 出错时由后端包装函数调用，把异常通过 message 提示出来。
export function installPy2JsErrorNotifier(): void {
  window.__xallingNotifyPy2JsError = (action, error) => {
    showBridgeMessage(`前端脚本执行失败（${action}）：${error}`);
  };
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
