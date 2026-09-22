"""UI theme persistence behind the bridge."""

from backend.config.current import CurrentConfig

THEME_NAMES = ("default", "dark", "cartoon", "illustration", "geek", "serene")


class ThemeService:
    """Read and persist the UI theme selected in the desktop app."""

    @staticmethod
    def get_current_theme() -> str:
        """Return the persisted theme name, defaulting to the light theme."""
        theme = CurrentConfig().theme.name
        return theme if theme in THEME_NAMES else "default"

    @staticmethod
    def set_current_theme(name: str) -> None:
        """Validate and persist the theme chosen from the settings screen."""
        if not isinstance(name, str):
            raise TypeError("主题名称必须是字符串")
        if name not in THEME_NAMES:
            raise ValueError("不支持的主题")

        current = CurrentConfig()
        current.theme.name = name
        current.write()
