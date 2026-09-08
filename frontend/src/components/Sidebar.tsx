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
import { useEffect, useState } from "react";

import { BrandMark } from "./BrandMark";

const navigation: MenuProps["items"] = [
  { key: "new", icon: <PlusCircleOutlined />, label: "新建任务" },
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

const tasks = ["整理产品需求", "设计本周工作计划", "分析用户反馈", "准备项目周报"];

type SidebarProps = {
  onCollapse: () => void;
  onNewTask: () => void;
  onSettingsClick: () => void;
  mode?: "workspace" | "settings";
  activeSettingsSection?: string;
  onSettingsSectionChange?: (section: string) => void;
  onBackToWorkspace?: () => void;
};

export function Sidebar({
  onCollapse,
  onNewTask,
  onSettingsClick,
  mode = "workspace",
  activeSettingsSection = "model",
  onSettingsSectionChange,
  onBackToWorkspace,
}: SidebarProps) {
  const inSettings = mode === "settings";
  const [openKeys, setOpenKeys] = useState<string[]>(["basic"]);

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
            <div className="project-heading">
              <span>项目</span>
              <FolderOpenOutlined />
            </div>
            <button className="project-row" type="button"><span className="project-dot" />未打开项目</button>
            <div className="project-heading task-heading"><span>最近任务</span><ClockCircleOutlined /></div>
            <div className="task-list">
              {tasks.map((task) => <button key={task} className="task-row" type="button">{task}</button>)}
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
