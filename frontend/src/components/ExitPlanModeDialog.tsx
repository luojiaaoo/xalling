import {
  ArrowRightOutlined,
  BorderOutlined,
  FileTextOutlined,
  LoadingOutlined,
} from "@ant-design/icons";
import { Button, Input, Tooltip } from "antd";
import { useState } from "react";

import type {
  ChatPermissionMode,
  ChatPermissionRequestEvent,
} from "../bridge/client";
import { ChatMarkdown } from "./ChatMarkdown";

type ExitPlanModeDialogProps = {
  decision: "allow" | "deny" | null;
  onDecision: (allowed: boolean, feedback?: string) => Promise<void>;
  onStop?: () => void;
  request: ChatPermissionRequestEvent;
  stopping?: boolean;
};

const permissionModeLabels: Record<Exclude<ChatPermissionMode, "plan">, string> = {
  default: "变更前确认",
  acceptEdits: "自动编辑",
  auto: "帮我批准",
  bypassPermissions: "完全访问",
};

export function ExitPlanModeDialog({
  decision,
  onDecision,
  onStop,
  request,
  stopping = false,
}: ExitPlanModeDialogProps) {
  const [feedback, setFeedback] = useState("");
  const nextMode = request.suggested_permission_mode ?? "default";
  const disabled = decision !== null || stopping;
  const rawPlan = request.input.plan;
  const plan = typeof rawPlan === "string" ? rawPlan.trim() : "";

  return (
    <section
      aria-labelledby={`exit-plan-mode-title-${request.permission_id}`}
      aria-modal="true"
      className="tool-permission-dialog exit-plan-mode-dialog"
      role="dialog"
    >
      <div className="tool-permission-heading">
        <span className="tool-permission-icon"><FileTextOutlined /></span>
        <div className="tool-permission-copy">
          <strong id={`exit-plan-mode-title-${request.permission_id}`}>
            计划已准备好
          </strong>
          <span>确认后，Claude 将退出计划模式并开始执行。</span>
        </div>
        <span className="exit-plan-mode-transition">
          计划模式 <ArrowRightOutlined /> {permissionModeLabels[nextMode]}
        </span>
      </div>
      {plan && (
        <section className="exit-plan-mode-plan" aria-label="待执行计划">
          <div className="exit-plan-mode-plan-heading">
            <FileTextOutlined />
            <span>执行计划</span>
          </div>
          <div className="exit-plan-mode-plan-content">
            <ChatMarkdown content={plan} streaming={false} />
          </div>
        </section>
      )}
      <Input.TextArea
        aria-label="告诉 Claude 如何继续规划"
        autoSize={{ minRows: 2, maxRows: 4 }}
        disabled={disabled}
        maxLength={20_000}
        onChange={(event) => setFeedback(event.target.value)}
        placeholder="如需调整，请告诉 Claude 还要补充或修改什么（可选）"
        value={feedback}
      />
      <div className="exit-plan-mode-footer">
        <span>填写反馈后选择“继续规划”，Claude 会按你的要求修改方案。</span>
        <div className="tool-permission-actions">
          {onStop && (
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
            disabled={disabled}
            loading={decision === "deny"}
            onClick={() => void onDecision(false, feedback)}
          >
            {feedback.trim() ? "发送反馈并继续规划" : "继续规划"}
          </Button>
          <Button
            disabled={disabled}
            loading={decision === "allow"}
            onClick={() => void onDecision(true)}
            type="primary"
          >
            执行计划
          </Button>
        </div>
      </div>
    </section>
  );
}
