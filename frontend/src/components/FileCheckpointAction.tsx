import { RollbackOutlined } from "@ant-design/icons";
import { App } from "antd";
import { useEffect, useRef, useState } from "react";

import { previewChatFiles, rewindChatFiles, type ChatRenderEvent } from "../api/client";

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
  const [previewing, setPreviewing] = useState(false);
  const pending = useRef(false);
  const version = useRef(0);
  useEffect(() => {
    pending.current = false;
    setPreviewing(false);
    return () => { version.current++; pending.current = false; };
  }, [sessionId, checkpointId]);
  const label = customLabel ?? (filesRestoredAt ? "再次恢复文件" : "恢复文件到此处");
  const showPreview = async () => {
    if (disabled || pending.current) return;
    pending.current = true;
    setPreviewing(true);
    const requestVersion = version.current;
    try {
      const preview = await previewChatFiles(sessionId, checkpointId);
      if (requestVersion !== version.current) return;
      const noChanges = preview.files !== null && preview.files.length === 0;
      modal.confirm({
        title: "恢复文件到这条消息之前？",
        content: (
          <div>
            <p>{projectPath}</p>
            {!preview.can_restore ? <p role="status">此检查点已不可恢复，请重新打开会话后再试。</p> : (
              <>
                <p>恢复预览：{preview.files === null ? "文件数量未知" : `涉及 ${preview.files.length} 个文件`}</p>
                <p>增删行数：{preview.insertions === null || preview.deletions === null
                  ? "未知" : `+${preview.insertions} / -${preview.deletions}`}</p>
                {noChanges && <p>当前没有需要恢复的文件。</p>}
                {preview.files !== null && preview.files.length > 0 && (
                  <ul aria-label="恢复涉及的文件" style={{ maxHeight: 240, overflowY: "auto", overflowWrap: "anywhere" }}>
                    {preview.files.map((path) => <li key={path}>{path}</li>)}
                  </ul>
                )}
              </>
            )}
            <p>此操作会覆盖已跟踪文件的后续修改，也可能删除之后由 Claude 创建的文件。聊天记录会保留。</p>
            <p>检查点覆盖主智能体通过 Write、Edit、NotebookEdit 做出的修改；命令行和普通子智能体的修改不在跟踪范围内。</p>
            <p>预览展示当前文件与所选检查点之间的变化范围；实际恢复时会重新检查。</p>
          </div>
        ),
        okText: "确认恢复文件",
        cancelText: "取消",
        okButtonProps: { danger: true, disabled: !preview.can_restore || noChanges },
        onOk: async () => {
          if (!preview.can_restore || noChanges) return;
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
      });
    } catch (error) {
      if (requestVersion === version.current) {
        void message.error(error instanceof Error ? error.message : "恢复预览失败，请稍后重试。");
      }
    } finally {
      if (requestVersion === version.current) {
        pending.current = false;
        setPreviewing(false);
      }
    }
  };
  return (
    <button
      type="button"
      className="message-action-button"
      disabled={disabled || previewing}
      aria-busy={previewing}
      aria-label={label}
      title={disabled ? "请等待生成或文件恢复结束" : "使用此消息的检查点恢复文件"}
      onClick={() => void showPreview()}
    >
      <RollbackOutlined />
      <span className="message-action-label">{previewing ? "正在查询恢复预览…" : label}</span>
    </button>
  );
}
