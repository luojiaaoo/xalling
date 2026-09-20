import { XProvider } from "@ant-design/x";
import { MenuUnfoldOutlined, PlusCircleOutlined } from "@ant-design/icons";
import { Button, Tooltip } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";

import { AppearanceSettings } from "./components/AppearanceSettings";
import { ModelSettings } from "./components/ModelSettings";
import { SearchPalette } from "./components/SearchPalette";
import { Sidebar } from "./components/Sidebar";
import { TitleBar } from "./components/TitleBar";
import { WindowResizeHandles } from "./components/WindowResizeHandles";
import { Workspace } from "./components/Workspace";
import {
  getCurrentTheme,
  listChatSessions,
  setChatPermissionMode,
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
  const [modelsRevision, setModelsRevision] = useState(0);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  // The sidebar selection may change while the current workspace keeps running.
  // Keep the session used to initialise Workspace separate so selecting the
  // newly-created history row does not make Workspace reload its own history.
  const [workspaceSessionId, setWorkspaceSessionId] = useState<string | null>(null);
  const [projectExpansionRequest, setProjectExpansionRequest] = useState<{
    path: string;
    sequence: number;
  } | null>(null);
  // 搜索跳转目标：打开会话后要滚动置顶的消息气泡（后端消息 key）
  const [focusMessageKey, setFocusMessageKey] = useState<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  // 提升到 App 层：新建任务（Workspace 重挂载）时保持和当前一致
  const [selectedProject, setSelectedProject] = useState<ProjectFolder | null>(null);
  const [effort, setEffort] = useState(2);
  const [permissionMode, setPermissionMode] = useState<ChatPermissionMode>("default");
  const permissionModeRequestRef = useRef(0);
  const [chatSessions, setChatSessions] = useState<ChatSessionSummary[]>([]);
  const [chatSessionsLoading, setChatSessionsLoading] = useState(true);
  const chatSessionsRequestIdRef = useRef(0);
  const [windowMaximized, setWindowMaximized] = useState(false);
  const illustrationTheme = useIllustrationTheme();
  const geekTheme = useGeekTheme();
  const sereneTheme = useSereneTheme();

  const refreshChatSessions = useCallback((showLoading = false) => {
    const requestId = chatSessionsRequestIdRef.current + 1;
    chatSessionsRequestIdRef.current = requestId;
    if (showLoading) {
      setChatSessionsLoading(true);
    }
    void listChatSessions()
      .then((sessions) => {
        if (requestId === chatSessionsRequestIdRef.current) {
          setChatSessions(sessions);
        }
      })
      .catch(() => {
        if (showLoading && requestId === chatSessionsRequestIdRef.current) {
          setChatSessions([]);
        }
      })
      .finally(() => {
        if (requestId === chatSessionsRequestIdRef.current) {
          setChatSessionsLoading(false);
        }
      });
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
    refreshChatSessions(true);
  }, [refreshChatSessions]);

  const hasRunningSession = chatSessions.some((session) => session.running);

  useEffect(() => {
    if (!hasRunningSession) {
      return undefined;
    }

    const pollRunningSessions = () => {
      if (document.visibilityState === "visible") {
        refreshChatSessions(false);
      }
    };
    const intervalId = window.setInterval(pollRunningSessions, 1_000);
    document.addEventListener("visibilitychange", pollRunningSessions);
    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener("visibilitychange", pollRunningSessions);
    };
  }, [hasRunningSession, refreshChatSessions]);

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

  // Ctrl/Cmd + K 打开搜索面板
  useEffect(() => {
    function openSearchOnShortcut(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
      }
    }

    window.addEventListener("keydown", openSearchOnShortcut);
    return () => window.removeEventListener("keydown", openSearchOnShortcut);
  }, []);

  function handleThemeChange(next: ThemeName) {
    setThemeName(next);
    void setCurrentTheme(next).catch(() => undefined);
  }

  const handlePermissionModeChange = useCallback((
    nextMode: ChatPermissionMode,
    sessionId: string,
  ) => {
    const previousMode = permissionMode;
    const requestId = permissionModeRequestRef.current + 1;
    permissionModeRequestRef.current = requestId;
    setPermissionMode(nextMode);
    void setChatPermissionMode(sessionId, nextMode).catch(() => {
      // Do not let a failed live update affect the mode used by the next turn.
      if (permissionModeRequestRef.current === requestId) {
        setPermissionMode(previousMode);
      }
    });
  }, [permissionMode]);

  const handlePermissionModeObserved = useCallback((nextMode: ChatPermissionMode) => {
    // The SDK status event is authoritative; invalidate any optimistic mode
    // update that is still waiting for a bridge response.
    permissionModeRequestRef.current += 1;
    setPermissionMode(nextMode);
  }, []);

  function handleNewTask() {
    setView("workspace");
    setActiveSessionId(null);
    setWorkspaceSessionId(null);
    setFocusMessageKey(null);
    setWorkspaceKey((key) => key + 1);
  }

  // 侧栏项目快捷按钮：以该项目为工作区开一个新任务，不选中任何历史会话
  function handleProjectTask(project: ProjectFolder) {
    setView("workspace");
    setSelectedProject(project.path ? project : null);
    setActiveSessionId(null);
    setWorkspaceSessionId(null);
    setFocusMessageKey(null);
    setWorkspaceKey((key) => key + 1);
  }

  function handleHistorySessionClick(sessionId: string) {
    setView("workspace");
    setActiveSessionId(sessionId);
    setWorkspaceSessionId(sessionId);
    setFocusMessageKey(null);
    setWorkspaceKey((key) => key + 1);
  }

  function handleConversationStart(project: ProjectFolder | null, sessionId: string) {
    setActiveSessionId(sessionId);
    if (!project?.path) {
      return;
    }
    setProjectExpansionRequest((current) => ({
      path: project.path,
      sequence: (current?.sequence ?? 0) + 1,
    }));
  }

  // 搜索结果：打开对应会话，并把它命中的消息气泡滚动置顶
  function handleSearchResultOpen(sessionId: string, messageKey: string | null) {
    setView("workspace");
    setActiveSessionId(sessionId);
    setWorkspaceSessionId(sessionId);
    setFocusMessageKey(messageKey);
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
              projectExpansionRequest={projectExpansionRequest}
              mode={view}
              onCollapse={() => setSidebarVisible(false)}
              onHistorySessionClick={handleHistorySessionClick}
              onNewTask={handleNewTask}
              onProjectTask={handleProjectTask}
              onSearchClick={() => setSearchOpen(true)}
              searchActive={searchOpen}
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
            focusMessageKey={focusMessageKey}
            hidden={view === "settings"}
            initialSessionId={workspaceSessionId}
            modelsRevision={modelsRevision}
            onEffortChange={setEffort}
            onPermissionModeChange={handlePermissionModeChange}
            onPermissionModeObserved={handlePermissionModeObserved}
            onConversationStart={handleConversationStart}
            onProjectChange={setSelectedProject}
            onSessionsChanged={refreshChatSessions}
            permissionMode={permissionMode}
            selectedProject={selectedProject}
          />
          {view === "settings" && (
            settingsSection === "theme" ? (
              <AppearanceSettings themeName={themeName} onThemeChange={handleThemeChange} />
            ) : (
              <ModelSettings
                section={settingsSection}
                onModelsChanged={() => setModelsRevision((revision) => revision + 1)}
              />
            )
          )}
        </div>
        {searchOpen && (
          <SearchPalette
            currentSessionId={activeSessionId}
            onClose={() => setSearchOpen(false)}
            onOpenResult={(sessionId, messageKey) => {
              setSearchOpen(false);
              handleSearchResultOpen(sessionId, messageKey);
            }}
          />
        )}
      </div>
    </XProvider>
  );
}
