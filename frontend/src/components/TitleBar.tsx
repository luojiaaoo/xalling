import { CloseOutlined, FullscreenOutlined, MinusOutlined, ShrinkOutlined } from "@ant-design/icons";
import { Button } from "antd";

import { closeWindow, minimizeWindow, toggleMaximizeWindow } from "../api/client";
import { TutorialHelp } from "./TutorialHelp";

type TitleBarProps = {
  nativeWindowAvailable: boolean;
  maximized: boolean;
  onMaximizedChange: (maximized: boolean) => void;
};

export function TitleBar({ maximized, onMaximizedChange, nativeWindowAvailable }: TitleBarProps) {
  const handleMaximize = async () => {
    onMaximizedChange(await toggleMaximizeWindow());
  };

  return (
    <header className="title-bar">
      <div
        className={`title-bar-drag${nativeWindowAvailable && !maximized ? " pywebview-drag-region" : ""}`}
        onDoubleClick={nativeWindowAvailable ? () => void handleMaximize() : undefined}
      />
      <div className="window-controls" aria-label="窗口控制">
        <TutorialHelp />
        {nativeWindowAvailable && (
          <>
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
          </>
        )}
      </div>
    </header>
  );
}
