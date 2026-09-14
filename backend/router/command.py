"""Claude command and skill methods exposed to the local Web UI."""

from abc import ABC, abstractmethod
from typing import Any, TypedDict

# 允许对外暴露并执行的常规命令白名单（交互式/客户端命令不开放）
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
    """Distinguish skills from regular commands in server metadata."""
    # SDK 显式标注 kind/type 时直接采用
    item_kind = item.get("kind", item.get("type"))
    if item_kind == "skill":
        return True
    if item_kind == "command":
        return False
    # 未标注时按经验规则推断：用户技能描述以 "(user)" 结尾，插件技能名带命名空间前缀
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
        # 技能与命令两条通道互斥，按调用方要求各取其一
        if _is_skill(name, description, item) is not skills:
            continue
        # 常规命令额外受白名单约束，技能全量放行
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
    # 技能名或其别名出现在消息开头时同样允许执行
    return any(
        name == skill["name"] or name in skill["aliases"] for skill in _get_server_commands(server_info, skills=True)
    )


class CommandRouter(ABC):
    """Expose live commands through clients retained by ChatRouter."""

    async def get_commands(self, session_id: str) -> list[ClaudeCommand]:
        """Return regular commands from the session's live SDK client."""
        return _get_server_commands(
            await self._get_chat_server_info(session_id),
            skills=False,
        )

    def get_allowed_command_names(self) -> list[str]:
        """Return command names the chat API allows at the prompt start."""
        return sorted(ALLOWED_COMMAND_NAMES)

    async def get_skills(self, session_id: str) -> list[ClaudeCommand]:
        """Return skills from the session's live SDK client."""
        return _get_server_commands(
            await self._get_chat_server_info(session_id),
            skills=True,
        )

    @abstractmethod
    async def _get_chat_server_info(self, session_id: str) -> dict[str, Any]:
        """Return live server metadata for a retained chat session."""
