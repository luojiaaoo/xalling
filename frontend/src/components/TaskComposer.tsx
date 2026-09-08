import {
  ArrowUpOutlined,
  DownOutlined,
  EyeOutlined,
  FolderOpenOutlined,
  LoadingOutlined,
  PaperClipOutlined,
  RobotOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import type { CascaderProps } from "antd";
import { Button, Cascader, Input, message, Popover, Slider, Space } from "antd";
import { useEffect, useState } from "react";

import { getModelGroups, type ModelGroup } from "../bridge/client";

type TaskComposerProps = {
  prompt: string;
  onPromptChange: (prompt: string) => void;
};

type ModelOption = {
  value: string;
  label: string;
  children?: ModelOption[];
  vision?: boolean;
};

const effortLevels = ["低", "中", "高", "最高"] as const;

export function TaskComposer({ prompt, onPromptChange }: TaskComposerProps) {
  const [submitting, setSubmitting] = useState(false);
  const [modelGroups, setModelGroups] = useState<ModelGroup[]>([]);
  const [selectedModel, setSelectedModel] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [effort, setEffort] = useState(2);
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
        const firstGroupIndex = configuredGroups.findIndex((group) => group.models.length > 0);
        if (firstGroupIndex >= 0) {
          setSelectedModel([String(firstGroupIndex), configuredGroups[firstGroupIndex].models[0]]);
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

  const modelOptions: ModelOption[] = modelGroups.map((group, groupIndex) => ({
    value: String(groupIndex),
    label: group.name,
    children: group.models.map((model) => ({
      value: model,
      label: model,
      vision: group.vision,
    })),
  }));
  const hasModels = modelGroups.some((group) => group.models.length > 0);
  const handleModelChange: CascaderProps<ModelOption>["onChange"] = (value) => {
    setSelectedModel(value as string[]);
  };

  const handleSubmit = async () => {
    const content = prompt.trim();
    if (!content) {
      messageApi.warning("先输入你希望我完成的任务吧");
      return;
    }

    setSubmitting(true);
    try {
      messageApi.info("当前仅完成界面交互，智能体能力将在后续步骤接入。");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="composer" aria-label="新建任务">
      {contextHolder}
      <div className="composer-project"><FolderOpenOutlined />选择项目 <DownOutlined /></div>
      <Input.TextArea
        aria-label="任务描述"
        autoSize={{ minRows: 3, maxRows: 7 }}
        onChange={(event) => onPromptChange(event.target.value)}
        onPressEnter={(event) => {
          if (!event.shiftKey) {
            event.preventDefault();
            void handleSubmit();
          }
        }}
        placeholder="描述你想完成的任务，使用 @ 添加上下文，使用 / 选择命令或能力"
        value={prompt}
      />
      <div className="composer-footer">
        <Space size={6}>
          <Button type="text" icon={<PaperClipOutlined />} aria-label="添加附件" />
          <Button type="text" icon={<ThunderboltOutlined />}>变更前确认 <DownOutlined /></Button>
        </Space>
        <Space size={6}>
          <Cascader<ModelOption>
            aria-label="选择模型"
            className="model-select"
            disabled={modelsLoading || !hasModels}
            displayRender={(labels) => labels.at(-1)}
            expandTrigger="hover"
            onChange={handleModelChange}
            optionRender={(option) => (
              <span className="model-option">
                <span>{option.label}</span>
                {option.vision && <EyeOutlined className="model-capability" title="支持视觉输入" />}
              </span>
            )}
            options={modelOptions}
            placeholder={modelsLoading ? "读取模型…" : "未配置模型"}
            prefix={<RobotOutlined />}
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
            aria-label="提交任务"
            className="send-button"
            icon={<ArrowUpOutlined />}
            loading={submitting}
            onClick={() => void handleSubmit()}
            shape="circle"
            type="primary"
          />
        </Space>
      </div>
    </section>
  );
}
