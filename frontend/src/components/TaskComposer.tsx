import {
  ArrowUpOutlined,
  BorderOutlined,
  CodeOutlined,
  DownOutlined,
  FileOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  FolderOutlined,
  GlobalOutlined,
  LockOutlined,
  LoadingOutlined,
  PictureOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
  UnlockOutlined,
} from "@ant-design/icons";
import { Attachments, Sender } from "@ant-design/x";
import type { AttachmentsRef } from "@ant-design/x/es/attachments";
import type { SenderRef } from "@ant-design/x/es/sender";
import type { SlotConfigType } from "@ant-design/x/es/sender/interface";
import type { CascaderProps, MenuProps } from "antd";
import {
  Badge,
  Button,
  Cascader,
  Dropdown,
  message,
  Popover,
  Slider,
  Space,
  Tooltip,
  Upload,
} from "antd";
import type { RcFile, UploadFile } from "antd/es/upload/interface";
import { useEffect, useRef, useState } from "react";

import {
  getClaudeCommands,
  getCurrentModel,
  getModelGroups,
  isAskUserQuestionRequest,
  searchProjectFiles,
  selectProjectFolder,
  setCurrentModel,
  type ChatPermissionAnswers,
  type ClaudeCommand,
  type ChatPermissionRequestEvent,
  type ChatPermissionMode,
  type ModelGroup,
  type ProjectFileMatch,
  type ProjectFolder,
} from "../bridge/client";
import { AskUserQuestionDialog } from "./AskUserQuestionDialog";

type TaskComposerProps = {
  busy?: boolean;
  conversationStarted?: boolean;
  effort: number;
  onEffortChange: (value: number) => void;
  onPermissionDecision?: (
    request: ChatPermissionRequestEvent,
    allowed: boolean,
    answers?: ChatPermissionAnswers,
  ) => Promise<void>;
  onPermissionModeChange: (mode: ChatPermissionMode) => void;
  onProjectChange: (project: ProjectFolder | null) => void;
  onSend: (draft: ComposerDraft) => void;
  onStop?: () => void;
  permissionMode: ChatPermissionMode;
  permissionRequest?: ChatPermissionRequestEvent | null;
  selectedProject: ProjectFolder | null;
  stopping?: boolean;
};

export type ComposerAttachment = {
  name: string;
  size?: number;
  type?: string;
};

export type ComposerDraft = {
  attachments: ComposerAttachment[];
  commandName?: string;
  effort: "low" | "medium" | "high" | "max";
  permissionMode: ChatPermissionMode;
  project: ProjectFolder | null;
  text: string;
};

type ModelOption = {
  value: string;
  label: string;
  children?: ModelOption[];
  imageVision?: boolean;
};

const effortLevels = ["低", "中", "高", "最高"] as const;
const effortValues = ["low", "medium", "high", "max"] as const;
const permissionModeLabels: Record<ChatPermissionMode, string> = {
  default: "变更前确认",
  acceptEdits: "自动编辑",
  plan: "计划模型",
  auto: "帮我批准",
  bypassPermissions: "完全访问",
};
const permissionModeDescriptions: Record<ChatPermissionMode, string> = {
  default: "改文件前先问我。",
  acceptEdits: "自动编辑文件。",
  plan: "编辑前先出计划。",
  auto: "帮你自动同意低风险操作（仅支持部分API）。",
  bypassPermissions: "减少确认次数，但可能会执行危险操作。",
};
const permissionModeIcons: Record<ChatPermissionMode, React.ReactNode> = {
  default: <SafetyCertificateOutlined />,
  acceptEdits: <CodeOutlined />,
  plan: <FileTextOutlined />,
  auto: <ThunderboltOutlined />,
  bypassPermissions: <UnlockOutlined />,
};
const permissionModeItems: MenuProps["items"] = (
  Object.keys(permissionModeLabels) as ChatPermissionMode[]
).map((mode) => ({
  key: mode,
  icon: permissionModeIcons[mode],
  label: (
    <div className="permission-mode-option">
      <div className="permission-mode-option-title">{permissionModeLabels[mode]}</div>
      <div className="permission-mode-option-description">
        {permissionModeDescriptions[mode]}
      </div>
    </div>
  ),
}));
const MAX_ATTACHMENTS = 10;
const MAX_FILE_SIZE = 20 * 1024 * 1024;
// Stable reference: a new array identity each render would reset the slot editor.
const EMPTY_SLOT_CONFIG: SlotConfigType[] = [];
const MENTION_TRIGGER_PATTERN = /(?:^|\s)@([^\s@]{0,64})$/u;
const COMMAND_TRIGGER_PATTERN = /^\/([^\s/]{0,64})$/u;

type MentionState = {
  activeIndex: number;
  loading: boolean;
  query: string;
  results: ProjectFileMatch[];
};

type CommandMenuState = {
  activeIndex: number;
  loading: boolean;
  query: string;
};

export function TaskComposer({
  busy = false,
  conversationStarted = false,
  effort,
  onEffortChange,
  onPermissionDecision,
  onPermissionModeChange,
  onProjectChange,
  onSend,
  onStop,
  permissionMode,
  permissionRequest = null,
  selectedProject,
  stopping = false,
}: TaskComposerProps) {
  const [prompt, setPrompt] = useState("");
  const [modelGroups, setModelGroups] = useState<ModelGroup[]>([]);
  const [selectedModel, setSelectedModel] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [permissionDecision, setPermissionDecision] = useState<"allow" | "deny" | null>(null);
  const [attachmentItems, setAttachmentItems] = useState<UploadFile[]>([]);
  const [attachmentsOpen, setAttachmentsOpen] = useState(false);
  const [selectingProject, setSelectingProject] = useState(false);
  const [mention, setMention] = useState<MentionState | null>(null);
  const [commandMenu, setCommandMenu] = useState<CommandMenuState | null>(null);
  const [claudeCommands, setClaudeCommands] = useState<ClaudeCommand[]>([]);
  const attachmentsRef = useRef<AttachmentsRef>(null);
  const senderRef = useRef<SenderRef>(null);
  const mentionListRef = useRef<HTMLDivElement>(null);
  const commandListRef = useRef<HTMLDivElement>(null);
  const commandContextRef = useRef<string | null>(null);
  const commandSequenceRef = useRef(0);
  const mentionSequenceRef = useRef(0);
  const conversationStartedRef = useRef(conversationStarted);
  conversationStartedRef.current = conversationStarted;
  const [messageApi, contextHolder] = message.useMessage();

  useEffect(() => {
    let active = true;

    const loadModels = async () => {
      try {
        const configuredGroups = await getModelGroups();
        if (!active) {
          return;
        }

        setModelGroups(configuredGroups);
        const currentModel = await getCurrentModel();
        if (active && currentModel) {
          setSelectedModel([currentModel.site, currentModel.model]);
        }
      } catch {
        if (active) {
          messageApi.error("模型列表加载失败，请检查本地配置");
        }
      } finally {
        if (active) {
          setModelsLoading(false);
        }
      }
    };

    void loadModels();
    return () => {
      active = false;
    };
  }, [messageApi]);

  useEffect(() => {
    setPermissionDecision(null);
  }, [permissionRequest?.permission_id]);

  const mentionQuery = mention?.query ?? null;
  const mentionProjectPath = selectedProject?.path ?? null;

  useEffect(() => {
    if (mentionQuery === null || mentionProjectPath === null) {
      return undefined;
    }
    let cancelled = false;
    setMention((current) => (current ? { ...current, loading: true } : current));
    const timer = window.setTimeout(() => {
      searchProjectFiles(mentionProjectPath, mentionQuery)
        .then((results) => {
          if (cancelled) {
            return;
          }
          setMention((current) => (
            current && current.query === mentionQuery
              ? { ...current, results, activeIndex: 0, loading: false }
              : current
          ));
        })
        .catch(() => {
          if (!cancelled) {
            setMention((current) => (current ? { ...current, results: [], loading: false } : current));
          }
        });
    }, 120);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [mentionQuery, mentionProjectPath]);

  useEffect(() => {
    mentionListRef.current
      ?.querySelector(".mention-item-active")
      ?.scrollIntoView({ block: "nearest" });
  }, [mention?.activeIndex]);

  const commandQuery = commandMenu?.query.trim().toLocaleLowerCase() ?? "";
  const commandDiscoveryKey = commandMenu
    ? `${selectedProject?.path ?? ""}\u0000${selectedModel.join("\u0000")}`
    : null;
  const commandMatchRank = (command: ClaudeCommand) => {
    const name = command.name.toLocaleLowerCase();
    const aliases = command.aliases.map((alias) => alias.toLocaleLowerCase());
    if (!commandQuery) {
      return command.kind === "command" ? 0 : 1;
    }
    if (name === commandQuery || aliases.includes(commandQuery)) {
      return 0;
    }
    if (name.startsWith(commandQuery) || aliases.some((alias) => alias.startsWith(commandQuery))) {
      return 1;
    }
    if (name.includes(commandQuery) || aliases.some((alias) => alias.includes(commandQuery))) {
      return 2;
    }
    return command.description.toLocaleLowerCase().includes(commandQuery) ? 3 : -1;
  };
  const filteredCommands = claudeCommands
    .map((command) => ({ command, rank: commandMatchRank(command) }))
    .filter(({ rank }) => rank >= 0)
    .sort((left, right) => left.rank - right.rank)
    .map(({ command }) => command);

  useEffect(() => {
    if (commandDiscoveryKey === null) {
      return undefined;
    }
    if (commandContextRef.current === commandDiscoveryKey) {
      return undefined;
    }
    commandContextRef.current = commandDiscoveryKey;
    let cancelled = false;
    let settled = false;
    setCommandMenu((current) => (current ? { ...current, loading: true } : current));
    getClaudeCommands(selectedProject?.path ?? null)
      .then((commands) => {
        settled = true;
        if (!cancelled) {
          setClaudeCommands(commands);
          setCommandMenu((current) => (
            current ? { ...current, activeIndex: 0, loading: false } : current
          ));
        }
      })
      .catch(() => {
        settled = true;
        if (!cancelled) {
          setClaudeCommands([]);
          setCommandMenu((current) => (
            current ? { ...current, activeIndex: 0, loading: false } : current
          ));
          messageApi.error("Claude 命令和技能加载失败，请检查模型配置。");
        }
      });
    return () => {
      cancelled = true;
      if (!settled && commandContextRef.current === commandDiscoveryKey) {
        commandContextRef.current = null;
      }
    };
  }, [commandDiscoveryKey, messageApi, selectedProject?.path]);

  useEffect(() => {
    commandListRef.current
      ?.querySelector(".mention-item-active")
      ?.scrollIntoView({ block: "nearest" });
  }, [commandMenu?.activeIndex]);

  const updateMentionFromSelection = () => {
    const selection = window.getSelection();
    const editorRoot = senderRef.current?.nativeElement;
    if (!selection || selection.rangeCount === 0 || !editorRoot) {
      setMention(null);
      return;
    }
    const range = selection.getRangeAt(0);
    const node = range.startContainer;
    if (!range.collapsed || !editorRoot.contains(node) || node.nodeType !== Node.TEXT_NODE) {
      setMention(null);
      return;
    }
    const textBeforeCursor = node.textContent?.slice(0, range.startOffset) ?? "";
    const match = MENTION_TRIGGER_PATTERN.exec(textBeforeCursor);
    if (!match) {
      setMention(null);
      return;
    }
    setCommandMenu(null);
    const query = match[1];
    setMention((current) => (
      current?.query === query
        ? current
        : {
          query,
          results: current?.results ?? [],
          activeIndex: 0,
          loading: true,
        }
    ));
  };

  const updateCommandFromValue = (value: string) => {
    const match = COMMAND_TRIGGER_PATTERN.exec(value);
    if (!match) {
      setCommandMenu(null);
      return false;
    }
    const query = match[1];
    setMention(null);
    setCommandMenu((current) => (
      current?.query === query
        ? current
        : { query, activeIndex: 0, loading: commandContextRef.current === null }
    ));
    return true;
  };

  const insertMention = (item: ProjectFileMatch) => {
    const query = mention?.query ?? "";
    mentionSequenceRef.current += 1;
    senderRef.current?.insert(
      [
        {
          type: "tag",
          key: `mention-${mentionSequenceRef.current}`,
          props: {
            label: (
              <span className="mention-chip">
                {item.is_dir ? <FolderOutlined /> : <FileOutlined />}
                <span>{item.name}</span>
              </span>
            ),
            value: item.path,
          },
          formatResult: (value: string) => `@${value}`,
        },
        { type: "text", value: " " },
      ],
      "cursor",
      `@${query}`,
    );
    setMention(null);
    senderRef.current?.focus();
  };

  const modelOptions: ModelOption[] = modelGroups
    .filter((group) => group.models.length > 0)
    .map((group) => ({
      value: group.name,
      label: group.name,
      children: group.models.map((model) => ({
        value: model.name,
        label: model.name,
        imageVision: model.image_vision,
      })),
    }));
  const hasModels = modelOptions.length > 0;

  const handleModelChange: CascaderProps<ModelOption>["onChange"] = (value) => {
    const selection = value as string[];
    setSelectedModel(selection);
    const [site, model] = selection;
    if (site && model) {
      void setCurrentModel(site, model).catch(() => {
        messageApi.error("当前模型保存失败");
      });
    }
  };

  const handleSubmit = (value: string, explicitCommandName?: string) => {
    const content = value.trim();
    if (!content && !attachmentItems.length) {
      messageApi.warning("请输入消息或添加附件。");
      return;
    }
    if (busy) {
      return;
    }

    const commandToken = content.match(/^\/([^\s/]+)/u)?.[1];
    const matchedCommand = claudeCommands.find((command) => (
      command.name === commandToken || command.aliases.includes(commandToken ?? "")
    ));
    onSend({
      text: content,
      commandName: explicitCommandName ?? matchedCommand?.name,
      project: selectedProject,
      effort: effortValues[effort],
      permissionMode,
      attachments: attachmentItems.map((file) => ({
        name: file.name,
        size: file.size,
        type: file.type,
      })),
    });
    setPrompt("");
    setMention(null);
    setCommandMenu(null);
    senderRef.current?.clear();
    setAttachmentItems([]);
    setAttachmentsOpen(false);
  };

  const selectCommand = (command: ClaudeCommand) => {
    if (command.kind === "command") {
      handleSubmit(`/${command.name}`, command.name);
      return;
    }
    const query = commandMenu?.query ?? "";
    commandSequenceRef.current += 1;
    senderRef.current?.insert(
      [
        {
          type: "tag",
          key: `command-${commandSequenceRef.current}`,
          props: {
            label: <span className="command-chip">/{command.name}</span>,
            value: command.name,
          },
          formatResult: (value: string) => `/${value}`,
        },
        { type: "text", value: " " },
      ],
      "cursor",
      `/${query}`,
    );
    setCommandMenu(null);
    window.requestAnimationFrame(() => senderRef.current?.focus({ cursor: "end" }));
  };

  const handlePermissionModeChange: MenuProps["onClick"] = ({ key }) => {
    onPermissionModeChange(key as ChatPermissionMode);
  };

  const handleToolPermissionDecision = async (
    allowed: boolean,
    answers?: ChatPermissionAnswers,
  ) => {
    if (!permissionRequest || !onPermissionDecision || permissionDecision || stopping) {
      return;
    }
    setPermissionDecision(allowed ? "allow" : "deny");
    try {
      await onPermissionDecision(permissionRequest, allowed, answers);
    } catch (error) {
      const text = error instanceof Error && error.message.trim()
        ? error.message
        : "权限决定提交失败，请重试。";
      messageApi.error(text);
      setPermissionDecision(null);
    }
  };

  const beforeAttach = (file: RcFile) => {
    if (file.size > MAX_FILE_SIZE) {
      messageApi.error(`${file.name} 超过 20 MB，无法添加。`);
      return Upload.LIST_IGNORE;
    }
    if (attachmentItems.length >= MAX_ATTACHMENTS) {
      messageApi.warning(`每次最多添加 ${MAX_ATTACHMENTS} 个附件。`);
      return Upload.LIST_IGNORE;
    }
    return false;
  };

  const addPastedFiles = (files: FileList) => {
    const availableSlots = MAX_ATTACHMENTS - attachmentItems.length;
    const acceptedFiles = Array.from(files)
      .filter((file) => {
        if (file.size <= MAX_FILE_SIZE) {
          return true;
        }
        messageApi.error(`${file.name} 超过 20 MB，无法添加。`);
        return false;
      })
      .slice(0, availableSlots)
      .map((file, index): UploadFile => {
        const uid = `pasted-${Date.now()}-${index}`;
        const originFile = Object.assign(file, {
          uid,
          lastModifiedDate: new Date(file.lastModified),
        }) as RcFile;
        return {
          uid,
          name: file.name,
          size: file.size,
          type: file.type,
          originFileObj: originFile,
        };
      });

    if (files.length > availableSlots) {
      messageApi.warning(`每次最多添加 ${MAX_ATTACHMENTS} 个附件。`);
    }
    if (acceptedFiles.length) {
      setAttachmentItems((current) => [...current, ...acceptedFiles]);
      setAttachmentsOpen(true);
    }
  };

  const chooseProjectFolder = async () => {
    if (conversationStarted || selectingProject) {
      return;
    }
    setSelectingProject(true);
    try {
      const project = await selectProjectFolder();
      if (project && !conversationStartedRef.current) {
        onProjectChange(project);
      }
    } catch {
      messageApi.error("项目文件夹选择失败。");
    } finally {
      setSelectingProject(false);
    }
  };

  return (
    <section
      className={`composer${conversationStarted ? " composer-chat" : ""}${
        permissionRequest ? " composer-permission-active" : ""
      }`}
      aria-label="发送消息"
    >
      {contextHolder}
      {permissionRequest && isAskUserQuestionRequest(permissionRequest) ? (
        <AskUserQuestionDialog
          key={permissionRequest.permission_id}
          decision={permissionDecision}
          onDecision={handleToolPermissionDecision}
          onStop={onStop}
          request={permissionRequest}
          stopping={stopping}
        />
      ) : permissionRequest && (
        <section
          aria-labelledby="tool-permission-title"
          aria-modal="true"
          className="tool-permission-dialog"
          role="alertdialog"
        >
          <div className="tool-permission-heading">
            <span className="tool-permission-icon"><SafetyCertificateOutlined /></span>
            <div className="tool-permission-copy">
              <strong id="tool-permission-title">{permissionRequest.title}</strong>
              <span>{permissionRequest.description}</span>
            </div>
            <code>{permissionRequest.display_name || permissionRequest.tool_name}</code>
          </div>
          <pre className="tool-permission-input">
            {JSON.stringify(permissionRequest.input, null, 2)}
          </pre>
          <div className="tool-permission-actions">
            {busy && onStop && (
              <Tooltip title={stopping ? "正在停止…" : "停止生成"}>
                <Button
                  aria-label="停止生成"
                  className="permission-stop-button"
                  disabled={stopping}
                  icon={stopping ? <LoadingOutlined spin /> : <BorderOutlined />}
                  onClick={onStop}
                  shape="circle"
                />
              </Tooltip>
            )}
            <Button
              danger
              disabled={permissionDecision !== null || stopping}
              loading={permissionDecision === "deny"}
              onClick={() => void handleToolPermissionDecision(false)}
            >
              拒绝
            </Button>
            <Button
              disabled={permissionDecision !== null || stopping}
              loading={permissionDecision === "allow"}
              onClick={() => void handleToolPermissionDecision(true)}
              type="primary"
            >
              允许
            </Button>
          </div>
        </section>
      )}
      {commandMenu && (
        <div
          className="mention-panel command-panel"
          role="listbox"
          aria-label="选择 Claude 命令或技能"
          onMouseDown={(event) => event.preventDefault()}
        >
          <div className="mention-panel-title">Claude 命令和技能</div>
          <div className="mention-panel-list" ref={commandListRef}>
            {filteredCommands.length === 0 ? (
              <div className="mention-empty">
                {commandMenu.loading ? "正在读取 Claude 命令和技能…" : "没有匹配的命令或技能。"}
              </div>
            ) : (
              filteredCommands.map((command, index) => (
                <button
                  key={command.name}
                  type="button"
                  role="option"
                  aria-selected={index === commandMenu.activeIndex}
                  className={`mention-item${index === commandMenu.activeIndex ? " mention-item-active" : ""}`}
                  onMouseEnter={() => setCommandMenu((current) => (
                    current ? { ...current, activeIndex: index } : current
                  ))}
                  onClick={() => selectCommand(command)}
                >
                  {command.kind === "skill" ? <ThunderboltOutlined /> : <CodeOutlined />}
                  <span className="mention-item-name">/{command.name}</span>
                  <span className="mention-item-path" title={command.description}>
                    {command.description || command.argument_hint || "Claude 命令"}
                  </span>
                  <span className="command-item-kind">
                    {command.kind === "skill" ? "技能" : "命令"}
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      )}
      {mention && (
        <div
          className="mention-panel"
          role="listbox"
          aria-label="选择要引用的文件或文件夹"
          onMouseDown={(event) => event.preventDefault()}
        >
          <div className="mention-panel-title">引用文件或文件夹</div>
          <div className="mention-panel-list" ref={mentionListRef}>
            {!selectedProject ? (
              <div className="mention-empty">请先选择项目文件夹。</div>
            ) : mention.results.length === 0 ? (
              <div className="mention-empty">
                {mention.loading ? "搜索中…" : "没有匹配的文件或文件夹。"}
              </div>
            ) : (
              mention.results.map((item, index) => (
                <button
                  key={item.path}
                  type="button"
                  role="option"
                  aria-selected={index === mention.activeIndex}
                  className={`mention-item${index === mention.activeIndex ? " mention-item-active" : ""}`}
                  onMouseEnter={() => setMention((current) => (
                    current ? { ...current, activeIndex: index } : current
                  ))}
                  onClick={() => insertMention(item)}
                >
                  {item.is_dir ? <FolderOutlined /> : <FileOutlined />}
                  <span className="mention-item-name">{item.name}</span>
                  <span className="mention-item-path">{item.relative}</span>
                </button>
              ))
            )}
          </div>
        </div>
      )}
      <Sender
        ref={senderRef}
        className="task-sender"
        autoSize={{ minRows: conversationStarted ? 2 : 3, maxRows: 7 }}
        value={prompt}
        slotConfig={EMPTY_SLOT_CONFIG}
        onChange={(value) => {
          setPrompt(value);
          if (!updateCommandFromValue(value)) {
            updateMentionFromSelection();
          }
        }}
        onKeyUp={() => {
          if (!updateCommandFromValue(prompt)) {
            updateMentionFromSelection();
          }
        }}
        onBlur={() => {
          setMention(null);
          setCommandMenu(null);
        }}
        onKeyDown={(event) => {
          if (event.nativeEvent.isComposing) {
            return undefined;
          }
          if (commandMenu) {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              const delta = event.key === "ArrowDown" ? 1 : -1;
              setCommandMenu((current) => {
                if (!current || filteredCommands.length === 0) {
                  return current;
                }
                const count = filteredCommands.length;
                return { ...current, activeIndex: (current.activeIndex + delta + count) % count };
              });
              return false;
            }
            if (event.key === "Enter" || event.key === "Tab") {
              event.preventDefault();
              const command = filteredCommands[commandMenu.activeIndex];
              if (command) {
                selectCommand(command);
              } else if (!commandMenu.loading) {
                setCommandMenu(null);
              }
              return false;
            }
            if (event.key === "Escape") {
              setCommandMenu(null);
              return false;
            }
          }
          if (mention) {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              const delta = event.key === "ArrowDown" ? 1 : -1;
              setMention((current) => {
                if (!current || current.results.length === 0) {
                  return current;
                }
                const count = current.results.length;
                return { ...current, activeIndex: (current.activeIndex + delta + count) % count };
              });
              return false;
            }
            if (event.key === "Enter" || event.key === "Tab") {
              event.preventDefault();
              const item = mention.results[mention.activeIndex];
              if (item) {
                insertMention(item);
              } else {
                setMention(null);
              }
              return false;
            }
            if (event.key === "Escape") {
              setMention(null);
              return false;
            }
          }
          if (event.key !== "Enter") {
            return undefined;
          }
          if (event.ctrlKey) {
            return false;
          }
          if (event.shiftKey || event.altKey || event.metaKey) {
            return undefined;
          }
          event.preventDefault();
          handleSubmit(prompt);
          return false;
        }}
        onSubmit={(value) => handleSubmit(value)}
        onPasteFile={addPastedFiles}
        loading={busy}
        submitType="enter"
        suffix={false}
        placeholder={conversationStarted
          ? "继续输入以排队后续修改"
          : "描述你想完成的任务，使用 @ 添加上下文，使用 / 选择命令或能力"}
        header={(
          <>
            <Tooltip
              title={conversationStarted
                ? "当前会话已锁定工作区；新建任务后可重新选择"
                : selectedProject?.path}
            >
              <button
                aria-disabled={conversationStarted || selectingProject}
                aria-label={conversationStarted ? "当前会话的工作区已锁定" : "选择工作区"}
                className={`composer-project${conversationStarted ? " composer-project-locked" : ""}`}
                disabled={conversationStarted || selectingProject}
                type="button"
                onClick={() => void chooseProjectFolder()}
              >
                {selectingProject ? <LoadingOutlined spin /> : <FolderOpenOutlined />}
                <span>{selectedProject?.name ?? "选择项目"}</span>
                {conversationStarted ? <LockOutlined /> : <DownOutlined />}
              </button>
            </Tooltip>
            <Sender.Header
              closable={false}
              forceRender
              open={attachmentsOpen}
              onOpenChange={setAttachmentsOpen}
            >
              <Attachments
                ref={attachmentsRef}
                className="task-attachments"
                items={attachmentItems}
                beforeUpload={beforeAttach}
                getDropContainer={() => senderRef.current?.nativeElement}
                maxCount={MAX_ATTACHMENTS}
                multiple
                onChange={({ fileList }) => {
                  setAttachmentItems(fileList);
                  setAttachmentsOpen(fileList.length > 0);
                }}
                overflow="scrollX"
                placeholder={{
                  title: "拖放图片或文件到这里",
                  description: "支持图片预览和常用文件，单个附件不超过 20 MB",
                }}
              />
            </Sender.Header>
          </>
        )}
        footer={(
          <div className="composer-footer">
            <Space size={6}>
              <Tooltip title="添加图片或文件">
                <Badge count={attachmentItems.length} size="small">
                  <Button
                    type="text"
                    icon={<PlusOutlined />}
                    aria-label="添加图片或文件"
                    onClick={() => {
                      attachmentsRef.current?.select({ multiple: true });
                    }}
                  />
                </Badge>
              </Tooltip>
              <Dropdown
                menu={{
                  items: permissionModeItems,
                  onClick: handlePermissionModeChange,
                  selectedKeys: [permissionMode],
                }}
                classNames={{ root: "permission-mode-dropdown" }}
                placement="topLeft"
                trigger={["click"]}
              >
                <Button
                  aria-label="选择 Claude 权限模式"
                  disabled={busy}
                  type="text"
                  icon={<ThunderboltOutlined />}
                >
                  {permissionModeLabels[permissionMode]} <DownOutlined />
                </Button>
              </Dropdown>
            </Space>
            <Space size={6}>
              <Cascader<ModelOption>
                aria-label="选择模型"
                className="model-select"
                disabled={modelsLoading || !hasModels}
                displayRender={(labels) => labels.join(" · ")}
                expandTrigger="hover"
                onChange={handleModelChange}
                optionRender={(option) => (
                  <span className="model-option">
                    <span>{option.label}</span>
                    {option.imageVision && (
                      <PictureOutlined className="model-capability" title="支持图片输入" />
                    )}
                  </span>
                )}
                options={modelOptions}
                placeholder={modelsLoading ? "读取模型…" : "未配置模型"}
                prefix={<GlobalOutlined />}
                showSearch
                size="small"
                suffixIcon={modelsLoading ? <LoadingOutlined spin /> : <DownOutlined />}
                value={selectedModel}
                variant="borderless"
              />
              <Popover
                arrow={false}
                content={(
                  <div className="effort-picker">
                    <div className="effort-picker-header">
                      <span>推理强度</span>
                      <strong>{effortLevels[effort]}</strong>
                    </div>
                    <Slider
                      aria-label="推理强度"
                      dots
                      max={effortLevels.length - 1}
                      min={0}
                      onChange={onEffortChange}
                      step={1}
                      tooltip={{ formatter: (value) => effortLevels[value ?? effort] }}
                      value={effort}
                    />
                  </div>
                )}
                placement="top"
                trigger="click"
              >
                <Button type="text" icon={<ThunderboltOutlined />}>
                  {effortLevels[effort]} <DownOutlined />
                </Button>
              </Popover>
              {busy ? (
                <Tooltip title={stopping ? "正在停止…" : "停止生成"}>
                  <Button
                    aria-label="停止生成"
                    className="sender-stop-button"
                    disabled={stopping}
                    icon={stopping ? <LoadingOutlined spin /> : <BorderOutlined />}
                    onClick={onStop}
                    shape="circle"
                    type="primary"
                  />
                </Tooltip>
              ) : (
                <Button
                  aria-label="发送消息"
                  className="sender-send-button"
                  disabled={!prompt.trim() && !attachmentItems.length}
                  icon={<ArrowUpOutlined />}
                  onClick={() => handleSubmit(prompt)}
                  shape="circle"
                  type="primary"
                />
              )}
            </Space>
          </div>
        )}
      />
    </section>
  );
}
