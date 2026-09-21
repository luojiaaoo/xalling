import { App } from "antd";
import { useEffect } from "react";

import { registerBridgeMessage } from "./bridgeMessage";

// 挂载在 <AntdApp> 内，把带主题上下文的 message 实例注册给桥接层使用
export function BridgeMessageHost() {
  const { message } = App.useApp();

  useEffect(() => registerBridgeMessage(message), [message]);

  return null;
}
