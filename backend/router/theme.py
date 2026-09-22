"""Theme-related methods exposed to the local Web UI."""

from backend.service.theme import ThemeService


class ThemeRouter:
    """Read and persist the UI theme selected in the desktop app."""

    def get_current_theme(self) -> str:
        """Return the persisted theme name, defaulting to the light theme."""
        return ThemeService.get_current_theme()

    def set_current_theme(self, name: str) -> None:
        """Validate and persist the theme chosen from the settings screen."""
        ThemeService.set_current_theme(name)
