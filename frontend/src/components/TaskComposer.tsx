import {
  ArrowUpOutlined,
  DownOutlined,
  FolderOpenOutlined,
  GlobalOutlined,
  LoadingOutlined,
  PictureOutlined,
  PlusOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { Attachments, Sender } from "@ant-design/x";
import type { AttachmentsRef } from "@ant-design/x/es/attachments";
import type { SenderRef } from "@ant-design/x/es/sender";
import type { CascaderProps } from "antd";
import {
  Badge,
  Button,
  Cascader,
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
  type ModelGroup,
  type ProjectFolder,
} from "../bridge/client";

type TaskComposerProps = {
  busy?: boolean;
  conversationStarted?: boolean;
  onProjectChange: (project: ProjectFolder | null) => void;
  onSend: (draft: ComposerDraft) => void;
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
const MAX_ATTACHMENTS = 10;
const MAX_FILE_SIZE = 20 * 1024 * 1024;

export function TaskComposer({
  busy = false,
  conversationStarted = false,
  onProjectChange,
  onSend,
  selectedProject,
}: TaskComposerProps) {
  const [prompt, setPrompt] = useState("");
  const [modelGroups, setModelGroups] = useState<ModelGroup[]>([]);
  const [selectedModel, setSelectedModel] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [effort, setEffort] = useState(2);
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
    <section className={`composer${conversationStarted ? " composer-chat" : ""}`} aria-label="发送消息">
      {contextHolder}
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
              <Button type="text" icon={<ThunderboltOutlined />}>
                变更前确认 <DownOutlined />
              </Button>
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
