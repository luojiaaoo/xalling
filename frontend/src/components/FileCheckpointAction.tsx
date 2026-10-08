import { RollbackOutlined } from "@ant-design/icons";
import { App } from "antd";

import { rewindChatFiles, type ChatRenderEvent } from "../api/client";

type FileCheckpointActionProps = {
  checkpointId: string;
  disabled: boolean;
  filesRestoredAt?: string;
  projectPath: string | null;
  sessionId: string;
  onRestored: (event: ChatRenderEvent) => void;
  onRestoringChange: (restoring: boolean) => void;
  label?: string;
};

export function FileCheckpointAction({
  checkpointId, disabled, filesRestoredAt, projectPath, sessionId, onRestored, onRestoringChange, label: customLabel,
}: FileCheckpointActionProps) {
  const { modal, message } = App.useApp();
  const label = customLabel ?? (filesRestoredAt ? "再次恢复文件" : "恢复文件到此处");
  return (
    <button
      type="button"
      className="message-action-button"
      disabled={disabled}
      aria-label={label}
      title={disabled ? "请等待生成或文件恢复结束" : "使用此消息的检查点恢复文件"}
      onClick={() => modal.confirm({
        title: "恢复文件到这条消息之前？",
        content: (
          <div>
            <p>{projectPath}</p>
            <p>此操作会覆盖已跟踪文件的后续修改，也可能删除之后由 Claude 创建的文件。聊天记录会保留。</p>
            <p>检查点覆盖主智能体通过 Write、Edit、NotebookEdit 做出的修改；命令行和普通子智能体的修改不在跟踪范围内。</p>
          </div>
        ),
        okText: "确认恢复文件",
        cancelText: "取消",
        okButtonProps: { danger: true },
        onOk: async () => {
          onRestoringChange(true);
          try {
            const result = await rewindChatFiles(sessionId, checkpointId);
            onRestored(result.event);
            if (result.warning) void message.warning(result.warning);
            else void message.success("文件已恢复到这条消息之前。");
          } catch (error) {
            void message.error(error instanceof Error ? error.message : "恢复失败，请刷新查看文件状态。");
            throw error;
          } finally {
            onRestoringChange(false);
          }
        },
      })}
    >
      <RollbackOutlined />
      <span className="message-action-label">{label}</span>
    </button>
  );
}
