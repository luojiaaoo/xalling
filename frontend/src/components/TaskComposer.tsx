import {
  ArrowUpOutlined,
  CodeOutlined,
  DownOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  GlobalOutlined,
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
  getCurrentModel,
  getModelGroups,
  selectProjectFolder,
  setCurrentModel,
  type ChatPermissionRequestEvent,
  type ChatPermissionMode,
  type ModelGroup,
  type ProjectFolder,
} from "../bridge/client";

type TaskComposerProps = {
  busy?: boolean;
  conversationStarted?: boolean;
  onPermissionDecision?: (
    request: ChatPermissionRequestEvent,
    allowed: boolean,
  ) => Promise<void>;
  onProjectChange: (project: ProjectFolder | null) => void;
  onSend: (draft: ComposerDraft) => void;
  permissionRequest?: ChatPermissionRequestEvent | null;
  selectedProject: ProjectFolder | null;
};

export type ComposerAttachment = {
  name: string;
  size?: number;
  type?: string;
};

export type ComposerDraft = {
  attachments: ComposerAttachment[];
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

export function TaskComposer({
  busy = false,
  conversationStarted = false,
  onPermissionDecision,
  onProjectChange,
  onSend,
  permissionRequest = null,
  selectedProject,
}: TaskComposerProps) {
  const [prompt, setPrompt] = useState("");
  const [modelGroups, setModelGroups] = useState<ModelGroup[]>([]);
  const [selectedModel, setSelectedModel] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [effort, setEffort] = useState(2);
  const [permissionMode, setPermissionMode] = useState<ChatPermissionMode>("default");
  const [permissionDecision, setPermissionDecision] = useState<"allow" | "deny" | null>(null);
  const [attachmentItems, setAttachmentItems] = useState<UploadFile[]>([]);
  const [attachmentsOpen, setAttachmentsOpen] = useState(false);
  const [selectingProject, setSelectingProject] = useState(false);
  const attachmentsRef = useRef<AttachmentsRef>(null);
  const senderRef = useRef<SenderRef>(null);
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

  const handleSubmit = (value: string) => {
    const content = value.trim();
    if (!content && !attachmentItems.length) {
      messageApi.warning("请输入消息或添加附件。");
      return;
    }
    if (busy) {
      return;
    }

    onSend({
      text: content,
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
    setAttachmentItems([]);
    setAttachmentsOpen(false);
  };

  const handlePermissionModeChange: MenuProps["onClick"] = ({ key }) => {
    setPermissionMode(key as ChatPermissionMode);
  };

  const handleToolPermissionDecision = async (allowed: boolean) => {
    if (!permissionRequest || !onPermissionDecision || permissionDecision) {
      return;
    }
    setPermissionDecision(allowed ? "allow" : "deny");
    try {
      await onPermissionDecision(permissionRequest, allowed);
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
    setSelectingProject(true);
    try {
      const project = await selectProjectFolder();
      if (project) {
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
      {permissionRequest && (
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
            <Button
              danger
              disabled={permissionDecision !== null}
              loading={permissionDecision === "deny"}
              onClick={() => void handleToolPermissionDecision(false)}
            >
              拒绝
            </Button>
            <Button
              disabled={permissionDecision !== null}
              loading={permissionDecision === "allow"}
              onClick={() => void handleToolPermissionDecision(true)}
              type="primary"
            >
              允许
            </Button>
          </div>
        </section>
      )}
      <Sender
        ref={senderRef}
        className="task-sender"
        autoSize={{ minRows: conversationStarted ? 2 : 3, maxRows: 7 }}
        value={prompt}
        onChange={setPrompt}
        onKeyDown={(event) => {
          if (event.key !== "Enter" || event.nativeEvent.isComposing) {
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
        onSubmit={handleSubmit}
        onPasteFile={addPastedFiles}
        loading={busy}
        submitType="enter"
        suffix={false}
        placeholder={conversationStarted
          ? "继续输入以排队后续修改"
          : "描述你想完成的任务，使用 @ 添加上下文，使用 / 选择命令或能力"}
        header={(
          <>
            <Tooltip title={selectedProject?.path}>
              <button
                className="composer-project"
                type="button"
                onClick={() => void chooseProjectFolder()}
              >
                {selectingProject ? <LoadingOutlined spin /> : <FolderOpenOutlined />}
                <span>{selectedProject?.name ?? "选择项目"}</span>
                <DownOutlined />
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
                      onChange={setEffort}
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
              <Button
                aria-label="发送消息"
                className="sender-send-button"
                disabled={busy || (!prompt.trim() && !attachmentItems.length)}
                icon={<ArrowUpOutlined />}
                loading={busy}
                onClick={() => handleSubmit(prompt)}
                shape="circle"
                type="primary"
              />
            </Space>
          </div>
        )}
      />
    </section>
  );
}
