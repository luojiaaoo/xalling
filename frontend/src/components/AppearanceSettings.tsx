import { CheckCircleFilled } from "@ant-design/icons";

import type { ThemeName } from "../theme";

const themeOptions: Array<{
  value: ThemeName;
  label: string;
  description: string;
}> = [
  { value: "default", label: "默认主题", description: "清爽的浅色界面" },
  { value: "dark", label: "黑暗主题", description: "深色背景，夜间更护眼" },
  { value: "cartoon", label: "卡通主题", description: "圆润边框，色彩明快" },
  { value: "illustration", label: "插画主题", description: "粗线条与明快配色，活泼醒目" },
  { value: "geek", label: "极客主题", description: "荧光绿终端风格，锐利硬朗" },
  { value: "serene", label: "静谧主题", description: "温润米白与深棕配色，安静克制" },
];

export function AppearanceSettings({
  themeName,
  onThemeChange,
}: {
  themeName: ThemeName;
  onThemeChange: (theme: ThemeName) => void;
}) {
  return (
    <main className="settings-page">
      <div className="settings-title">
        <span className="settings-kicker">基础设置</span>
        <h1>主题设置</h1>
        <p>选择界面主题，切换后立即生效并自动保存。</p>
      </div>

      <div className="theme-options" role="radiogroup" aria-label="主题选择">
        {themeOptions.map((option) => (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={themeName === option.value}
            className={`theme-option ${themeName === option.value ? "theme-option-active" : ""}`}
            onClick={() => onThemeChange(option.value)}
          >
            <span className={`theme-option-swatch theme-swatch-${option.value}`}>
              <span className="theme-swatch-bar theme-swatch-bar-accent" />
              <span className="theme-swatch-bar" />
              <span className="theme-swatch-bar" />
            </span>
            <strong>{option.label}</strong>
            <small>{option.description}</small>
            {themeName === option.value && (
              <CheckCircleFilled className="theme-option-check" />
            )}
          </button>
        ))}
      </div>
    </main>
  );
}
