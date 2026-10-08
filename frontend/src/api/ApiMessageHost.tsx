import { App } from "antd";
import { useEffect } from "react";

import { registerApiMessage } from "./apiMessage";

// 挂载在 <AntdApp> 内，把带主题上下文的 message 实例注册给 API 错误提示使用。
export function ApiMessageHost() {
  const { message } = App.useApp();

  useEffect(() => registerApiMessage(message), [message]);

  return null;
}
