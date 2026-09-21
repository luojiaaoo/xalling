"""py2js 统一入口：Python 执行 JS 出错时通过前端 message 组件提示。"""

import json
from typing import Any

from webview.errors import JavascriptException, WebViewException
from webview.window import Window

# 前端在 main.tsx 中通过 installPy2JsErrorNotifier 安装的全局钩子
_NOTIFY_HOOK = "window.__xallingNotifyPy2JsError"


def evaluate_js(window: Window, script: str, *, action: str) -> Any:
    """执行 JS 脚本；失败时先通过前端 message 提示异常，再原样抛出。

    异常继续抛出是为了保留调用方原有的错误处理逻辑。
    """
    try:
        return window.evaluate_js(script)
    except (JavascriptException, WebViewException) as exc:
        _notify_frontend_error(window, action, exc)
        raise


def _notify_frontend_error(window: Window, action: str, error: Exception) -> None:
    notify_script = (
        f"{_NOTIFY_HOOK}?.("
        f"{json.dumps(action)},{json.dumps(str(error))}"
        ");"
    )
    try:
        window.evaluate_js(notify_script)
    except (JavascriptException, WebViewException):
        # 提示通道本身不可用时静默放弃，避免异常循环
        pass
