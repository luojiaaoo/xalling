import { CheckCircleOutlined, ExclamationCircleOutlined } from "@ant-design/icons";
import { Button } from "antd";

import { closeWindow, type ShutdownState } from "../api/client";

export function ShutdownScreen({ state }: { state: ShutdownState }) {
  return (
    <main className="shutdown-screen" role="status" aria-live="polite">
      {state.phase === "failed" ? (
        <>
          <ExclamationCircleOutlined className="shutdown-error" />
          <h1>关闭失败</h1>
          <p>{state.error}</p>
          <Button onClick={() => void closeWindow()}>重试关闭</Button>
        </>
      ) : (
        <>
          <CheckCircleOutlined className="shutdown-success" />
          <h1>已关闭</h1>
          <p>可以关闭此页面了</p>
        </>
      )}
    </main>
  );
}
