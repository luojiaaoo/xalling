import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  FolderOpenOutlined,
  HomeOutlined,
  MenuFoldOutlined,
  PlusCircleOutlined,
  SearchOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { Avatar, Button, Menu, Tooltip } from "antd";
import type { MenuProps } from "antd";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";

import type { ChatSessionSummary, ProjectFolder } from "../bridge/client";
import { getHomeFolder } from "../bridge/client";
import { BrandMark } from "./BrandMark";

const navigation: MenuProps["items"] = [
  {
    key: "search",
    icon: <SearchOutlined />,
    label: (
      <span className="menu-label">
        <span>搜索</span>
        <kbd className="menu-shortcut">Ctrl K</kbd>
      </span>
    ),
  },
  { key: "automation", icon: <ThunderboltOutlined />, label: "自动化" },
];

const settingsNavigation: MenuProps["items"] = [
  {
    key: "basic",
    label: "基础设置",
    children: [
      { key: "model", label: "模型设置" },
      { key: "theme", label: "主题设置" },
    ],
  },
];

/** 设置分区所属的分组，用于决定侧栏默认展开哪个目录。 */
const sectionGroups: Record<string, string> = {
  model: "basic",
  theme: "basic",
};

type AutoScrollTextProps = {
  className?: string;
  text: string;
};

const SIDEBAR_SCROLL_GAP = 24;
const SIDEBAR_SCROLL_SPEED = 32;

function AutoScrollText({ className = "", text }: AutoScrollTextProps) {
  const containerRef = useRef<HTMLSpanElement>(null);
  const textRef = useRef<HTMLSpanElement>(null);
  const [scrollDistance, setScrollDistance] = useState(0);

  useLayoutEffect(() => {
    const container = containerRef.current;
    const textElement = textRef.current;
    if (!container || !textElement) return;

    const updateScrollDistance = () => {
      const contentWidth = textElement.scrollWidth;
      const overflowing = contentWidth - container.clientWidth > 1;
      setScrollDistance(overflowing ? contentWidth + SIDEBAR_SCROLL_GAP : 0);
    };

    updateScrollDistance();
    const resizeObserver = new ResizeObserver(updateScrollDistance);
    resizeObserver.observe(container);
    return () => resizeObserver.disconnect();
  }, [text]);

  const style = {
    "--sidebar-scroll-distance": scrollDistance,
    "--sidebar-scroll-gap": `${SIDEBAR_SCROLL_GAP}px`,
    "--sidebar-scroll-duration": `${(scrollDistance / SIDEBAR_SCROLL_SPEED).toFixed(2)}s`,
  } as CSSProperties;

  return (
    <span
      ref={containerRef}
      className={`auto-scroll-text${scrollDistance > 1 ? " auto-scroll-text-overflowing" : ""}${
        className ? ` ${className}` : ""
      }`}
    >
      <span ref={textRef} className="auto-scroll-text-inner">
        {text}
      </span>
      {scrollDistance > 1 && (
        <span className="auto-scroll-text-track" style={style} aria-hidden="true">
          <span className="auto-scroll-text-copy">{text}</span>
          <span className="auto-scroll-text-copy">{text}</span>
        </span>
      )}
    </span>
  );
}

type SidebarProps = {
  activeSessionId?: string | null;
  projectExpansionRequest?: { path: string; sequence: number } | null;
  onCollapse: () => void;
  onHistorySessionClick?: (sessionId: string) => void;
  onNewTask: () => void;
  onProjectTask?: (project: ProjectFolder) => void;
  onSearchClick?: () => void;
  onSettingsClick: () => void;
  mode?: "workspace" | "settings";
  searchActive?: boolean;
  activeSettingsSection?: string;
  onSettingsSectionChange?: (section: string) => void;
  onBackToWorkspace?: () => void;
  sessions?: ChatSessionSummary[];
  sessionsLoading?: boolean;
};

export function Sidebar({
  activeSessionId = null,
  projectExpansionRequest = null,
  onCollapse,
  onHistorySessionClick,
  onNewTask,
  onProjectTask,
  onSearchClick,
  onSettingsClick,
  mode = "workspace",
  searchActive = false,
  activeSettingsSection = "model",
  onSettingsSectionChange,
  onBackToWorkspace,
  sessions = [],
  sessionsLoading = false,
}: SidebarProps) {
  const inSettings = mode === "settings";
  const [openKeys, setOpenKeys] = useState<string[]>(["basic"]);
  const [openProjectKeys, setOpenProjectKeys] = useState<Set<string>>(new Set());
  const [defaultProjectPath, setDefaultProjectPath] = useState<string | null>(null);

  // 读取默认项目路径，用于把它的分组固定在列表最顶上
  useEffect(() => {
    let active = true;
    void getHomeFolder().then((folder) => {
      if (active) {
        setDefaultProjectPath(folder?.path ?? null);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  const sessionGroups = useMemo(() => {
    const grouped = new Map<string, ChatSessionSummary[]>();
    for (const session of sessions) {
      const key = session.project_path || "__unknown_project__";
      const group = grouped.get(key) ?? [];
      group.push(session);
      grouped.set(key, group);
    }
    const groups = [...grouped.entries()]
      .map(([key, groupSessions]) => {
        const sortedSessions = [...groupSessions].sort(
          (left, right) => right.last_modified - left.last_modified,
        );
        return {
          key,
          lastModified: sortedSessions[0].last_modified,
          name: sortedSessions[0].project_name,
          path: sortedSessions[0].project_path,
          sessions: sortedSessions,
        };
      })
      .sort((left, right) => right.lastModified - left.lastModified);
    // 默认路径的分组永远固定在最顶上，其余仍按最近修改排序
    // （路径已由后端统一归一化，直接比较字符串即可）
    if (defaultProjectPath) {
      const pinnedIndex = groups.findIndex(
        (group) => group.key === defaultProjectPath,
      );
      if (pinnedIndex > 0) {
        groups.unshift(...groups.splice(pinnedIndex, 1));
      }
    }
    return groups;
  }, [defaultProjectPath, sessions]);

  const activeProjectKey =
    sessions.find((session) => session.session_id === activeSessionId)?.project_path || null;

  useEffect(() => {
    if (!activeProjectKey) {
      return;
    }
    setOpenProjectKeys((current) => {
      if (current.size === 1 && current.has(activeProjectKey)) {
        return current;
      }
      return new Set([activeProjectKey]);
    });
  }, [activeProjectKey, activeSessionId]);

  useEffect(() => {
    const projectPath = projectExpansionRequest?.path;
    if (!projectPath) {
      return;
    }
    setOpenProjectKeys((current) => {
      if (current.size === 1 && current.has(projectPath)) {
        return current;
      }
      return new Set([projectPath]);
    });
  }, [projectExpansionRequest]);

  // 选中分区变化时，展开它所属的分组（手风琴：同时只开一个）
  useEffect(() => {
    const group = sectionGroups[activeSettingsSection];
    if (group) {
      setOpenKeys([group]);
    }
  }, [activeSettingsSection]);

  function handleOpenChange(keys: string[]) {
    // 手风琴模式：只保留最后展开的一个分组
    setOpenKeys(keys.length ? [keys[keys.length - 1]] : []);
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-top">
        <div className="brand-row">
          <BrandMark />
          <span className="brand-name">Xalling</span>
          <Tooltip title="收起侧栏">
            <Button
              type="text"
              icon={<MenuFoldOutlined />}
              aria-label="收起侧栏"
              onClick={onCollapse}
            />
          </Tooltip>
        </div>
        {inSettings ? (
          <>
            <Button
              className="back-workspace-button"
              icon={<ArrowLeftOutlined />}
              block
              onClick={onBackToWorkspace}
            >
              返回工作区
            </Button>
            <Menu
              className="main-menu settings-menu"
              mode="inline"
              openKeys={openKeys}
              onOpenChange={handleOpenChange}
              selectedKeys={[activeSettingsSection]}
              onClick={({ key }) => onSettingsSectionChange?.(key)}
              items={settingsNavigation}
            />
          </>
        ) : (
          <>
            <Button className="new-task-button" icon={<PlusCircleOutlined />} block onClick={onNewTask}>
              新建任务
            </Button>
            <Menu
              className="main-menu"
              mode="inline"
              selectedKeys={searchActive ? ["search"] : []}
              onClick={({ key }) => {
                if (key === "search") {
                  onSearchClick?.();
                }
              }}
              items={navigation}
            />
            <div className="task-list">
              {sessionsLoading && !sessions.length && (
                <div className="history-list-status">正在读取…</div>
              )}
              {!sessionsLoading && !sessions.length && (
                <div className="history-list-status">暂无历史会话</div>
              )}
              {sessionGroups.map((group) => (
                <details
                  key={group.key}
                  className="history-project-group"
                  open={openProjectKeys.has(group.key)}
                  onToggle={(event) => {
                    const isOpen = event.currentTarget.open;
                    setOpenProjectKeys((current) => {
                      if (isOpen) {
                        return new Set([group.key]);
                      }
                      if (!current.has(group.key)) {
                        return current;
                      }
                      const next = new Set(current);
                      next.delete(group.key);
                      return next;
                    });
                  }}
                >
                  <summary
                    className="history-project-heading"
                    title={group.path || "未知工作区"}
                  >
                    {group.key === defaultProjectPath ? (
                      <HomeOutlined />
                    ) : (
                      <FolderOpenOutlined />
                    )}
                    <span className="history-project-copy">
                      <AutoScrollText className="history-project-name" text={group.name} />
                      <AutoScrollText
                        className="history-project-path"
                        text={group.path || "未知工作区"}
                      />
                    </span>
                    <span className="history-project-count">{group.sessions.length}</span>
                    <Tooltip title="在此项目新建任务">
                      <button
                        className="history-project-enter"
                        type="button"
                        aria-label={`在 ${group.name} 新建任务`}
                        onClick={(event) => {
                          // 阻止默认行为，避免点击按钮时顺带展开/收起分组
                          event.preventDefault();
                          event.stopPropagation();
                          onProjectTask?.({ name: group.name, path: group.path });
                        }}
                      >
                        <ArrowRightOutlined />
                      </button>
                    </Tooltip>
                  </summary>
                  <div className="history-session-list">
                    {group.sessions.map((session) => (
                      <Tooltip
                        key={session.session_id}
                        placement="right"
                        title={session.title}
                      >
                        <button
                          className={`task-row${
                            session.session_id === activeSessionId
                              ? " task-row-active"
                              : ""
                          }`}
                          type="button"
                          onClick={() => onHistorySessionClick?.(session.session_id)}
                        >
                          <AutoScrollText className="task-row-title" text={session.title} />
                          {session.running && (
                            <span
                              className="session-running-indicator"
                              role="status"
                              aria-label="会话正在运行"
                            />
                          )}
                        </button>
                      </Tooltip>
                    ))}
                  </div>
                </details>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="sidebar-bottom">
        <div className="profile-row" onClick={onSettingsClick}>
          <Avatar size={32} className="profile-avatar">L</Avatar>
          <span>luojiaaoo</span>
          <Button type="text" icon={<SettingOutlined />} aria-label="设置" />
        </div>
      </div>
    </aside>
  );
}
