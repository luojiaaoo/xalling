import {
  BarChartOutlined,
  CheckOutlined,
  CopyOutlined,
  PaperClipOutlined,
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
  respondChatPermission,
  sendChatMessage,
  stopChatMessage,
  subscribeChatEvents,
  type ChatPermissionAnswers,
  type ChatPermissionMode,
  type ChatPermissionRequestEvent,
  type ChatStreamEvent,
  type ChatUsage,
  type ProjectFolder,
} from "../bridge/client";
import { pickQuote } from "../quotes";
import {
  AgentTrace,
  applyChatStreamEvent,
  finishAgentTrace,
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

function stopReasonLabel(reason?: string): string {
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
          <dt>模型</dt><dd title={usage.model_name ?? undefined}>{usage.model_name ?? "—"}</dd>
        </div>
        <div className="response-usage-wide">
          <dt>停止原因</dt><dd>{stopReasonLabel(usage.stop_reason)}</dd>
        </div>
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

function exitPlanText(event: ChatPermissionRequestEvent): string | null {
  if (event.tool_name !== "ExitPlanMode") {
    return null;
  }
  const plan = event.input.plan;
  return typeof plan === "string" && plan.trim() ? plan.trim() : null;
}

function applyExitPlanToAssistant(
  message: ConversationMessage,
  event: ChatPermissionRequestEvent,
): ConversationMessage {
  const plan = exitPlanText(event);
  if (!plan) {
    return message;
  }
  const blockId = `exit-plan-${event.permission_id}`;
  let trace = message.trace ?? [];
  if (!trace.some((item) => item.key === blockId)) {
    const metadata = {
      block_id: blockId,
      timestamp: Date.now(),
    };
    trace = applyChatStreamEvent(trace, { ...metadata, type: "output_start" });
    trace = applyChatStreamEvent(trace, { ...metadata, type: "output_delta", text: plan });
    trace = applyChatStreamEvent(trace, { ...metadata, type: "output_complete" });
  }
  return {
    ...message,
    content: message.content.includes(plan)
      ? message.content
      : message.content
        ? `${message.content}\n\n${plan}`
        : plan,
    trace,
  };
}

function applyEventToAssistant(
  message: ConversationMessage,
  event: ChatStreamEvent,
): ConversationMessage {
  const trace = message.trace ?? [];
  const isTopLevelEvent = event.parent_tool_id === undefined;
  const startsNewOutput = (
    event.type === "output_start" || event.type === "output_delta"
  ) && isTopLevelEvent
    && !trace.some((traceItem) => traceItem.key === event.block_id);
  const separator = startsNewOutput && message.content ? "\n\n" : "";
  const content = event.type === "output_delta" && isTopLevelEvent
    ? `${message.content}${separator}${event.text}`
    : `${message.content}${separator}`;
  return {
    ...message,
    content,
    loading: true,
    trace: applyChatStreamEvent(trace, event),
  };
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
  const eventIndexRef = useRef(-1);
  const historyLoadingRef = useRef(Boolean(initialSessionId));
  const messageNumberRef = useRef(0);
  const queuedEventsRef = useRef<ChatStreamEvent[]>([]);
  const startedAtRef = useRef<number | null>(null);
  const stopRequestedRef = useRef(false);
  const planScrollPendingRef = useRef(false);
  const copyFeedbackTimerRef = useRef<number | null>(null);
  const [copiedMessageKey, setCopiedMessageKey] = useState<string | null>(null);
  // 搜索跳转目标：后端消息 key 对应前端气泡 key（history- 前缀），命中一次后清空
  const focusBubbleKeyRef = useRef(focusMessageKey ? `history-${focusMessageKey}` : null);
  const conversationStarted = Boolean(initialSessionId) || messages.length > 0;

  const applyLiveEvent = useCallback((event: ChatStreamEvent) => {
    if (
      event.event_index !== undefined
      && event.event_index <= eventIndexRef.current
    ) {
      return;
    }
    if (event.event_index !== undefined) {
      eventIndexRef.current = event.event_index;
    }
    if (event.type === "permission_request") {
      setPermissionRequests((current) => (
        current.some((item) => item.permission_id === event.permission_id)
          ? current
          : [...current, event]
      ));
      const plan = exitPlanText(event);
      if (plan) {
        planScrollPendingRef.current = true;
        setBusy(true);
        setMessages((current) => {
          let assistantKey = activeAssistantKeyRef.current;
          let next = current;
          if (!assistantKey || !current.some((item) => item.key === assistantKey)) {
            assistantKey = `active-${sessionIdRef.current}`;
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
            item.key === assistantKey ? applyExitPlanToAssistant(item, event) : item
          ));
        });
      }
      return;
    }
    if (event.type === "session_started") {
      sessionIdRef.current = event.session_id;
      startedAtRef.current = event.timestamp ?? Date.now();
      onSessionsChanged?.();
      return;
    }
    if (event.type === "chat_complete") {
      const reply = event.reply;
      sessionIdRef.current = reply.session_id;
      const stopped = Boolean(reply.stopped || stopRequestedRef.current);
      const workingSeconds = startedAtRef.current === null
        ? undefined
        : Math.max(
            1,
            Math.round(((event.timestamp ?? Date.now()) - startedAtRef.current) / 1000),
          );
      setMessages((current) => current.map((item) => (
        item.key === activeAssistantKeyRef.current
          ? {
              ...item,
              content: stopped ? (reply.content || item.content) : reply.content,
              finalOutputKey: reply.final_output_block_id ?? undefined,
              loading: false,
              status: stopped ? "abort" : "success",
              trace: finishAgentTrace(item.trace ?? [], "success", event.timestamp),
              usage: reply.usage,
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
    if (event.type === "chat_error") {
      setMessages((current) => current.map((item) => (
        item.key === activeAssistantKeyRef.current
          ? {
              ...item,
              content: event.message || item.content,
              loading: false,
              status: "error",
              trace: finishAgentTrace(item.trace ?? [], "error", event.timestamp),
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
      let assistantKey = activeAssistantKeyRef.current;
      let next = current;
      if (!assistantKey || !current.some((item) => item.key === assistantKey)) {
        assistantKey = `active-${sessionIdRef.current}`;
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
        messageNumberRef.current = history.messages.filter(
          (message) => message.role === "user",
        ).length;
        let historyMessages: ConversationMessage[] = history.messages.map((message) => {
          if (message.role === "user") {
            return {
              content: message.content,
              key: `history-${message.key}`,
              role: "user",
              status: "success",
            };
          }
          const trace = message.trace_events.reduce<AgentTraceItem[]>(
            (items, event) => applyChatStreamEvent(items, event),
            [],
          );
          return {
            content: message.content,
            expandedTraceItemKeys: [],
            finalOutputKey: message.final_output_block_id ?? undefined,
            key: `history-${message.key}`,
            role: "ai",
            status: "success",
            trace: finishAgentTrace(trace, "success"),
            traceExpanded: false,
            usage: message.usage,
          };
        });
        if (activeChat) {
          const assistantKey = `active-${activeChat.session_id}`;
          activeAssistantKeyRef.current = assistantKey;
          let assistant: ConversationMessage = {
            content: "",
            expandedTraceItemKeys: [],
            key: assistantKey,
            loading: true,
            role: "ai",
            trace: [],
            traceExpanded: false,
          };
          const permissions: ChatPermissionRequestEvent[] = [];
          let running = true;
          for (const event of activeChat.events) {
            if (event.event_index !== undefined) {
              eventIndexRef.current = Math.max(
                eventIndexRef.current,
                event.event_index,
              );
            }
            if (event.type === "permission_request") {
              permissions.push(event);
              const plan = exitPlanText(event);
              if (plan) {
                planScrollPendingRef.current = true;
                assistant = applyExitPlanToAssistant(assistant, event);
              }
            } else if (event.type === "session_started") {
              sessionIdRef.current = event.session_id;
              startedAtRef.current = event.timestamp ?? Date.now();
            } else if (event.type === "chat_complete") {
              const stopped = Boolean(event.reply.stopped);
              assistant = {
                ...assistant,
                content: event.reply.content || assistant.content,
                finalOutputKey: event.reply.final_output_block_id ?? undefined,
                loading: false,
                status: stopped ? "abort" : "success",
                trace: finishAgentTrace(
                  assistant.trace ?? [],
                  "success",
                  event.timestamp,
                ),
                usage: event.reply.usage,
              };
              running = false;
            } else if (event.type === "chat_error") {
              assistant = {
                ...assistant,
                content: event.message || assistant.content,
                loading: false,
                status: "error",
                trace: finishAgentTrace(
                  assistant.trace ?? [],
                  "error",
                  event.timestamp,
                ),
              };
              running = false;
            } else {
              assistant = applyEventToAssistant(assistant, event);
            }
          }
          let lastUserIndex = -1;
          for (let index = historyMessages.length - 1; index >= 0; index -= 1) {
            if (historyMessages[index].role === "user") {
              lastUserIndex = index;
              break;
            }
          }
          historyMessages = [
            ...historyMessages.slice(0, lastUserIndex + 1),
            assistant,
          ];
          setPermissionRequests(permissions);
          setBusy(running);
          if (!running) {
            startedAtRef.current = null;
          }
        }
        setMessages(historyMessages);
        if (history.project_path) {
          onProjectChange({
            name: history.project_name,
            path: history.project_path,
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

  useEffect(() => {
    if (!planScrollPendingRef.current) {
      return undefined;
    }
    const frame = requestAnimationFrame(() => {
      const plans = chatScrollRef.current?.querySelectorAll(".assistant-plan-output");
      const target = plans?.item((plans?.length ?? 0) - 1);
      if (!(target instanceof HTMLElement)) {
        return;
      }
      planScrollPendingRef.current = false;
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [messages]);

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
  ) => {
    const resolved = await respondChatPermission(
      request.permission_id,
      allowed,
      answers,
      feedback,
    );
    if (!resolved) {
      throw new Error("权限请求已失效，请等待当前任务更新。");
    }
    if (allowed && request.tool_name === "ExitPlanMode") {
      onPermissionModeChange(request.suggested_permission_mode ?? "default");
    }
    setPermissionRequests((current) => current.filter(
      (item) => item.permission_id !== request.permission_id,
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
        const stopped = Boolean(reply.stopped || stopRequestedRef.current);
        setMessages((current) => current.map((item) => (
          item.key === assistantKey
            ? {
                ...item,
                content: stopped ? (reply.content || item.content) : reply.content,
                finalOutputKey: reply.final_output_block_id ?? undefined,
                loading: false,
                status: stopped ? "abort" : "success",
                trace: finishAgentTrace(item.trace ?? [], "success"),
                usage: reply.usage,
                workingSeconds: Math.max(1, Math.round((Date.now() - startedAt) / 1000)),
              }
            : item
        )));
        onSessionsChanged?.();
      })
      .catch((error: unknown) => {
        const stopped = stopRequestedRef.current;
        setMessages((current) => current.map((item) => (
          item.key === assistantKey
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

  const sessionStats = messages.reduce<{
    agentSteps: number;
    inputTokens: number;
    latestUsage?: ChatUsage;
    outputTokens: number;
    toolCalls: number;
    toolFailures: number;
    toolSuccesses: number;
    turns: number;
  }>((stats, item) => {
    if (item.role === "user") {
      stats.turns += 1;
      return stats;
    }
    if (item.usage) {
      stats.inputTokens += item.usage.input_tokens ?? 0;
      stats.outputTokens += item.usage.output_tokens ?? 0;
      stats.agentSteps += item.usage.num_turns ?? 1;
      stats.latestUsage = item.usage;
    } else if (!item.loading) {
      stats.agentSteps += 1;
    }
    for (const traceItem of item.trace ?? []) {
      if (traceItem.kind !== "tools") {
        continue;
      }
      stats.toolCalls += traceItem.calls.length;
      stats.toolSuccesses += traceItem.calls.filter(
        (call) => call.status === "success",
      ).length;
      stats.toolFailures += traceItem.calls.filter(
        (call) => call.status === "error",
      ).length;
    }
    return stats;
  }, {
    agentSteps: 0,
    inputTokens: 0,
    outputTokens: 0,
    toolCalls: 0,
    toolFailures: 0,
    toolSuccesses: 0,
    turns: 0,
  });

  const bubbleItems = messages.map((item) => {
    const traceItems = item.trace ?? [];
    const lastTraceItem = traceItems.at(-1);
    const streamingOutput = item.loading && lastTraceItem?.kind === "output"
      ? lastTraceItem
      : undefined;
    const showingPlan = streamingOutput?.key.startsWith("exit-plan-") ?? false;
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
                    showingPlan ? (
                      <div className="assistant-plan-output">
                        <ChatMarkdown content={responseContent} streaming={false} />
                      </div>
                    ) : (
                      <ChatMarkdown
                        content={responseContent}
                        streaming={Boolean(item.loading && streamingOutput?.status === "running")}
                      />
                    )
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
          {conversationStarted && (
            <div className="conversation-stats" aria-label="当前会话统计">
              <span><strong>{sessionStats.turns}</strong>轮对话</span>
              <span>AI 调用<strong>{sessionStats.agentSteps}</strong>步</span>
              <span>缓存命中率<strong>{formatCacheHitRate(sessionStats.latestUsage)}</strong></span>
              <span>词元 · 输入<strong>{formatTokenCount(sessionStats.inputTokens)}</strong> · 输出<strong>{formatTokenCount(sessionStats.outputTokens)}</strong> · 总<strong>{formatTokenCount(sessionStats.inputTokens + sessionStats.outputTokens)}</strong></span>
              <span>工具<strong>{sessionStats.toolCalls}</strong>次 · <em className="stat-success">成功{sessionStats.toolSuccesses}</em>/<em className="stat-failure">失败{sessionStats.toolFailures}</em></span>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
