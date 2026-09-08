import { XProvider } from "@ant-design/x";
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

  return (
    <XProvider theme={themes[themeName]}>
      <div className="desktop-app">
        <div className="app-shell">
          <Sidebar
            mode={view}
            onSettingsClick={() => setView("settings")}
            activeSettingsSection={settingsSection}
            onSettingsSectionChange={setSettingsSection}
            onBackToWorkspace={() => setView("workspace")}
          />
          {view === "settings" ? (
            settingsSection === "theme" ? (
              <AppearanceSettings themeName={themeName} onThemeChange={handleThemeChange} />
            ) : (
              <ModelSettings section={settingsSection} />
            )
          ) : (
            <Workspace />
          )}
        </div>
      </div>
    </XProvider>
  );
}
