import { BugOutlined, CalendarOutlined, DesktopOutlined, MoonOutlined } from "@ant-design/icons";
import { Button } from "antd";

const actions = [
  { label: "周报总结", icon: <CalendarOutlined /> },
  { label: "报错修复", icon: <BugOutlined /> },
  { label: "PPT 制作", icon: <DesktopOutlined /> },
  { label: "闲时任务", icon: <MoonOutlined /> },
];

type QuickActionsProps = {
  onSelect: (label: string) => void;
};

export function QuickActions({ onSelect }: QuickActionsProps) {
  return (
    <div className="quick-actions" aria-label="快捷任务">
      {actions.map(({ label, icon }) => (
        <Button key={label} icon={icon} onClick={() => onSelect(label)}>{label}</Button>
      ))}
    </div>
  );
}
