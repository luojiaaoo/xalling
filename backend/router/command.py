"""Claude command and skill methods exposed to the local Web UI."""

from typing import Any, TypedDict

ALLOWED_COMMAND_NAMES = frozenset(
    {
        "compact",
        "init",
        "recap",
        "reload-skills",
        "security-review",
        "team-onboarding",
    }
)


class ClaudeCommand(TypedDict):
    """One slash command advertised by the Claude runtime."""

    name: str
    description: str
    argument_hint: str
    aliases: list[str]


def _is_skill(name: str, description: str, item: dict[object, object]) -> bool:
    item_kind = item.get("kind", item.get("type"))
    if item_kind == "skill":
        return True
    if item_kind == "command":
        return False
    return description.rstrip().endswith("(user)") or name.startswith((".agents:", ".xalling:", "opencode:"))


def _get_server_commands(
    server_info: dict[str, Any],
    *,
    skills: bool,
) -> list[ClaudeCommand]:
    """Normalize either skills or regular commands from live server metadata."""
    raw_commands = server_info.get("commands", [])
    if not isinstance(raw_commands, list):
        return []

    commands: list[ClaudeCommand] = []
    for item in raw_commands:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue

        name = name.strip()
        raw_description = item.get("description", "")
        description = raw_description if isinstance(raw_description, str) else ""
        if _is_skill(name, description, item) is not skills:
            continue
        if not skills and name not in ALLOWED_COMMAND_NAMES:
            continue

        argument_hint = item.get("argumentHint", "")
        aliases = item.get("aliases", [])
        commands.append(
            {
                "name": name,
                "description": description,
                "argument_hint": (argument_hint if isinstance(argument_hint, str) else ""),
                "aliases": (
                    [alias.strip() for alias in aliases if isinstance(alias, str) and alias.strip()]
                    if isinstance(aliases, list)
                    else []
                ),
            }
        )
    return commands


def is_allowed_leading_slash(name: str, server_info: dict[str, Any]) -> bool:
    """Return whether a leading slash name may be executed."""
    if name in ALLOWED_COMMAND_NAMES:
        return True
    return any(
        name == skill["name"] or name in skill["aliases"] for skill in _get_server_commands(server_info, skills=True)
    )


class CommandRouter:
    """Expose live commands through clients retained by ChatRouter."""

    def get_commands(self, session_id: str) -> list[ClaudeCommand]:
        """Return regular commands from the session's live SDK client."""
        return _get_server_commands(
            self._get_chat_server_info(session_id),
            skills=False,
        )

    def get_allowed_command_names(self) -> list[str]:
        """Return command names the chat API allows at the prompt start."""
        return sorted(ALLOWED_COMMAND_NAMES)

    def get_skills(self, session_id: str) -> list[ClaudeCommand]:
        """Return skills from the session's live SDK client."""
        return _get_server_commands(
            self._get_chat_server_info(session_id),
            skills=True,
        )

    def _get_chat_server_info(self, session_id: str) -> dict[str, Any]:
        raise NotImplementedError
