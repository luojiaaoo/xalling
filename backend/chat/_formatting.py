"""Internal formatting helpers shared by chat readers and writers."""

from typing import Any


def summarize_tool_input(tool_input: dict[str, Any]) -> str:
    """Create the compact tool-input label used by live and history UI."""
    preferred_keys = (
        "file_path",
        "path",
        "pattern",
        "query",
        "url",
        "command",
        "description",
    )
    summary_parts: list[str] = []
    for key in preferred_keys:
        if key not in tool_input:
            continue
        value = tool_input[key]
        if not isinstance(value, (str, int, float, bool)):
            continue
        normalized = " ".join(str(value).split())
        if normalized:
            summary_parts.append(f"{key}: {normalized[:180]}")
        if len(summary_parts) == 2:
            break
    return " · ".join(summary_parts)
