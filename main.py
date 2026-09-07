from pathlib import Path
from typing import Any

import webview


class ApplicationBridge:
    """Small, JSON-only API exposed to the local Web UI."""

    def submit_task(self, submission: dict[str, Any]) -> dict[str, str]:
        """Validate a task request received through pywebview's JS bridge."""
        prompt = submission.get("prompt") if isinstance(submission, dict) else None
        if not isinstance(prompt, str):
            raise TypeError("任务内容必须是文本")

        prompt = prompt.strip()
        if not prompt:
            raise ValueError("任务内容不能为空")
        if len(prompt) > 4_000:
            raise ValueError("任务内容不能超过 4000 个字符")

        # The agent workflow will be scheduled here in a later iteration.
        return {
            "id": "local-task",
            "status": "queued",
            "message": "任务已加入本地工作队列",
        }


def main() -> None:
    """Launch the desktop shell."""
    index_file = Path(__file__).parent / "frontend" / "dist" / "index.html"
    if not index_file.is_file():
        message = "找不到前端构建产物。请先在 frontend 目录执行 npm run build。"
        raise FileNotFoundError(message)

    webview.create_window(
        "Xalling",
        url=index_file.resolve().as_uri(),
        js_api=ApplicationBridge(),
        width=1280,
        height=820,
        min_size=(1050, 680),
    )
    webview.start()


if __name__ == "__main__":
    main()
