import {
  CalendarOutlined,
  ClockCircleOutlined,
  FolderOpenOutlined,
  ReloadOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { Button, Empty, Modal, Spin } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  getHomeFolder,
  listAllScheduledTasks,
  type ScheduledTaskSummary,
} from "../bridge/client";

const scheduleTypeLabels: Record<ScheduledTaskSummary["schedule_type"], string> = {
  interval: "周期任务",
  date: "一次性任务",
  cron: "Cron 任务",
};

const permissionModeLabels: Record<string, string> = {
  default: "变更前确认",
  acceptEdits: "自动编辑",
  plan: "计划模式",
  auto: "帮我批准",
  bypassPermissions: "完全访问",
};

function formatDateTime(value: string | null): string {
  if (!value) {
    return "暂无下次执行";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function workspaceName(path: string | null): string {
  return path?.split(/[\\/]/).filter(Boolean).at(-1) ?? "默认工作区";
}

type AutomationProps = {
  onClose: () => void;
  open: boolean;
  projectPath: string | null;
};

export function Automation({ onClose, open, projectPath }: AutomationProps) {
  const [currentWorkspacePath, setCurrentWorkspacePath] = useState(projectPath);
  const [tasks, setTasks] = useState<ScheduledTaskSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [workspaceFilter, setWorkspaceFilter] = useState(projectPath ?? "");
  const requestIdRef = useRef(0);

  useEffect(() => {
    if (projectPath) {
      setCurrentWorkspacePath(projectPath);
      return;
    }
    let active = true;
    void getHomeFolder().then((folder) => {
      if (active) {
        setCurrentWorkspacePath(folder?.path ?? null);
      }
    });
    return () => {
      active = false;
    };
  }, [projectPath]);

  useEffect(() => {
    setWorkspaceFilter(currentWorkspacePath ?? "");
  }, [currentWorkspacePath]);

  const refresh = useCallback(async (showLoading: boolean) => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    if (showLoading) {
      setLoading(true);
    }
    try {
      const nextTasks = await listAllScheduledTasks();
      if (requestId === requestIdRef.current) {
        setTasks(nextTasks);
        setError(null);
      }
    } catch (reason) {
      if (requestId === requestIdRef.current) {
        setError(reason instanceof Error ? reason.message : "任务查询失败");
      }
    } finally {
      if (showLoading && requestId === requestIdRef.current) {
        setLoading(false);
      }
    }
  }, [projectPath]);

  const workspacePaths = [...new Set(tasks.map((task) => task.workspace_path))].sort();
  const visibleTasks = workspaceFilter
    ? tasks.filter((task) => task.workspace_path === workspaceFilter)
    : tasks;

  useEffect(() => {
    if (!open) {
      return;
    }
    void refresh(true);
  }, [open, refresh]);

  return (
    <Modal
      className="automation-modal"
      destroyOnHidden
      footer={null}
      open={open}
      title="自动化任务"
      width={820}
      onCancel={onClose}
    >
      <div className="automation-content">
      <div className="automation-title-row">
        <div className="automation-title">
          <span className="automation-kicker">自动化</span>
          <h1>定时任务</h1>
          <p title={currentWorkspacePath ?? undefined}>
            当前工作区：{workspaceName(currentWorkspacePath)}
          </p>
        </div>
        <div className="automation-title-actions">
          <select
            aria-label="筛选工作区"
            className="automation-workspace-filter"
            value={workspaceFilter}
            onChange={(event) => setWorkspaceFilter(event.target.value)}
          >
            <option value="">全部工作区</option>
            {workspacePaths.map((path) => (
              <option key={path} value={path}>{workspaceName(path)}</option>
            ))}
          </select>
          <Button
            aria-label="刷新定时任务"
            icon={<ReloadOutlined />}
            loading={loading}
            title="刷新定时任务"
            type="text"
            onClick={() => void refresh(true)}
          />
        </div>
      </div>

      {error && <div className="automation-error" role="alert">{error}</div>}

      {loading && !tasks.length ? (
        <div className="automation-status"><Spin size="large" /></div>
      ) : visibleTasks.length === 0 ? (
        <div className="automation-status">
          <Empty description={tasks.length ? "当前筛选条件下暂无定时任务" : "暂无定时任务"} />
        </div>
      ) : (
        <div className="automation-task-list">
          {visibleTasks.map((task) => (
            <article className="automation-task-card" key={task.task_id}>
              <div className="automation-task-heading">
                <div className="automation-task-title-wrap">
                  <ThunderboltOutlined className="automation-task-icon" />
                  <div>
                    <h2>{task.title}</h2>
                    <span className="automation-task-id">{task.task_id}</span>
                  </div>
                </div>
                <span className="automation-task-type">
                  {scheduleTypeLabels[task.schedule_type]}
                </span>
              </div>
              <p className="automation-task-prompt">{task.prompt}</p>
              <div className="automation-task-meta">
                <span title={task.workspace_path}>
                  <FolderOpenOutlined />
                  {workspaceName(task.workspace_path)}
                </span>
                <span>
                  <SettingOutlined />
                  权限模式：{permissionModeLabels[task.permission_mode] ?? task.permission_mode}
                </span>
                <span>
                  <CalendarOutlined />
                  {task.schedule_value}
                </span>
                <span>
                  <ClockCircleOutlined />
                  下次执行：{formatDateTime(task.next_run_time)}
                </span>
              </div>
            </article>
          ))}
        </div>
      )}
      </div>
    </Modal>
  );
}
