import { ConfigProvider } from "antd";

import { Sidebar } from "./components/Sidebar";
import { Workspace } from "./components/Workspace";

const theme = {
  token: {
    colorPrimary: "#6d5dfc",
    colorInfo: "#6d5dfc",
    colorText: "#20212b",
    colorTextSecondary: "#77798c",
    colorBgBase: "#f7f7fb",
    colorBorder: "#e7e7f0",
    borderRadius: 12,
    fontFamily: "Inter, 'PingFang SC', 'Microsoft YaHei', sans-serif",
  },
};

export default function App() {
  return (
    <ConfigProvider theme={theme}>
      <div className="app-shell">
        <Sidebar />
        <Workspace />
      </div>
    </ConfigProvider>
  );
}
