import {
  ArrowUpOutlined,
  DownOutlined,
  FolderOpenOutlined,
  PaperClipOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { Button, Dropdown, Input, message, Space } from "antd";
import { useState } from "react";

import { submitTask } from "../bridge/client";

type TaskComposerProps = {
  prompt: string;
  onPromptChange: (prompt: string) => void;
};

export function TaskComposer({ prompt, onPromptChange }: TaskComposerProps) {
  const [submitting, setSubmitting] = useState(false);
  const [messageApi, contextHolder] = message.useMessage();

  const handleSubmit = async () => {
    const content = prompt.trim();
    if (!content) {
      messageApi.warning("先输入你希望我完成的任务吧");
      return;
    }

    setSubmitting(true);
    try {
      const result = await submitTask({ prompt: content });
      messageApi.success(result.message);
      onPromptChange("");
    } catch {
      messageApi.error("任务提交失败，请稍后重试");
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
          <Button type="text">管理模型 <DownOutlined /></Button>
          <Button type="text" icon={<ThunderboltOutlined />}>最高 <DownOutlined /></Button>
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
