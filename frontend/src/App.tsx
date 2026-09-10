import { XProvider } from "@ant-design/x";
import { MenuUnfoldOutlined, PlusCircleOutlined } from "@ant-design/icons";
import { Button, Tooltip } from "antd";
import { useCallback, useEffect, useState } from "react";

import { AppearanceSettings } from "./components/AppearanceSettings";
import { ModelSettings } from "./components/ModelSettings";
import { Sidebar } from "./components/Sidebar";
import { TitleBar } from "./components/TitleBar";
import { WindowResizeHandles } from "./components/WindowResizeHandles";
import { Workspace } from "./components/Workspace";
import {
  getCurrentTheme,
  listChatSessions,
  setCurrentTheme,
  type ChatPermissionMode,
  type ChatSessionSummary,
  type ProjectFolder,
} from "./bridge/client";
import useGeekTheme from "./geekTheme";
import useIllustrationTheme from "./illustrationTheme";
import useSereneTheme from "./sereneTheme";
import { themes, type ThemeName } from "./theme";

const SIDEBAR_AUTO_COLLAPSE_WIDTH = 500;

function isThemeName(value: string): value is ThemeName {
  return (
    value === "default" ||
    value === "dark" ||
    value === "cartoon" ||
    value === "illustration" ||
    value === "geek" ||
    value === "serene"
  );
}

export default function App() {
  const [view, setView] = useState<"workspace" | "settings">("workspace");
  const [settingsSection, setSettingsSection] = useState("model");
  const [themeName, setThemeName] = useState<ThemeName>("default");
  const [sidebarVisible, setSidebarVisible] = useState(true);
  const [workspaceKey, setWorkspaceKey] = useState(0);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  // 提升到 App 层：新建任务（Workspace 重挂载）时保持和当前一致
  const [selectedProject, setSelectedProject] = useState<ProjectFolder | null>(null);
  const [effort, setEffort] = useState(2);
  const [permissionMode, setPermissionMode] = useState<ChatPermissionMode>("default");
  const [chatSessions, setChatSessions] = useState<ChatSessionSummary[]>([]);
  const [chatSessionsLoading, setChatSessionsLoading] = useState(true);
  const [windowMaximized, setWindowMaximized] = useState(false);
  const illustrationTheme = useIllustrationTheme();
  const geekTheme = useGeekTheme();
  const sereneTheme = useSereneTheme();

  const refreshChatSessions = useCallback(() => {
    setChatSessionsLoading(true);
    void listChatSessions()
      .then(setChatSessions)
      .catch(() => setChatSessions([]))
      .finally(() => setChatSessionsLoading(false));
  }, []);

  const configProps =
    themeName === "illustration"
      ? illustrationTheme
      : themeName === "geek"
        ? geekTheme
        : themeName === "serene"
          ? sereneTheme
          : { theme: themes[themeName] };

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
    refreshChatSessions();
  }, [refreshChatSessions]);

  useEffect(() => {
    document.documentElement.dataset.theme = themeName;
    document.documentElement.style.colorScheme =
      themeName === "dark" || themeName === "geek" ? "dark" : "light";
  }, [themeName]);

  useEffect(() => {
    function collapseSidebarOnNarrowWindow() {
      if (window.innerWidth <= SIDEBAR_AUTO_COLLAPSE_WIDTH) {
        setSidebarVisible(false);
      }
    }

    collapseSidebarOnNarrowWindow();
    window.addEventListener("resize", collapseSidebarOnNarrowWindow);
    return () => window.removeEventListener("resize", collapseSidebarOnNarrowWindow);
  }, []);

  function handleThemeChange(next: ThemeName) {
    setThemeName(next);
    void setCurrentTheme(next).catch(() => undefined);
  }

  function handleNewTask() {
    setView("workspace");
    setActiveSessionId(null);
    setWorkspaceKey((key) => key + 1);
  }

  function handleHistorySessionClick(sessionId: string) {
    setView("workspace");
    setActiveSessionId(sessionId);
    setWorkspaceKey((key) => key + 1);
  }

  return (
    <XProvider {...configProps}>
      <div className="desktop-app">
        <TitleBar maximized={windowMaximized} onMaximizedChange={setWindowMaximized} />
        <WindowResizeHandles disabled={windowMaximized} />
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
              activeSessionId={activeSessionId}
              mode={view}
              onCollapse={() => setSidebarVisible(false)}
              onHistorySessionClick={handleHistorySessionClick}
              onNewTask={handleNewTask}
              onSettingsClick={() =>
                setView((currentView) => currentView === "settings" ? "workspace" : "settings")
              }
              activeSettingsSection={settingsSection}
              onSettingsSectionChange={setSettingsSection}
              onBackToWorkspace={() => setView("workspace")}
              sessions={chatSessions}
              sessionsLoading={chatSessionsLoading}
            />
          )}
          <Workspace
            key={workspaceKey}
            effort={effort}
            hidden={view === "settings"}
            initialSessionId={activeSessionId}
            onEffortChange={setEffort}
            onPermissionModeChange={setPermissionMode}
            onProjectChange={setSelectedProject}
            onSessionsChanged={refreshChatSessions}
            permissionMode={permissionMode}
            selectedProject={selectedProject}
          />
          {view === "settings" && (
            settingsSection === "theme" ? (
              <AppearanceSettings themeName={themeName} onThemeChange={handleThemeChange} />
            ) : (
              <ModelSettings section={settingsSection} />
            )
          )}
        </div>
      </div>
    </XProvider>
  );
}
