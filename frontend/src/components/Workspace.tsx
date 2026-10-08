import {
  BarChartOutlined,
  CheckOutlined,
  CopyOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import { Bubble } from "@ant-design/x";
import { App as AntdApp, Popover } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { flushSync } from "react-dom";

import {
  getActiveChat,
  getChatSession,
  getHomeFolder,
  isPermissionRequestEvent,
  respondChatPermission,
  saveAttachment,
  sendChatMessage,
  stopChatMessage,
  subscribeChatEvents,
  TransportDisconnectedError,
  type ChatPermissionAnswers,
  type ChatPermissionMode,
  type ChatPlanExecutionMode,
  type ChatPermissionRequestEvent,
  type ChatRenderEvent,
  type ChatUsage,
  type ModelSelection,
  type ProjectFolder,
  type SubagentUsage,
} from "../api/client";
import { pickQuote } from "../quotes";
import {
  AgentTrace,
} from "./AgentTrace";
import { finishAgentTrace } from "../chat/trace";
import { conversationFromEvents, reduceConversationEvent, isConversationEvent, eventTime, turnAssistantKey, contextCompactionText, pendingPermissionsFromEvents, type ConversationMessage } from "../chat/conversation";
import { ChatMarkdown } from "./ChatMarkdown";
import { TurnChanges } from "./TurnChanges";
import {
  TaskComposer,
  type ComposerAttachment,
  type ComposerDraft,
} from "./TaskComposer";
import type { TokenUsageSummary } from "./TokenUsageIndicator";

const effortValues = ["low", "medium", "high", "max"] as const;

const greetingsByPeriod: string[][] = [
  ["凌晨好呀，夜深了，别太拼，慢慢来。", "凌晨好呀，这么晚还醒着，辛苦了，剩下的交给我。", "凌晨好呀，安静的深夜适合专注，但也记得照顾自己。"],
  ["早上好呀，这么早就开始啦，新的一天一起加油！", "早上好呀，清晨的你已经很棒了，今天会是好日子。", "早上好呀，早起的鸟儿有虫吃，我们一起加油！"],
  ["早上好呀，元气满满的上午，正适合开工。", "早上好呀，带着好心情出发吧。", "早上好呀，今天也要闪闪发光。"],
  ["中午好呀，忙碌了一上午，记得好好吃饭。", "中午好呀，歇口气，下午继续冲。", "中午好呀，吃饱了才有力气改变世界。"],
  ["下午好呀，午后时光，稳稳推进就好。", "下午好呀，离目标又近了一步，继续加油。", "下午好呀，来杯咖啡，把剩下的交给我。"],
  ["晚上好呀，忙了一天辛苦了，放轻松。", "晚上好呀，今晚就别太操劳啦，剩下的交给我。", "晚上好呀，愿今晚的效率与好心情同在。"],
];

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

function cacheHitRate(usage?: ChatUsage): number | null {
  if (!usage) {
    return null;
  }
  const cacheRead = usage.cache_read_input_tokens ?? 0;
  const cacheCreation = usage.cache_creation_input_tokens ?? 0;
  const input = usage.input_tokens ?? 0;
  const cacheableInput = input + cacheRead + cacheCreation;
  return cacheableInput > 0 ? cacheRead / cacheableInput : null;
}

function formatCacheHitRate(usage?: ChatUsage): string {
  const rate = cacheHitRate(usage);
  return rate === null ? "—" : `${Math.round(rate * 100)}%`;
}

function stopReasonLabel(reason?: string | null): string {
  const labels: Record<string, string> = {
    end_turn: "正常完成",
    interrupted: "用户停止",
    max_tokens: "达到输出上限",
    success: "正常完成",
  };
  return reason ? (labels[reason] ?? reason) : "—";
}

function ResponseUsageDetails({ usage }: { usage: ChatUsage }) {
  const input = usage.input_tokens ?? 0;
  const output = usage.output_tokens ?? 0;
  const cacheRead = usage.cache_read_input_tokens ?? 0;
  const cacheCreation = usage.cache_creation_input_tokens ?? 0;
  const total = input + output + cacheRead + cacheCreation;
  return (
    <div className="response-usage-card">
      <div className="response-usage-title">
        <strong>本次响应</strong>
      </div>
      <dl className="response-usage-grid">
        <div><dt>输入 Token</dt><dd>{formatTokenCount(input)}</dd></div>
        <div><dt>输出 Token</dt><dd>{formatTokenCount(output)}</dd></div>
        <div><dt>缓存读取</dt><dd>{formatTokenCount(cacheRead)}</dd></div>
        <div><dt>缓存创建</dt><dd>{formatTokenCount(cacheCreation)}</dd></div>
        <div><dt>缓存命中率</dt><dd>{formatCacheHitRate(usage)}</dd></div>
        <div><dt>总 Token</dt><dd>{formatTokenCount(total)}</dd></div>
        <div className="response-usage-wide">
          <dt>模型</dt><dd title={usage.model ?? undefined}>{usage.model ?? "—"}</dd>
        </div>
        <div className="response-usage-wide">
          <dt>停止原因</dt><dd>{stopReasonLabel(usage.stop_reason)}</dd>
        </div>
      </dl>
    </div>
  );
}

function SubagentUsageDetails({ usage }: { usage: SubagentUsage }) {
  return (
    <div className="response-usage-card">
      <div className="response-usage-title">
        <strong>子智能体消耗</strong>
      </div>
      <dl className="response-usage-grid">
        <div><dt>子智能体</dt><dd>{usage.count}</dd></div>
        <div><dt>总 Token</dt><dd>{formatTokenCount(usage.total_tokens)}</dd></div>
      </dl>
    </div>
  );
}

function copyWithFallback(content: string): void {
  const textArea = document.createElement("textarea");
  textArea.value = content;
  textArea.style.position = "fixed";
  textArea.style.opacity = "0";
  document.body.appendChild(textArea);
  textArea.select();
  document.execCommand("copy");
  textArea.remove();
}

function getGreeting(hour: number): string {
  const period = hour < 6 ? 0 : hour < 8 ? 1 : hour < 11 ? 2 : hour < 13 ? 3 : hour < 18 ? 4 : 5;
  const options = greetingsByPeriod[period];
  return options[Math.floor(Math.random() * options.length)];
}

function buildPrompt(text: string, attachmentPaths: string[]): string {
  const parts = [text];
  if (attachmentPaths.length) {
    const bullets = attachmentPaths.map((path, index) => `${index + 1}. @${path}`).join("\n");
    parts.push(`attachments:\n${bullets}`);
  }
  return parts.filter(Boolean).join("\n\n");
}

function fileToBase64(file: File): Promise<string> {
  return file.arrayBuffer().then((buffer) => {
    const bytes = new Uint8Array(buffer);
    // 分块转换，避免超大文件一次性展开导致调用栈溢出。
    let binary = "";
    const chunkSize = 0x8000;
    for (let offset = 0; offset < bytes.length; offset += chunkSize) {
      binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
    }
    return btoa(binary);
  });
}

async function uploadAttachments(
  attachments: ComposerAttachment[],
): Promise<string[]> {
  const paths: string[] = [];
  for (const attachment of attachments) {
    if (!attachment.file) {
      continue;
    }
    const data = await fileToBase64(attachment.file);
    const saved = await saveAttachment(attachment.name, data);
    paths.push(saved.path);
  }
  return paths;
}

function errorText(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message.replace(/^Error:\s*/i, "");
  }
  return "发送失败，请检查模型配置后重试。";
}

type WorkspaceProps = {
  effort: number;
  focusMessageKey?: string | null;
  hidden?: boolean;
  initialSessionId?: string | null;
  modelsRevision: number;
  onEffortChange: (value: number) => void;
  onConversationStart?: (project: ProjectFolder | null, sessionId: string) => void;
  onPermissionModeChange: (mode: ChatPermissionMode, sessionId: string) => void;
  onPermissionModeObserved: (mode: ChatPermissionMode) => void;
  onProjectChange: Dispatch<SetStateAction<ProjectFolder | null>>;
  onSessionsChanged?: () => void;
  permissionMode: ChatPermissionMode;
  selectedProject: ProjectFolder | null;
};

export function Workspace({
  effort,
  focusMessageKey = null,
  hidden = false,
  initialSessionId = null,
  modelsRevision,
  onEffortChange,
  onConversationStart,
  onPermissionModeChange,
  onPermissionModeObserved,
  onProjectChange,
  onSessionsChanged,
  permissionMode,
  selectedProject,
}: WorkspaceProps) {
  const { message: messageApi } = AntdApp.useApp();
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [historyLoading, setHistoryLoading] = useState(Boolean(initialSessionId));
  const [busy, setBusy] = useState(false);
  const [restoringFiles, setRestoringFiles] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [permissionRequests, setPermissionRequests] = useState<ChatPermissionRequestEvent[]>([]);
  const [quote] = useState(pickQuote);
  const [greeting] = useState(() => getGreeting(new Date().getHours()));
  const sessionIdRef = useRef(initialSessionId ?? crypto.randomUUID());
  const activeAssistantKeyRef = useRef<string | null>(null);
  const activeSubmissionRef = useRef<string | null>(null);
  const closedTurnsRef = useRef(new Set<string>());
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const processedEventIdsRef = useRef(new Set<string>());
  const historyLoadingRef = useRef(Boolean(initialSessionId));
  const messageNumberRef = useRef(0);
  const queuedEventsRef = useRef<ChatRenderEvent[]>([]);
  const startedAtRef = useRef<number | null>(null);
  const stopRequestedRef = useRef(false);
  const copyFeedbackTimerRef = useRef<number | null>(null);
  const [copiedMessageKey, setCopiedMessageKey] = useState<string | null>(null);
  const [modelSelection, setModelSelection] = useState<ModelSelection | null>(null);
  // 搜索跳转目标：后端消息 key 对应前端气泡 key（history- 前缀），命中一次后清空
  const focusBubbleKeyRef = useRef(focusMessageKey);
  useEffect(() => { focusBubbleKeyRef.current = focusMessageKey; }, [focusMessageKey]);
  const conversationStarted = Boolean(initialSessionId) || messages.length > 0;
  const tokenUsage = useMemo<TokenUsageSummary>(() => {
    const summary = messages.reduce<TokenUsageSummary>((current, message) => {
      const usage = message.usage;
      if (!usage) {
        return current;
      }
      const inputTokens = usage.input_tokens ?? 0;
      const outputTokens = usage.output_tokens ?? 0;
      const subagentTokens = usage.subagent_usage?.total_tokens ?? 0;
      return {
        inputTokens: current.inputTokens + inputTokens,
        outputTokens: current.outputTokens + outputTokens,
        subagentTokens: current.subagentTokens + subagentTokens,
        totalTokens: current.totalTokens
          + inputTokens
          + outputTokens
          + subagentTokens,
      };
    }, {
      inputTokens: 0,
      outputTokens: 0,
      subagentTokens: 0,
      totalTokens: 0,
    });
    return summary;
  }, [messages]);

  const applyLiveEvent = useCallback((event: ChatRenderEvent) => {
    if (processedEventIdsRef.current.has(event.id)) return;
    processedEventIdsRef.current.add(event.id);
    if (event.session_id) sessionIdRef.current = event.session_id;
    const compactionText = contextCompactionText(event);
    if (compactionText) {
      void messageApi.info({ content: compactionText, duration: 3, key: "context-compaction" });
      return;
    }
    if (isPermissionRequestEvent(event)) {
      if (closedTurnsRef.current.has(event.turn_id)) return;
      setPermissionRequests((current) => current.some((item) => item.data.request_id === event.data.request_id)
        ? current : [...current, event]);
      return;
    }
    if (event.event === "permission.resolved") {
      setPermissionRequests((current) => current.filter((item) => item.data.request_id !== event.data.request_id));
      return;
    }
    if (event.event === "permission.mode.changed") {
      const mode = event.data.mode;
      if (mode === "default" || mode === "acceptEdits" || mode === "plan" || mode === "auto" || mode === "bypassPermissions") {
        onPermissionModeObserved(mode);
      }
      return;
    }
    if (!isConversationEvent(event)) return;
    const assistantKey = turnAssistantKey(event.turn_id);
    setMessages((current) => reduceConversationEvent(current, event));
    if (event.event.startsWith("files.")) return;
    if (event.event === "turn.completed" || event.event === "turn.failed") {
      closedTurnsRef.current.add(event.turn_id);
      setPermissionRequests((current) => current.filter((item) => item.turn_id !== event.turn_id));
      if (activeAssistantKeyRef.current === assistantKey) {
        activeSubmissionRef.current = null;
        setBusy(false);
        setStopping(false);
      }
      onSessionsChanged?.();
    } else if (!closedTurnsRef.current.has(event.turn_id)) {
      activeAssistantKeyRef.current = assistantKey;
      if (event.event === "turn.started") {
        startedAtRef.current = eventTime(event);
        onSessionsChanged?.();
      }
      setBusy(true);
    }
  }, [messageApi, onPermissionModeObserved, onSessionsChanged]);

  useEffect(() => subscribeChatEvents(sessionIdRef.current, (event) => {
    if (historyLoadingRef.current) {
      queuedEventsRef.current.push(event);
      return;
    }
    applyLiveEvent(event);
  }, (snapshot) => {
    setBusy(snapshot?.running ?? false);
    setStopping(false);
    setPermissionRequests(pendingPermissionsFromEvents(snapshot?.events ?? []));
    if (!snapshot?.running) activeSubmissionRef.current = null;
    if (snapshot?.running) {
      setMessages((current) => current.map((item) => (
        item.key === activeAssistantKeyRef.current
          ? { ...item, loading: true, status: undefined }
          : item
      )));
    } else if (!snapshot) {
      setMessages((current) => current.map((item) => (
        item.key === activeAssistantKeyRef.current && item.loading
          ? { ...item, loading: false, status: "error", content: item.content || "连接已恢复，请重新发送此消息。" }
          : item
      )));
    }
  }), [applyLiveEvent]);

  useEffect(() => {
    let active = true;
    void getHomeFolder().then((folder) => {
      if (active && folder) {
        // 仅在还没选过项目时填默认目录，保持新建任务时工作区和当前一致
        onProjectChange((current) => current ?? folder);
      }
    });
    return () => {
      active = false;
    };
  }, [onProjectChange]);

  useEffect(() => {
    if (!initialSessionId) {
      return undefined;
    }

    let active = true;
    historyLoadingRef.current = true;
    setHistoryLoading(true);
    void Promise.all([
      getChatSession(
        initialSessionId,
        selectedProject?.path ?? null,
        effortValues[effort] ?? "high",
        permissionMode,
      ),
      getActiveChat(initialSessionId, true),
    ])
      .then(([history, activeChat]) => {
        if (!active) {
          return;
        }
        sessionIdRef.current = history.session_id;
        if (history.permission_mode) {
          onPermissionModeObserved(history.permission_mode);
        }
        if (history.model) {
          setModelSelection(history.model);
        } else {
          setModelSelection(null);
        }
        if (history.effort) {
          const restoredEffort = effortValues.indexOf(history.effort);
          if (restoredEffort >= 0) {
            onEffortChange(restoredEffort);
          }
        }
        const activeEvents = activeChat?.events ?? [];
        const activeTurnIds = new Set(activeEvents.filter((event) => !event.event.startsWith("files.")).map((event) => event.turn_id));
        const events = [
          ...history.events.filter((event) => !activeTurnIds.has(event.turn_id)),
          ...activeEvents,
        ];
        processedEventIdsRef.current = new Set(events.map((event) => event.id));
        const historyMessages = conversationFromEvents(events);
        messageNumberRef.current = historyMessages.filter(
          (message) => message.role === "user",
        ).length;
        setMessages(historyMessages);
        const permissions = pendingPermissionsFromEvents(activeEvents);
        closedTurnsRef.current = new Set(events.filter((event) => event.event === "turn.completed" || event.event === "turn.failed").map((event) => event.turn_id));
        for (const id of activeChat?.covered_event_ids ?? []) processedEventIdsRef.current.add(id);
        setPermissionRequests(permissions);
        setBusy(activeChat?.running ?? false);
        if (activeChat?.running) {
          const lastEvent = activeEvents.at(-1);
          if (lastEvent) {
            activeAssistantKeyRef.current = turnAssistantKey(lastEvent.turn_id);
          }
          const started = activeEvents.find((event) => event.event === "turn.started");
          startedAtRef.current = started ? eventTime(started) : Date.now();
        } else {
          startedAtRef.current = null;
        }
        if (history.cwd) {
          const segments = history.cwd.split(/[\\/]/).filter(Boolean);
          onProjectChange({
            name: segments.at(-1) ?? history.cwd,
            path: history.cwd,
          });
        }
        historyLoadingRef.current = false;
        const queuedEvents = queuedEventsRef.current;
        queuedEventsRef.current = [];
        for (const event of queuedEvents) {
          applyLiveEvent(event);
        }
      })
      .catch((error: unknown) => {
        if (!active) {
          return;
        }
        setMessages([{
          content: errorText(error),
          key: "history-load-error",
          role: "ai",
          status: "error",
        }]);
        historyLoadingRef.current = false;
        queuedEventsRef.current = [];
      })
      .finally(() => {
        if (active) {
          setHistoryLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [applyLiveEvent, initialSessionId, onPermissionModeObserved, onProjectChange]);

  useEffect(() => {
    if (!busy) {
      setElapsedSeconds(0);
      return;
    }
    const updateElapsed = () => {
      const startedAt = startedAtRef.current ?? Date.now();
      startedAtRef.current = startedAt;
      setElapsedSeconds(Math.max(1, Math.floor((Date.now() - startedAt) / 1000)));
    };
    updateElapsed();
    const timer = window.setInterval(() => {
      updateElapsed();
    }, 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  useEffect(() => {
    if (!busy || permissionRequests.length > 0) {
      return;
    }
    const scrollBox = chatScrollRef.current;
    scrollBox?.scrollTo({ top: scrollBox.scrollHeight, behavior: "smooth" });
  }, [busy, messages, elapsedSeconds, permissionRequests]);

  // 搜索跳转：历史载入完成后，按序号数气泡，把命中气泡滚动置顶并短暂高亮
  useEffect(() => {
    const targetKey = focusBubbleKeyRef.current;
    if (!targetKey || historyLoading) {
      return undefined;
    }
    const index = messages.findIndex((item) => item.key === targetKey);
    if (index < 0) {
      return undefined;
    }
    focusBubbleKeyRef.current = null;
    const frame = requestAnimationFrame(() => {
      const target = chatScrollRef.current
        ?.querySelectorAll(".chat-bubbles .ant-bubble")
        .item(index);
      if (!(target instanceof HTMLElement)) {
        return;
      }
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      target.classList.add("search-jump-target");
      window.setTimeout(() => target.classList.remove("search-jump-target"), 2600);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [focusMessageKey, historyLoading, messages]);

  useEffect(() => () => {
    if (copyFeedbackTimerRef.current !== null) {
      window.clearTimeout(copyFeedbackTimerRef.current);
    }
  }, []);

  const handleCopy = async (messageKey: string, content: string) => {
    try {
      await navigator.clipboard.writeText(content);
    } catch {
      copyWithFallback(content);
    }
    setCopiedMessageKey(messageKey);
    if (copyFeedbackTimerRef.current !== null) {
      window.clearTimeout(copyFeedbackTimerRef.current);
    }
    copyFeedbackTimerRef.current = window.setTimeout(() => {
      setCopiedMessageKey((current) => current === messageKey ? null : current);
    }, 1_800);
  };

  const handlePermissionDecision = async (
    request: ChatPermissionRequestEvent,
    allowed: boolean,
    answers?: ChatPermissionAnswers,
    feedback?: string,
    executionMode?: ChatPlanExecutionMode,
  ) => {
    const resolved = await respondChatPermission(
      request.data.request_id,
      allowed,
      answers,
      feedback,
      executionMode,
    );
    if (!resolved) {
      throw new Error("权限请求已失效，请等待当前任务更新。");
    }
    setPermissionRequests((current) => current.filter(
      (item) => item.data.request_id !== request.data.request_id,
    ));
  };

  const handlePermissionModeChange = (mode: ChatPermissionMode) => {
    onPermissionModeChange(mode, sessionIdRef.current);
  };

  const handleSend = (draft: ComposerDraft) => {
    if (busy || restoringFiles) {
      return;
    }
    messageNumberRef.current += 1;
    const turnId = messageNumberRef.current;
    const userKey = `user-${turnId}`;
    const assistantKey = `assistant-${turnId}`;
    const startedAt = Date.now();
    activeAssistantKeyRef.current = assistantKey;
    activeSubmissionRef.current = assistantKey;
    startedAtRef.current = startedAt;
    stopRequestedRef.current = false;
    const startingNewConversation = !conversationStarted;
    const startConversation = () => {
      if (startingNewConversation) {
        onConversationStart?.(draft.project, sessionIdRef.current);
      }
      setMessages((current) => [
        ...current,
        {
          key: userKey,
          role: "user",
          content: draft.text,
          status: "success",
        },
        {
          key: assistantKey,
          role: "ai",
          content: "",
          expandedTraceItemKeys: [],
          loading: true,
          trace: [],
          traceExpanded: false,
          submissionKey: assistantKey,
          startedAt,
        },
      ]);
      setBusy(true);
    };
    const transitionDocument = document as Document & {
      startViewTransition?: (update: () => void) => {
        updateCallbackDone: Promise<void>;
      };
    };
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let conversationReady: Promise<void>;
    if (!conversationStarted && !reduceMotion && transitionDocument.startViewTransition) {
      const transition = transitionDocument.startViewTransition(() => {
        flushSync(startConversation);
      });
      conversationReady = transition.updateCallbackDone;
    } else {
      startConversation();
      conversationReady = Promise.resolve();
    }

    void conversationReady
      .then(() => uploadAttachments(draft.attachments))
      .then((attachmentPaths) => sendChatMessage(
        buildPrompt(draft.text, attachmentPaths), draft.project?.path ?? null,
        sessionIdRef.current, draft.effort, draft.permissionMode, draft.model,
      ))
      .then(async () => {
        // WebSocket owns completion. If HTTP arrives first, recover its exact
        // events instead of writing a second response or changing a later turn.
        if (activeSubmissionRef.current !== assistantKey) return;
        const snapshot = await getActiveChat(sessionIdRef.current, true);
        if (activeSubmissionRef.current !== assistantKey) return;
        snapshot?.events.forEach(applyLiveEvent);
      })
      .catch((error: unknown) => {
        if (error instanceof TransportDisconnectedError || activeSubmissionRef.current !== assistantKey) return;
        activeSubmissionRef.current = null;
        const stopped = stopRequestedRef.current;
        setMessages((current) => current.map((item) => item.submissionKey === assistantKey
          ? { ...item, content: stopped ? item.content : errorText(error), loading: false,
            status: stopped ? "abort" : "error",
            trace: finishAgentTrace(item.trace ?? [], stopped ? "success" : "error"),
            workingSeconds: Math.max(1, Math.round((Date.now() - startedAt) / 1000)) } : item));
        setBusy(false);
        setStopping(false);
      });
  };

  const handleStop = async () => {
    if (!busy || stopping || stopRequestedRef.current) {
      return;
    }
    stopRequestedRef.current = true;
    setStopping(true);
    try {
      await stopChatMessage(sessionIdRef.current);
      setPermissionRequests([]);
    } catch {
      stopRequestedRef.current = false;
      setStopping(false);
    }
  };

  const setTraceExpanded = (messageKey: string, expanded: boolean) => {
    setMessages((current) => current.map((message) => (
      message.key === messageKey ? { ...message, traceExpanded: expanded } : message
    )));
  };

  const setTraceItemExpanded = (
    messageKey: string,
    traceItemKey: string,
    expanded: boolean,
  ) => {
    setMessages((current) => current.map((message) => {
      if (message.key !== messageKey) {
        return message;
      }
      const expandedKeys = message.expandedTraceItemKeys ?? [];
      return {
        ...message,
        expandedTraceItemKeys: expanded
          ? expandedKeys.includes(traceItemKey)
            ? expandedKeys
            : [...expandedKeys, traceItemKey]
          : expandedKeys.filter((key) => key !== traceItemKey),
      };
    }));
  };

  const bubbleItems = messages.map((item) => {
    const traceItems = item.trace ?? [];
    const lastTraceItem = traceItems.at(-1);
    const streamingOutput = item.loading
      && lastTraceItem?.kind === "output"
      && lastTraceItem.key === item.finalOutputKey
      ? lastTraceItem
      : undefined;
    const externalOutputKey = item.loading ? streamingOutput?.key : item.finalOutputKey;
    const responseContent = item.loading && !streamingOutput ? undefined : item.content;

    return {
      key: item.key,
      role: item.role,
      status: item.status,
      streaming: item.role === "ai" && item.loading,
      footer: item.role === "user" ? (
        <div className="message-actions user-message-footer">
          <button
            aria-label="复制用户消息的 Markdown 原文"
            className={`message-action-button${
              copiedMessageKey === item.key ? " is-copied" : ""
            }`}
            type="button"
            onClick={() => void handleCopy(item.key, item.content)}
          >
            {copiedMessageKey === item.key ? <CheckOutlined /> : <CopyOutlined />}
            <span className="message-action-label">
              {copiedMessageKey === item.key ? "已复制" : "复制 Markdown"}
            </span>
          </button>
        </div>
      ) : item.role === "ai" && !item.loading && item.content ? (
        <div className="message-actions assistant-message-footer">
          <button
            aria-label="复制 AI 回复的 Markdown 原文"
            className={`message-action-button${
              copiedMessageKey === item.key ? " is-copied" : ""
            }`}
            type="button"
            onClick={() => void handleCopy(item.key, item.content)}
          >
            {copiedMessageKey === item.key ? <CheckOutlined /> : <CopyOutlined />}
            <span className="message-action-label">
              {copiedMessageKey === item.key ? "已复制" : "复制 Markdown"}
            </span>
          </button>
          {item.usage && (
            <Popover
              content={<ResponseUsageDetails usage={item.usage} />}
              mouseEnterDelay={0.12}
              placement="topLeft"
            >
              <button
                aria-label="查看本次 AI 响应用量"
                className={`message-action-button response-status-button response-status-${
                  item.status ?? "success"
                }`}
                type="button"
              >
                <BarChartOutlined />
                <span className="message-action-label">查看响应用量</span>
              </button>
            </Popover>
          )}
          {item.usage?.subagent_usage && item.usage.subagent_usage.count > 0 && (
            <Popover
              content={<SubagentUsageDetails usage={item.usage.subagent_usage} />}
              mouseEnterDelay={0.12}
              placement="topLeft"
            >
              <button
                aria-label="查看本次子智能体消耗"
                className="message-action-button subagent-usage-button"
                type="button"
              >
                <RobotOutlined />
                <span className="message-action-label">查看子智能体消耗</span>
              </button>
            </Popover>
          )}
        </div>
      ) : undefined,
      footerPlacement: item.role === "user" ? "outer-end" as const : "outer-start" as const,
      content: item.role === "ai" ? (
        <article className="assistant-turn">
          <AgentTrace
            elapsedSeconds={elapsedSeconds}
            expanded={Boolean(item.traceExpanded)}
            expandedItemKeys={item.expandedTraceItemKeys ?? []}
            externalOutputKey={externalOutputKey}
            externalOutputKeys={externalOutputKey ? item.finalOutputKeys : undefined}
            failed={item.status === "error"}
            items={traceItems}
            loading={Boolean(item.loading)}
            onExpandedChange={(expanded) => setTraceExpanded(item.key, expanded)}
            onItemExpandedChange={(traceItemKey, expanded) => (
              setTraceItemExpanded(item.key, traceItemKey, expanded)
            )}
            workingSeconds={item.workingSeconds}
          />
          {item.status === "error"
            ? <div className="chat-message-error">{item.content}</div>
            : (
                <>
                  {responseContent && (
                    <ChatMarkdown
                      content={responseContent}
                      streaming={Boolean(item.loading && streamingOutput?.status === "running")}
                    />
                  )}
                  {item.status === "abort" && (
                    <div className="chat-message-stopped">已停止生成</div>
                  )}
                </>
              )}
          {!item.loading && !!item.fileChanges?.length && (
            <TurnChanges
              files={item.fileChanges}
              checkpointId={item.checkpointId}
              filesRestoredAt={item.filesRestoredAt}
              disabled={busy || restoringFiles || historyLoading}
              projectPath={selectedProject?.path ?? null}
              sessionId={sessionIdRef.current}
              onRestored={applyLiveEvent}
              onRestoringChange={setRestoringFiles}
            />
          )}
        </article>
      ) : (
        <div className="user-message">
          <div className="chat-message-text">{item.content}</div>
        </div>
      ),
    };
  });

  return (
    <main
      aria-hidden={hidden}
      className={`workspace${conversationStarted ? " workspace-chat" : ""}`}
      hidden={hidden}
    >
      <div className="watermark" aria-hidden="true">X</div>
      <div className={conversationStarted ? "chat-layout" : "workspace-content"}>
        {!conversationStarted && (
          <div className="workspace-intro">
            <div className="eyebrow">XALLING · AI WORKSPACE</div>
            <h2>{greeting}</h2>
            <p className="subtitle">{quote}</p>
          </div>
        )}
        {conversationStarted && (
          <div ref={chatScrollRef} className="chat-scroll">
            <div className="chat-column">
              {historyLoading && !messages.length && (
                <div className="history-loading">正在载入历史会话…</div>
              )}
              <Bubble.List
                autoScroll={false}
                className="chat-bubbles"
                items={bubbleItems}
                role={{
                  user: { className: "user-bubble", placement: "end", variant: "outlined" },
                  ai: { className: "assistant-bubble", placement: "start", variant: "borderless" },
                }}
              />
            </div>
          </div>
        )}
        <div className={`composer-stage ${
          conversationStarted ? "chat-composer-column" : "welcome-composer-column"
        }`}>
          <TaskComposer
            busy={busy}
            fileRestoring={restoringFiles}
            conversationStarted={conversationStarted}
            effort={effort}
            modelsRevision={modelsRevision}
            modelSelection={modelSelection}
            onEffortChange={onEffortChange}
            onPermissionDecision={handlePermissionDecision}
            onPermissionModeChange={handlePermissionModeChange}
            onProjectChange={onProjectChange}
            onSend={handleSend}
            onStop={() => void handleStop()}
            permissionMode={permissionMode}
            permissionRequest={permissionRequests[0] ?? null}
            selectedProject={selectedProject}
            sessionId={sessionIdRef.current}
            stopping={stopping}
            tokenUsage={tokenUsage}
          />
        </div>
      </div>
    </main>
  );
}
