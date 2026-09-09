import { theme } from "antd";
import type { ThemeConfig } from "antd";

export type ThemeName =
  | "default"
  | "dark"
  | "cartoon"
  | "illustration"
  | "geek"
  | "serene";
export type StaticThemeName = Exclude<ThemeName, "illustration" | "geek" | "serene">;

const fontFamily = "Inter, 'PingFang SC', 'Microsoft YaHei', sans-serif";

/** 不需要组件级样式增强的基础主题。 */
export const themes: Record<StaticThemeName, ThemeConfig> = {
  default: {
    token: {
      colorPrimary: "#6d5dfc",
      colorInfo: "#6d5dfc",
      colorText: "#20212b",
      colorTextSecondary: "#77798c",
      colorBgBase: "#f7f7fb",
      colorBorder: "#e7e7f0",
      borderRadius: 12,
      fontFamily,
    },
  },
  dark: {
    algorithm: theme.darkAlgorithm,
    token: {
      colorPrimary: "#6d5dfc",
      colorInfo: "#6d5dfc",
      borderRadius: 12,
      fontFamily,
    },
    components: {
      Layout: {
        bodyBg: "#050505",
        footerBg: "#050505",
        headerBg: "#111111",
        headerColor: "rgba(255, 255, 255, 0.88)",
        siderBg: "#050505",
        triggerBg: "#111111",
        triggerColor: "rgba(255, 255, 255, 0.88)",
      },
      Menu: {
        darkItemBg: "transparent",
        darkItemColor: "rgba(255, 255, 255, 0.68)",
        darkItemHoverBg: "rgba(255, 255, 255, 0.08)",
        darkItemHoverColor: "#fff",
        darkItemSelectedBg: "rgba(109, 93, 252, 0.28)",
        darkItemSelectedColor: "#fff",
        darkSubMenuItemBg: "transparent",
      },
    },
  },
  cartoon: {
    algorithm: theme.defaultAlgorithm,
    token: {
      colorText: "#51463B",
      colorPrimary: "#225555",
      colorError: "#DA8787",
      colorInfo: "#9CD3D3",
      colorInfoBorder: "#225555",
      colorBorder: "#225555",
      colorBorderSecondary: "#88BBBB",
      lineWidth: 2,
      lineWidthBold: 2,
      borderRadius: 18,
      borderRadiusLG: 18,
      borderRadiusSM: 18,
      controlHeightSM: 28,
      controlHeight: 36,
      colorBgBase: "#FAFAEE",
      fontFamily,
    },
    components: {
      Button: {
        primaryShadow: "none",
        dangerShadow: "none",
        defaultShadow: "none",
      },
      Modal: {
        boxShadow: "none",
      },
      Card: {
        colorBgContainer: "#BBAA99",
      },
      Tooltip: {
        borderRadius: 6,
        colorBorder: "#225555",
        algorithm: true,
      },
      Select: {
        optionSelectedBg: "#CBC4AF",
      },
      Notification: {
        colorSuccessBg: "#E0EECF",
        colorErrorBg: "#F3D0C8",
        colorInfoBg: "#D9EEEE",
        colorWarningBg: "#FFF1B8",
      },
      Layout: {
        bodyBg: "#FAFAEE",
        footerBg: "#FAFAEE",
        headerBg: "#F6D878",
        headerColor: "#51463B",
        siderBg: "#F5E8C0",
        triggerBg: "#E8D29A",
        triggerColor: "#51463B",
      },
      Menu: {
        activeBarBorderWidth: 0,
        itemBg: "transparent",
        subMenuItemBg: "transparent",
      },
      Progress: {
        circleTextColor: "#51463B",
        defaultColor: "#225555",
        remainingColor: "#CBC4AF",
      },
    },
  },
};
