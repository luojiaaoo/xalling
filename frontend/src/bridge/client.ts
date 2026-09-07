export type TaskSubmission = {
  prompt: string;
  projectId?: string;
};

export type TaskResult = {
  id: string;
  status: "queued" | "completed";
  message: string;
};

type PyWebviewApi = {
  submit_task: (submission: TaskSubmission) => Promise<TaskResult>;
  minimize_window: () => Promise<void>;
  toggle_maximize_window: () => Promise<{ maximized: boolean }>;
  close_window: () => Promise<void>;
};

declare global {
  interface Window {
    pywebview?: { api: PyWebviewApi };
  }
}

let bridgeReady = Boolean(window.pywebview?.api);

window.addEventListener("pywebviewready", () => {
  bridgeReady = true;
});

export async function submitTask(submission: TaskSubmission): Promise<TaskResult> {
  const api = window.pywebview?.api;

  if (!bridgeReady || !api) {
    return {
      id: `draft-${Date.now()}`,
      status: "queued",
      message: "桌面桥接尚未就绪，任务已保存在当前演示会话。",
    };
  }

  return api.submit_task(submission);
}

export async function minimizeWindow(): Promise<void> {
  await window.pywebview?.api.minimize_window();
}

export async function toggleMaximizeWindow(): Promise<boolean> {
  const result = await window.pywebview?.api.toggle_maximize_window();
  return result?.maximized ?? false;
}

export async function closeWindow(): Promise<void> {
  await window.pywebview?.api.close_window();
}
