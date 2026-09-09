import { CloseOutlined, FullscreenOutlined, MinusOutlined, ShrinkOutlined } from "@ant-design/icons";
import { Button } from "antd";

import { closeWindow, minimizeWindow, toggleMaximizeWindow } from "../bridge/client";

type TitleBarProps = {
  maximized: boolean;
  onMaximizedChange: (maximized: boolean) => void;
};

export function TitleBar({ maximized, onMaximizedChange }: TitleBarProps) {
  const handleMaximize = async () => {
    onMaximizedChange(await toggleMaximizeWindow());
  };

  return (
    <header className="title-bar">
      <div
        className={`title-bar-drag${maximized ? "" : " pywebview-drag-region"}`}
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
