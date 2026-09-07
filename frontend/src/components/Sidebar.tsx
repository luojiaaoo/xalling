import {
  AppstoreOutlined,
  ClockCircleOutlined,
  FolderOpenOutlined,
  MoreOutlined,
  PlusCircleOutlined,
  SearchOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { Avatar, Button, Menu, Tooltip } from "antd";
import type { MenuProps } from "antd";

import { BrandMark } from "./BrandMark";

const navigation: MenuProps["items"] = [
  { key: "new", icon: <PlusCircleOutlined />, label: "新建任务" },
  { key: "search", icon: <SearchOutlined />, label: "搜索" },
  { key: "automation", icon: <ThunderboltOutlined />, label: "自动化" },
  { key: "plugins", icon: <AppstoreOutlined />, label: "插件市场" },
];

const tasks = ["整理产品需求", "设计本周工作计划", "分析用户反馈", "准备项目周报"];

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div>
        <div className="brand-row">
          <BrandMark />
          <span className="brand-name">Xalling</span>
          <Tooltip title="收起侧栏"><Button type="text" icon={<MoreOutlined />} /></Tooltip>
        </div>
        <Button className="new-task-button" icon={<PlusCircleOutlined />} block>
          新建任务
          <kbd>Ctrl N</kbd>
        </Button>
        <Menu className="main-menu" mode="inline" selectedKeys={["automation"]} items={navigation} />
      </div>

      <div className="sidebar-bottom">
        <div className="project-heading">
          <span>项目</span>
          <FolderOpenOutlined />
        </div>
        <button className="project-row" type="button"><span className="project-dot" />未打开项目</button>
        <div className="project-heading task-heading"><span>最近任务</span><ClockCircleOutlined /></div>
        <div className="task-list">
          {tasks.map((task) => <button key={task} className="task-row" type="button">{task}</button>)}
        </div>
        <div className="profile-row">
          <Avatar size={32} className="profile-avatar">L</Avatar>
          <span>luojiaaoo</span>
          <Button type="text" icon={<SettingOutlined />} aria-label="设置" />
        </div>
      </div>
    </aside>
  );
}
