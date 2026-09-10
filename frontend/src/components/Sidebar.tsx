import {
  AppstoreOutlined,
  ArrowLeftOutlined,
  ClockCircleOutlined,
  FolderOpenOutlined,
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

import type { ChatSessionSummary } from "../bridge/client";
import { BrandMark } from "./BrandMark";

const navigation: MenuProps["items"] = [
  { key: "search", icon: <SearchOutlined />, label: "搜索" },
  { key: "automation", icon: <ThunderboltOutlined />, label: "自动化" },
  { key: "plugins", icon: <AppstoreOutlined />, label: "插件市场" },
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

function AutoScrollText({ className = "", text }: AutoScrollTextProps) {
  const containerRef = useRef<HTMLSpanElement>(null);
  const [scrollDistance, setScrollDistance] = useState(0);

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const updateScrollDistance = () => {
      setScrollDistance(Math.max(0, container.scrollWidth - container.clientWidth));
    };

    updateScrollDistance();
    const resizeObserver = new ResizeObserver(updateScrollDistance);
    resizeObserver.observe(container);
    return () => resizeObserver.disconnect();
  }, [text]);

  const style = {
    "--sidebar-scroll-distance": scrollDistance,
    "--sidebar-scroll-duration": `${Math.max(2.4, scrollDistance / 32).toFixed(2)}s`,
  } as CSSProperties;

  return (
    <span
      ref={containerRef}
      className={`auto-scroll-text${scrollDistance > 1 ? " auto-scroll-text-overflowing" : ""}${
        className ? ` ${className}` : ""
      }`}
    >
      <span className="auto-scroll-text-inner" style={style}>
        {text}
      </span>
    </span>
  );
}

type SidebarProps = {
  activeSessionId?: string | null;
  onCollapse: () => void;
  onHistorySessionClick?: (sessionId: string) => void;
  onNewTask: () => void;
  onSettingsClick: () => void;
  mode?: "workspace" | "settings";
  activeSettingsSection?: string;
  onSettingsSectionChange?: (section: string) => void;
  onBackToWorkspace?: () => void;
  sessions?: ChatSessionSummary[];
  sessionsLoading?: boolean;
};

export function Sidebar({
  activeSessionId = null,
  onCollapse,
  onHistorySessionClick,
  onNewTask,
  onSettingsClick,
  mode = "workspace",
  activeSettingsSection = "model",
  onSettingsSectionChange,
  onBackToWorkspace,
  sessions = [],
  sessionsLoading = false,
}: SidebarProps) {
  const inSettings = mode === "settings";
  const [openKeys, setOpenKeys] = useState<string[]>(["basic"]);
  const [openProjectKeys, setOpenProjectKeys] = useState<Set<string>>(new Set());
  const sessionGroups = useMemo(() => {
    const grouped = new Map<string, ChatSessionSummary[]>();
    for (const session of sessions) {
      const key = session.project_path || "__unknown_project__";
      const group = grouped.get(key) ?? [];
      group.push(session);
      grouped.set(key, group);
    }
    return [...grouped.entries()].map(([key, groupSessions]) => ({
      key,
      name: groupSessions[0].project_name,
      path: groupSessions[0].project_path,
      sessions: groupSessions,
    }));
  }, [sessions]);

  useEffect(() => {
    const activeProjectKey = sessions.find(
      (session) => session.session_id === activeSessionId,
    )?.project_path || null;
    setOpenProjectKeys((current) => {
      const next = new Set(current);
      if (!next.size && sessionGroups[0]) {
        next.add(sessionGroups[0].key);
      }
      if (activeProjectKey) {
        next.add(activeProjectKey);
      }
      return next;
    });
  }, [activeSessionId, sessionGroups, sessions]);

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
      <div>
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
              <kbd>Ctrl N</kbd>
            </Button>
            <Menu className="main-menu" mode="inline" selectedKeys={["automation"]} items={navigation} />
          </>
        )}
      </div>

      <div className="sidebar-bottom">
        {!inSettings && (
          <>
            <div className="project-heading task-heading">
              <span>历史会话</span>
              <ClockCircleOutlined />
            </div>
            <div className="task-list">
              {sessionsLoading && (
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
                      const next = new Set(current);
                      if (isOpen) {
                        next.add(group.key);
                      } else {
                        next.delete(group.key);
                      }
                      return next;
                    });
                  }}
                >
                  <summary
                    className="history-project-heading"
                    title={group.path || "未知工作区"}
                  >
                    <FolderOpenOutlined />
                    <span className="history-project-copy">
                      <AutoScrollText className="history-project-name" text={group.name} />
                      <AutoScrollText
                        className="history-project-path"
                        text={group.path || "未知工作区"}
                      />
                    </span>
                    <span className="history-project-count">{group.sessions.length}</span>
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
                        </button>
                      </Tooltip>
                    ))}
                  </div>
                </details>
              ))}
            </div>
          </>
        )}
        <div className="profile-row" onClick={onSettingsClick}>
          <Avatar size={32} className="profile-avatar">L</Avatar>
          <span>luojiaaoo</span>
          <Button type="text" icon={<SettingOutlined />} aria-label="设置" />
        </div>
      </div>
    </aside>
  );
}
