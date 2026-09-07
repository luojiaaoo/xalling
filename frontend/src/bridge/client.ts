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
