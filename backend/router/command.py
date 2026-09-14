"""Claude skill methods exposed to the local Web UI."""

from threading import Lock, Thread
from typing import TypedDict
from uuid import uuid4

from backend.chat.client import (
    ClaudeChatConfig,
    get_cached_server_info,
    start_server_info_monitor,
)
from backend.config.current import CurrentConfig
from backend.config.setting import Settings, default_project_folder


class ClaudeSkill(TypedDict):
    """One user or project skill advertised by the Claude runtime."""

    name: str
    description: str
    argument_hint: str
    aliases: list[str]


def _is_skill(name: str, description: str, item: dict[object, object]) -> bool:
    """Identify skills in the runtime's combined slash-command list."""
    item_kind = item.get("kind", item.get("type"))
    if item_kind == "skill":
        return True
    if item_kind == "command":
        return False
    return description.rstrip().endswith("(user)") or name.startswith(
        (".agents:", ".xalling:", "opencode:")
    )


class CommandRouter:
    """Expose cached Claude skills without creating another SDK client."""

    def __init__(self) -> None:
        super().__init__()
        self._server_info_monitor_lock = Lock()
        self._server_info_monitor_thread: Thread | None = None

    def _start_server_info_monitor(self) -> None:
        """Start the application-wide metadata monitor once."""
        with self._server_info_monitor_lock:
            if (
                self._server_info_monitor_thread is not None
                and self._server_info_monitor_thread.is_alive()
            ):
                return
            self._server_info_monitor_thread = start_server_info_monitor(
                self._server_info_config
            )

    @staticmethod
    def _server_info_config() -> ClaudeChatConfig | None:
        """Build monitor configuration from the current provider selection."""
        settings = Settings()
        current = CurrentConfig().model
        selected = next(
            (
                (site, model.name)
                for site in settings.model
                for model in site.models
                if site.name == current.site and model.name == current.name
            ),
            None,
        )
        if selected is None:
            selected = next(
                (
                    (site, model.name)
                    for site in settings.model
                    for model in site.models
                ),
                None,
            )
        if selected is None:
            return None

        site, model_name = selected
        return ClaudeChatConfig(
            api_key=site.api_key,
            api_url=site.api_url,
            effort="low",
            is_new_session=True,
            model=model_name,
            project=default_project_folder(),
            session_id=str(uuid4()),
        )

    def get_commands(self) -> list[ClaudeSkill]:
        """Return the skills from the latest cached Claude server metadata."""
        raw_commands = get_cached_server_info().get("commands", [])
        if not isinstance(raw_commands, list):
            return []

        skills: list[ClaudeSkill] = []
        for item in raw_commands:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                continue

            normalized_name = name.strip()
            raw_description = item.get("description", "")
            description = (
                raw_description if isinstance(raw_description, str) else ""
            )
            if not _is_skill(normalized_name, description, item):
                continue

            raw_argument_hint = item.get("argumentHint", "")
            raw_aliases = item.get("aliases", [])
            skills.append(
                {
                    "name": normalized_name,
                    "description": description,
                    "argument_hint": (
                        raw_argument_hint
                        if isinstance(raw_argument_hint, str)
                        else ""
                    ),
                    "aliases": (
                        [
                            alias.strip()
                            for alias in raw_aliases
                            if isinstance(alias, str) and alias.strip()
                        ]
                        if isinstance(raw_aliases, list)
                        else []
                    ),
                }
            )
        return skills
