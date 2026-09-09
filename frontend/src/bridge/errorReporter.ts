import { reportFrontendError } from "./client";

// 浏览器控制台错误实时上报到本地 browser.log（Python 侧 LogRouter 接收）。
// 覆盖三类来源：console.error/warn、未捕获异常、未处理的 Promise rejection。

const DEDUPE_WINDOW_MS = 1000;

let lastFingerprint = "";
let lastReportedAt = 0;

function formatArg(arg: unknown): string {
  if (arg instanceof Error) {
    return arg.message;
  }
  if (typeof arg === "string") {
    return arg;
  }
  try {
    return JSON.stringify(arg) ?? String(arg);
  } catch {
    return String(arg);
  }
}

function report(kind: string, message: string, stack?: string): void {
  // 相同错误短时间内只上报一次，避免错误风暴打满桥接
  const fingerprint = `${kind}:${message}`;
  const now = Date.now();
  if (fingerprint === lastFingerprint && now - lastReportedAt < DEDUPE_WINDOW_MS) {
    return;
  }
  lastFingerprint = fingerprint;
  lastReportedAt = now;

  void reportFrontendError(kind, message, stack ?? null).catch(() => undefined);
}

function stackOf(value: unknown): string | undefined {
  return value instanceof Error ? value.stack : undefined;
}

export function installErrorReporter(): void {
  window.addEventListener("error", (event) => {
    report("error", event.message, stackOf(event.error));
  });

  window.addEventListener("unhandledrejection", (event) => {
    const reason: unknown = event.reason;
    report(
      "unhandledrejection",
      reason instanceof Error ? reason.message : formatArg(reason),
      stackOf(reason),
    );
  });

  for (const level of ["error", "warn"] as const) {
    const original = console[level];
    console[level] = (...args: unknown[]) => {
      original.apply(console, args);
      report(
        `console.${level}`,
        args.map(formatArg).join(" "),
        stackOf(args.find((arg) => arg instanceof Error)),
      );
    };
  }
}
