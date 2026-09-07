import { CloseOutlined, FullscreenOutlined, MinusOutlined, ShrinkOutlined } from "@ant-design/icons";
import { Button } from "antd";
import { useState } from "react";

import { closeWindow, minimizeWindow, toggleMaximizeWindow } from "../bridge/client";

export function TitleBar() {
  const [maximized, setMaximized] = useState(false);

  const handleMaximize = async () => {
    setMaximized(await toggleMaximizeWindow());
  };

  return (
    <header className="title-bar">
      <div
        className="title-bar-drag pywebview-drag-region"
        onDoubleClick={() => void handleMaximize()}
      />
      <div className="window-controls" aria-label="窗口控制">
        <Button type="text" icon={<MinusOutlined />} onClick={() => void minimizeWindow()} aria-label="最小化" />
        <Button
          type="text"
          icon={maximized ? <ShrinkOutlined /> : <FullscreenOutlined />}
          onClick={() => void handleMaximize()}
          aria-label={maximized ? "还原窗口" : "最大化窗口"}
        />
        <Button
          type="text"
          className="close-window-button"
          icon={<CloseOutlined />}
          onClick={() => void closeWindow()}
          aria-label="关闭窗口"
        />
      </div>
    </header>
  );
}
