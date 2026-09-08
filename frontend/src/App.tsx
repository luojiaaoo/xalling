import { XProvider } from "@ant-design/x";
import { MenuUnfoldOutlined, PlusCircleOutlined } from "@ant-design/icons";
import { Button, Tooltip } from "antd";
import { useEffect, useState } from "react";

import { AppearanceSettings } from "./components/AppearanceSettings";
import { ModelSettings } from "./components/ModelSettings";
import { Sidebar } from "./components/Sidebar";
import { Workspace } from "./components/Workspace";
import { getCurrentTheme, setCurrentTheme } from "./bridge/client";
import { themes, type ThemeName } from "./theme";

function isThemeName(value: string): value is ThemeName {
  return value === "default" || value === "dark" || value === "cartoon";
}

export default function App() {
  const [view, setView] = useState<"workspace" | "settings">("workspace");
  const [settingsSection, setSettingsSection] = useState("model");
  const [themeName, setThemeName] = useState<ThemeName>("default");
  const [sidebarVisible, setSidebarVisible] = useState(true);
  const [workspaceKey, setWorkspaceKey] = useState(0);

  // 启动时从后端读取持久化的主题选择
  useEffect(() => {
    void getCurrentTheme()
      .then((name) => {
        if (isThemeName(name)) {
          setThemeName(name);
        }
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = themeName;
  }, [themeName]);

  function handleThemeChange(next: ThemeName) {
    setThemeName(next);
    void setCurrentTheme(next).catch(() => undefined);
  }

  function handleNewTask() {
    setView("workspace");
    setWorkspaceKey((key) => key + 1);
  }

  return (
    <XProvider theme={themes[themeName]}>
      <div className="desktop-app">
        {!sidebarVisible && (
          <div className="sidebar-collapsed-actions">
            <Tooltip title="展开侧栏">
              <Button
                type="text"
                icon={<MenuUnfoldOutlined />}
                aria-label="展开侧栏"
                onClick={() => setSidebarVisible(true)}
              />
            </Tooltip>
            <Tooltip title="新建任务">
              <Button
                type="text"
                icon={<PlusCircleOutlined />}
                aria-label="新建任务"
                onClick={handleNewTask}
              />
            </Tooltip>
          </div>
        )}
        <div className={`app-shell${sidebarVisible ? "" : " sidebar-collapsed"}`}>
          {sidebarVisible && (
            <Sidebar
              mode={view}
              onCollapse={() => setSidebarVisible(false)}
              onNewTask={handleNewTask}
              onSettingsClick={() => setView("settings")}
              activeSettingsSection={settingsSection}
              onSettingsSectionChange={setSettingsSection}
              onBackToWorkspace={() => setView("workspace")}
            />
          )}
          {view === "settings" ? (
            settingsSection === "theme" ? (
              <AppearanceSettings themeName={themeName} onThemeChange={handleThemeChange} />
            ) : (
              <ModelSettings section={settingsSection} />
            )
          ) : (
            <Workspace key={workspaceKey} />
          )}
        </div>
      </div>
    </XProvider>
  );
}
