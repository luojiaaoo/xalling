import {
  BarChartOutlined,
  CheckOutlined,
  CopyOutlined,
  PaperClipOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import { Bubble } from "@ant-design/x";
import { Popover } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { flushSync } from "react-dom";

import {
  getActiveChat,
  getChatSession,
  getHomeFolder,
  isPermissionRequestEvent,
  respondChatPermission,
  sendChatMessage,
  stopChatMessage,
  subscribeChatEvents,
  type ChatPermissionAnswers,
  type ChatPermissionMode,
  type ChatPlanExecutionMode,
  type ChatPermissionRequestEvent,
  type ChatRenderEvent,
  type ChatUsage,
  type ProjectFolder,
  type SubagentUsage,
} from "../bridge/client";
import { pickQuote } from "../quotes";
import {
  AgentTrace,
  applyRenderEvent,
  finishAgentTrace,
  stripExitPlanContent,
  type AgentTraceItem,
} from "./AgentTrace";
import { ChatMarkdown } from "./ChatMarkdown";
import {
  TaskComposer,
  type ComposerAttachment,
  type ComposerDraft,
} from "./TaskComposer";

const greetingsByPeriod: string[][] = [
  ["凌晨好呀，夜深了，别太拼，慢慢来。", "凌晨好呀，这么晚还醒着，辛苦了，剩下的交给我。", "凌晨好呀，安静的深夜适合专注，但也记得照顾自己。"],
  ["早上好呀，这么早就开始啦，新的一天一起加油！", "早上好呀，清晨的你已经很棒了，今天会是好日子。", "早上好呀，早起的鸟儿有虫吃，我们一起加油！"],
  ["早上好呀，元气满满的上午，正适合开工。", "早上好呀，带着好心情出发吧。", "早上好呀，今天也要闪闪发光。"],
  ["中午好呀，忙碌了一上午，记得好好吃饭。", "中午好呀，歇口气，下午继续冲。", "中午好呀，吃饱了才有力气改变世界。"],
  ["下午好呀，午后时光，稳稳推进就好。", "下午好呀，离目标又近了一步，继续加油。", "下午好呀，来杯咖啡，把剩下的交给我。"],
  ["晚上好呀，忙了一天辛苦了，放轻松。", "晚上好呀，今晚就别太操劳啦，剩下的交给我。", "晚上好呀，愿今晚的效率与好心情同在。"],
];

type ConversationMessage = {
  attachments?: ComposerAttachment[];
  content: string;
  expandedTraceItemKeys?: string[];
  finalOutputKey?: string;
  key: string;
  loading?: boolean;
  role: "ai" | "user";
  status?: "abort" | "error" | "success";
  trace?: AgentTraceItem[];
  traceExpanded?: boolean;
  usage?: ChatUsage;
  workingSeconds?: number;
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

function requestPrompt(draft: ComposerDraft): string {
  const text = draft.text || "请处理这次附加的文件。";
  if (!draft.attachments.length) {
    return text;
  }
  const fileNames = draft.attachments.map((file) => file.name).join("、");
  return `${text}\n\n本次附加文件：${fileNames}。如果这些文件位于当前项目中，请读取后再处理。`;
}

function errorText(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message.replace(/^Error:\s*/i, "");
  }
  return "发送失败，请检查模型配置后重试。";
}

function applyEventToAssistant(
  message: ConversationMessage,
  event: ChatRenderEvent,
): ConversationMessage {
  const trace = message.trace ?? [];
  const isTopLevelEvent = event.parent_tool_use_id === null;
  const foldsCurrentOutput = isTopLevelEvent && (
    event.event === "turn.proxy.completed"
    || event.event === "user.proxy.message"
  );
  const currentContent = foldsCurrentOutput ? "" : message.content;
  const currentOutputKey = foldsCurrentOutput ? undefined : message.finalOutputKey;
  const isOutputEvent = event.event.startsWith("assistant.reply.")
    && typeof event.data.trace_id === "string";
  const traceId = typeof event.data.trace_id === "string" ? event.data.trace_id : event.id;
  const outputKey = `${traceId}:reply`;
  const startsNewOutput = (
    event.event === "assistant.reply.started"
    || event.event === "assistant.reply.delta"
  ) && isTopLevelEvent
    && !trace.some((traceItem) => traceItem.key === outputKey);
  const separator = startsNewOutput && currentContent ? "\n\n" : "";
  const delta = typeof event.data.text === "string" ? event.data.text : "";
  const nextContent = event.event === "assistant.reply.delta" && isTopLevelEvent
    ? `${currentContent}${separator}${delta}`
    : `${currentContent}${separator}`;
  const nextTrace = applyRenderEvent(trace, event);
  return {
    ...message,
    content: stripExitPlanContent(nextContent, nextTrace),
    finalOutputKey: isOutputEvent && isTopLevelEvent
      ? outputKey
      : currentOutputKey,
    loading: true,
    trace: nextTrace,
  };
}

function eventTime(event: ChatRenderEvent): number {
  const value = Date.parse(event.created_at);
  return Number.isFinite(value) ? value : Date.now();
}

function turnAssistantKey(turnId: string): string {
  return `turn-${turnId}-assistant`;
}

function turnUserKey(turnId: string): string {
  return `turn-${turnId}-user`;
}

function isStoppedUsage(usage: ChatUsage | undefined): boolean {
  return usage?.terminal_reason?.startsWith("aborted") === true
    || usage?.stop_reason === "interrupted";
}

function conversationFromEvents(events: ChatRenderEvent[]): ConversationMessage[] {
  const messages: ConversationMessage[] = [];
  for (const event of events) {
    const userKey = turnUserKey(event.turn_id);
    const assistantKey = turnAssistantKey(event.turn_id);
    if (event.event === "user.message") {
      const content = typeof event.data.content === "string" ? event.data.content : "";
      if (!messages.some((item) => item.key === userKey)) {
        messages.push({ content, key: userKey, role: "user", status: "success" });
      }
      continue;
    }
    if (
      event.event === "turn.started"
      || event.event === "permission.requested"
      || event.event === "permission.resolved"
    ) {
      continue;
    }

    let assistantIndex = messages.findIndex((item) => item.key === assistantKey);
    if (assistantIndex === -1) {
      messages.push({
        content: "",
        expandedTraceItemKeys: [],
        key: assistantKey,
        loading: true,
        role: "ai",
        trace: [],
        traceExpanded: false,
      });
      assistantIndex = messages.length - 1;
    }
    let assistant = messages[assistantIndex];
    if (event.event === "turn.completed") {
      const usage = event.data.usage as ChatUsage | undefined;
      const content = typeof event.data.content === "string"
        ? event.data.content
        : assistant.content;
      assistant = {
        ...assistant,
        content: content || assistant.content,
        loading: false,
        status: isStoppedUsage(usage) ? "abort" : event.data.is_error === true ? "error" : "success",
        trace: finishAgentTrace(
          assistant.trace ?? [],
          event.data.is_error === true ? "error" : "success",
          eventTime(event),
        ),
        usage,
      };
    } else if (event.event === "turn.failed") {
      assistant = {
        ...assistant,
        content: typeof event.data.message === "string"
          ? event.data.message
          : assistant.content,
        loading: false,
        status: "error",
        trace: finishAgentTrace(assistant.trace ?? [], "error", eventTime(event)),
      };
    } else {
      assistant = applyEventToAssistant(assistant, event);
    }
    messages[assistantIndex] = assistant;
  }
  return messages;
}

type WorkspaceProps = {
  effort: number;
  focusMessageKey?: string | null;
  hidden?: boolean;
  initialSessionId?: string | null;
  modelsRevision: number;
  onEffortChange: (value: number) => void;
  onConversationStart?: (project: ProjectFolder | null) => void;
  onPermissionModeChange: (mode: ChatPermissionMode) => void;
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
  onProjectChange,
  onSessionsChanged,
  permissionMode,
  selectedProject,
}: WorkspaceProps) {
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [historyLoading, setHistoryLoading] = useState(Boolean(initialSessionId));
  const [busy, setBusy] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [permissionRequests, setPermissionRequests] = useState<ChatPermissionRequestEvent[]>([]);
  const [quote] = useState(pickQuote);
  const [greeting] = useState(() => getGreeting(new Date().getHours()));
  const sessionIdRef = useRef(initialSessionId ?? crypto.randomUUID());
  const activeAssistantKeyRef = useRef<string | null>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const processedEventIdsRef = useRef(new Set<string>());
  const historyLoadingRef = useRef(Boolean(initialSessionId));
  const messageNumberRef = useRef(0);
  const queuedEventsRef = useRef<ChatRenderEvent[]>([]);
  const startedAtRef = useRef<number | null>(null);
  const stopRequestedRef = useRef(false);
  const copyFeedbackTimerRef = useRef<number | null>(null);
  const [copiedMessageKey, setCopiedMessageKey] = useState<string | null>(null);
  // 搜索跳转目标：后端消息 key 对应前端气泡 key（history- 前缀），命中一次后清空
  const focusBubbleKeyRef = useRef(focusMessageKey);
  const conversationStarted = Boolean(initialSessionId) || messages.length > 0;

  const applyLiveEvent = useCallback((event: ChatRenderEvent) => {
    if (processedEventIdsRef.current.has(event.id)) {
      return;
    }
    processedEventIdsRef.current.add(event.id);
    if (event.session_id) {
      sessionIdRef.current = event.session_id;
    }
    if (isPermissionRequestEvent(event)) {
      setPermissionRequests((current) => (
        current.some((item) => item.data.request_id === event.data.request_id)
          ? current
          : [...current, event]
      ));
      return;
    }
    if (event.event === "permission.resolved") {
      const requestId = event.data.request_id;
      setPermissionRequests((current) => current.filter(
        (item) => item.data.request_id !== requestId,
      ));
      return;
    }
    if (event.event === "turn.started") {
      const assistantKey = turnAssistantKey(event.turn_id);
      const previousKey = activeAssistantKeyRef.current;
      activeAssistantKeyRef.current = assistantKey;
      startedAtRef.current = eventTime(event);
      setMessages((current) => current.map((item) => (
        item.key === previousKey ? { ...item, key: assistantKey } : item
      )));
      onSessionsChanged?.();
      return;
    }
    if (event.event === "user.message") {
      const content = typeof event.data.content === "string" ? event.data.content : "";
      const userKey = turnUserKey(event.turn_id);
      setMessages((current) => {
        if (current.some((item) => item.key === userKey)) {
          return current;
        }
        let candidateIndex = -1;
        for (let index = current.length - 1; index >= 0; index -= 1) {
          if (current[index].role === "user" && current[index].key.startsWith("user-")) {
            candidateIndex = index;
            break;
          }
        }
        if (candidateIndex === -1) {
          return [...current, { content, key: userKey, role: "user", status: "success" }];
        }
        return current.map((item, index) => (
          index === candidateIndex ? { ...item, key: userKey } : item
        ));
      });
      return;
    }
    if (event.event === "turn.completed") {
      const usage = event.data.usage as ChatUsage | undefined;
      const stopped = isStoppedUsage(usage) || stopRequestedRef.current;
      const workingSeconds = startedAtRef.current === null
        ? undefined
        : Math.max(
            1,
            Math.round((eventTime(event) - startedAtRef.current) / 1000),
          );
      setMessages((current) => current.map((item) => (
        item.key === activeAssistantKeyRef.current
          ? {
              ...item,
              content: typeof event.data.content === "string"
                ? (event.data.content || item.content)
                : item.content,
              loading: false,
              status: stopped ? "abort" : event.data.is_error === true ? "error" : "success",
              trace: finishAgentTrace(
                item.trace ?? [],
                event.data.is_error === true ? "error" : "success",
                eventTime(event),
              ),
              usage,
              workingSeconds,
            }
          : item
      )));
      setBusy(false);
      setStopping(false);
      setPermissionRequests([]);
      onSessionsChanged?.();
      return;
    }
    if (event.event === "turn.failed") {
      setMessages((current) => current.map((item) => (
        item.key === activeAssistantKeyRef.current
          ? {
              ...item,
              content: typeof event.data.message === "string"
                ? event.data.message
                : item.content,
              loading: false,
              status: "error",
              trace: finishAgentTrace(item.trace ?? [], "error", eventTime(event)),
            }
          : item
      )));
      setBusy(false);
      setStopping(false);
      setPermissionRequests([]);
      return;
    }

    setBusy(true);
    setMessages((current) => {
      let assistantKey = turnAssistantKey(event.turn_id);
      let next = current;
      if (!current.some((item) => item.key === assistantKey)) {
        activeAssistantKeyRef.current = assistantKey;
        next = [
          ...current,
          {
            content: "",
            expandedTraceItemKeys: [],
            key: assistantKey,
            loading: true,
            role: "ai",
            trace: [],
            traceExpanded: false,
          },
        ];
      }
      return next.map((item) => (
        item.key === assistantKey ? applyEventToAssistant(item, event) : item
      ));
    });
  }, [onSessionsChanged]);

  useEffect(() => subscribeChatEvents(sessionIdRef.current, (event) => {
    if (historyLoadingRef.current) {
      queuedEventsRef.current.push(event);
      return;
    }
    applyLiveEvent(event);
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
      getChatSession(initialSessionId),
      getActiveChat(initialSessionId),
    ])
      .then(([history, activeChat]) => {
        if (!active) {
          return;
        }
        sessionIdRef.current = history.session_id;
        const activeEvents = activeChat?.events ?? [];
        const activeTurnIds = new Set(activeEvents.map((event) => event.turn_id));
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
        const permissions = activeEvents.filter(isPermissionRequestEvent);
        setPermissionRequests(permissions);
        setBusy(Boolean(activeChat));
        if (activeChat) {
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
  }, [applyLiveEvent, initialSessionId, onProjectChange]);

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
  }, [historyLoading, messages]);

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
    if (allowed && request.data.tool_name === "ExitPlanMode") {
      if (executionMode) {
        onPermissionModeChange(executionMode);
      } else {
        const suggestion = request.data.suggestions.find((item) => (
          item.type === "setMode"
          && (
            item.mode === "default"
            || item.mode === "acceptEdits"
            || item.mode === "auto"
            || item.mode === "bypassPermissions"
          )
        ));
        onPermissionModeChange(
          (suggestion?.mode as Exclude<ChatPermissionMode, "plan"> | undefined)
          ?? "default",
        );
      }
    }
    setPermissionRequests((current) => current.filter(
      (item) => item.data.request_id !== request.data.request_id,
    ));
  };

  const handleSend = (draft: ComposerDraft) => {
    if (busy) {
      return;
    }
    messageNumberRef.current += 1;
    const turnId = messageNumberRef.current;
    const userKey = `user-${turnId}`;
    const assistantKey = `assistant-${turnId}`;
    const startedAt = Date.now();
    activeAssistantKeyRef.current = assistantKey;
    startedAtRef.current = startedAt;
    stopRequestedRef.current = false;
    const startingNewConversation = !conversationStarted;
    const startConversation = () => {
      if (startingNewConversation) {
        onConversationStart?.(draft.project);
      }
      setMessages((current) => [
        ...current,
        {
          key: userKey,
          role: "user",
          content: draft.text || "已添加附件",
          attachments: draft.attachments,
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
      .then(() => sendChatMessage(
        requestPrompt(draft),
        draft.project?.path ?? null,
        sessionIdRef.current,
        draft.effort,
        draft.permissionMode,
      ))
      .then((reply) => {
        if (reply.session_id) {
          sessionIdRef.current = reply.session_id;
        }
        const stopped = isStoppedUsage(reply.usage) || stopRequestedRef.current;
        const resolvedAssistantKey = activeAssistantKeyRef.current ?? assistantKey;
        setMessages((current) => current.map((item) => (
          item.key === resolvedAssistantKey
            ? {
                ...item,
                content: stopped ? (reply.content || item.content) : reply.content,
                loading: false,
                status: stopped ? "abort" : reply.is_error ? "error" : "success",
                trace: finishAgentTrace(
                  item.trace ?? [],
                  reply.is_error ? "error" : "success",
                ),
                usage: reply.usage,
                workingSeconds: Math.max(1, Math.round((Date.now() - startedAt) / 1000)),
              }
            : item
        )));
        onSessionsChanged?.();
      })
      .catch((error: unknown) => {
        const stopped = stopRequestedRef.current;
        const resolvedAssistantKey = activeAssistantKeyRef.current ?? assistantKey;
        setMessages((current) => current.map((item) => (
          item.key === resolvedAssistantKey
            ? {
                ...item,
                content: stopped ? item.content : errorText(error),
                loading: false,
                status: stopped ? "abort" : "error",
                trace: finishAgentTrace(item.trace ?? [], stopped ? "success" : "error"),
                workingSeconds: Math.max(1, Math.round((Date.now() - startedAt) / 1000)),
              }
            : item
        )));
      })
      .finally(() => {
        setBusy(false);
        setStopping(false);
        setPermissionRequests([]);
        onSessionsChanged?.();
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
    const responseContent = item.loading ? streamingOutput?.content : item.content;

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
      ) : !item.loading && item.content ? (
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
        </article>
      ) : (
        <div className="user-message">
          <div className="chat-message-text">{item.content}</div>
          {!!item.attachments?.length && (
            <div className="chat-message-files">
              {item.attachments.map((file, index) => (
                <span key={`${file.name}-${index}`}><PaperClipOutlined />{file.name}</span>
              ))}
            </div>
          )}
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
            conversationStarted={conversationStarted}
            effort={effort}
            modelsRevision={modelsRevision}
            onEffortChange={onEffortChange}
            onPermissionDecision={handlePermissionDecision}
            onPermissionModeChange={onPermissionModeChange}
            onProjectChange={onProjectChange}
            onSend={handleSend}
            onStop={() => void handleStop()}
            permissionMode={permissionMode}
            permissionRequest={permissionRequests[0] ?? null}
            selectedProject={selectedProject}
            sessionId={sessionIdRef.current}
            stopping={stopping}
          />
        </div>
      </div>
    </main>
  );
}
