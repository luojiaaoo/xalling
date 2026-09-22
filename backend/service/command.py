"""Command and skill metadata normalization behind the bridge."""

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
        "verify",
        "code-review",
        "dataviz",
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
    # The CLI prefixes skill descriptions with their source, e.g. "(opencode) ..." or "(.agents) ..."; built-in commands have no prefix
    return description.lstrip().startswith("(")


def _skill_real_name(name: str, description: str) -> str:
    """技能名补上命名空间：取描述首括号里的来源，拼成 source:name 形式。"""
    # 名字本身已带命名空间（含 ":"）时保持原样
    if ":" in name:
        return name
    start = description.find("(")
    end = description.find(")", start + 1) if start != -1 else -1
    if start == -1 or end == -1:
        return name
    source = description[start + 1 : end].strip()
    if not source:
        return name
    return f"{source}:{name}"


def _get_server_commands(
    server_info: dict[str, Any],
    *,
    skills: bool,
) -> list[ClaudeCommand]:
    """Normalize either skills or regular commands from live server metadata."""
    raw_commands = server_info.get("commands", [])
    if not isinstance(raw_commands, list):
        return []

    commands: dict[str, ClaudeCommand] = {}
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
        # 技能名补上描述首括号里的来源命名空间（如 opencode:xxx）
        if skills:
            name = _skill_real_name(name, description)

        argument_hint = item.get("argumentHint", "")
        aliases = item.get("aliases", [])
        # 重名时保留最后一个（技能与命令均按此规则去重）
        commands[name] = {
            "name": name,
            "description": description,
            "argument_hint": (argument_hint if isinstance(argument_hint, str) else ""),
            "aliases": (
                [alias.strip() for alias in aliases if isinstance(alias, str) and alias.strip()]
                if isinstance(aliases, list)
                else []
            ),
        }
    return list(commands.values())


def is_allowed_leading_slash(name: str, server_info: dict[str, Any]) -> bool:
    """Return whether a leading slash name may be executed."""
    if name in ALLOWED_COMMAND_NAMES:
        return True
    # 技能名或其别名出现在消息开头时同样允许执行
    return any(
        name == skill["name"] or name in skill["aliases"] for skill in _get_server_commands(server_info, skills=True)
    )


class CommandService:
    """Expose regular commands and skills from live server metadata."""

    @staticmethod
    def get_commands(server_info: dict[str, Any]) -> list[ClaudeCommand]:
        """Return regular commands from the session's live SDK client."""
        return _get_server_commands(server_info, skills=False)

    @staticmethod
    def get_skills(server_info: dict[str, Any]) -> list[ClaudeCommand]:
        """Return skills from the session's live SDK client."""
        return _get_server_commands(server_info, skills=True)

    @staticmethod
    def get_allowed_command_names() -> list[str]:
        """Return command names the chat API allows at the prompt start."""
        return sorted(ALLOWED_COMMAND_NAMES)
