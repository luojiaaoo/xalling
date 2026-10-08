import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "antd/dist/reset.css";
import "./styles.css";
import App from "./App";
import { installErrorReporter } from "./bridge/errorReporter";

// 在 React 渲染之前安装，确保最早期的错误也能捕获
installErrorReporter();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
