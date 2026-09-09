import { PaperClipOutlined } from "@ant-design/icons";
import { Bubble } from "@ant-design/x";
import { useEffect, useRef, useState } from "react";

import { getHomeFolder, sendChatMessage, type ProjectFolder } from "../bridge/client";
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
  status?: "error" | "success";
  trace?: AgentTraceItem[];
  traceExpanded?: boolean;
  workingSeconds?: number;
};

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

export function Workspace() {
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [selectedProject, setSelectedProject] = useState<ProjectFolder | null>(null);
  const [quote] = useState(pickQuote);
  const [greeting] = useState(() => getGreeting(new Date().getHours()));
  const sessionIdRef = useRef<string | null>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const messageNumberRef = useRef(0);
  const conversationStarted = messages.length > 0;

  useEffect(() => {
    let active = true;
    void getHomeFolder().then((folder) => {
      if (active && folder) {
        setSelectedProject((current) => current ?? folder);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!busy) {
      setElapsedSeconds(0);
      return;
    }
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.max(1, Math.floor((Date.now() - startedAt) / 1000)));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  useEffect(() => {
    const scrollBox = chatScrollRef.current;
    scrollBox?.scrollTo({ top: scrollBox.scrollHeight, behavior: "smooth" });
  }, [messages, elapsedSeconds]);

  const handleSend = (draft: ComposerDraft) => {
    if (busy) {
      return;
    }
    messageNumberRef.current += 1;
    const turnId = messageNumberRef.current;
    const userKey = `user-${turnId}`;
    const assistantKey = `assistant-${turnId}`;
    const startedAt = Date.now();
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

    void sendChatMessage(
      requestPrompt(draft),
      draft.project?.path ?? null,
      sessionIdRef.current,
      draft.effort,
      (event) => {
        setMessages((current) => current.map((item) => {
          if (item.key !== assistantKey) {
            return item;
          }
          const trace = item.trace ?? [];
          const startsNewOutput = (
            event.type === "output_start" || event.type === "output_delta"
          ) && !trace.some((traceItem) => traceItem.key === event.block_id);
          const separator = startsNewOutput && item.content ? "\n\n" : "";
          const content = event.type === "output_delta"
            ? `${item.content}${separator}${event.text}`
            : `${item.content}${separator}`;
          return {
            ...item,
            content,
            trace: applyChatStreamEvent(trace, event),
          };
        }));
      },
    )
      .then((reply) => {
        sessionIdRef.current = reply.session_id;
        setMessages((current) => current.map((item) => (
          item.key === assistantKey
            ? {
                ...item,
                content: reply.content,
                finalOutputKey: reply.final_output_block_id ?? undefined,
                loading: false,
                status: "success",
                trace: finishAgentTrace(item.trace ?? [], "success"),
                traceExpanded: false,
                workingSeconds: Math.max(1, Math.round((Date.now() - startedAt) / 1000)),
              }
            : item
        )));
      })
      .catch((error: unknown) => {
        setMessages((current) => current.map((item) => (
          item.key === assistantKey
            ? {
                ...item,
                content: errorText(error),
                loading: false,
                status: "error",
                trace: finishAgentTrace(item.trace ?? [], "error"),
                traceExpanded: false,
                workingSeconds: Math.max(1, Math.round((Date.now() - startedAt) / 1000)),
              }
            : item
        )));
      })
      .finally(() => setBusy(false));
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
    const streamingOutput = item.loading && lastTraceItem?.kind === "output"
      ? lastTraceItem
      : undefined;
    const externalOutputKey = item.loading ? streamingOutput?.key : item.finalOutputKey;
    const responseContent = item.loading ? streamingOutput?.content : item.content;

    return {
      key: item.key,
      role: item.role,
      status: item.status,
      streaming: item.role === "ai" && item.loading,
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
            : responseContent && (
                <ChatMarkdown
                  content={responseContent}
                  streaming={Boolean(item.loading && streamingOutput?.status === "running")}
                />
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
    <main className={`workspace${conversationStarted ? " workspace-chat" : ""}`}>
      <div className="watermark" aria-hidden="true">X</div>
      {!conversationStarted ? (
        <div className="workspace-content">
          <div className="eyebrow">XALLING · AI WORKSPACE</div>
          <h2>{greeting}</h2>
          <p className="subtitle">{quote}</p>
          <TaskComposer
            onProjectChange={setSelectedProject}
            onSend={handleSend}
            selectedProject={selectedProject}
          />
        </div>
      ) : (
        <div className="chat-layout">
          <div ref={chatScrollRef} className="chat-scroll">
            <div className="chat-column">
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
          <div className="chat-composer-column">
            <TaskComposer
              busy={busy}
              conversationStarted
              onProjectChange={setSelectedProject}
              onSend={handleSend}
              selectedProject={selectedProject}
            />
          </div>
        </div>
      )}
    </main>
  );
}
