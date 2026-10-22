"""移植 zvec-grep 的 Text/MarkdownExtractor 与 input-budget（99cf43f）。

Ported from zvec-ai/zvec-grep, Apache-2.0; Python translation.
See THIRD-PARTY-NOTICES.
"""

import math
import re

from backend.service.knowledge.text_files import TEXT_WHITESPACE

CHUNK_SIZE = 3600
CHUNK_OVERLAP = 540
_SPACE = f"[{re.escape(TEXT_WHITESPACE)}]"


def index_chunk_options(max_input_tokens: int | None, text: str | None = None) -> tuple[int, int]:
    """上游按文本密度估算字符预算；不是严格 token 长度保证。"""
    if max_input_tokens is None:
        return CHUNK_SIZE, CHUNK_OVERLAP
    units = _utf16_units(text) if text is not None else None
    dense = False
    if units is not None and len(units) > max_input_tokens:
        window = 16 * 1024
        if len(units) <= window:
            dense = _dense_window(units)
        else:
            last_start = len(units) - window
            dense = any(_dense_window(units[start : start + window]) for start in range(0, last_start + 1, 8 * 1024))
            if not dense and last_start % (8 * 1024):
                dense = _dense_window(units[last_start:])
    max_chars = max_input_tokens * (100 if dense else 185) // 100
    return max_chars, max_chars * 15 // 100


def _dense_window(text: str) -> bool:
    required = math.ceil(len(text) * 30 / 100)
    count = 0
    for character in text:
        if not ("A" <= character <= "Z" or "a" <= character <= "z" or character in " \t"):
            count += 1
            if count >= required:
                return True
    return False


def chunk_text(
    text: str,
    *,
    markdown: bool = False,
    max_chars: int = CHUNK_SIZE,
    overlap_chars: int = CHUNK_OVERLAP,
) -> list[str]:
    """按上游规则返回片段正文，保持字符计数、切点和空白处理一致。"""
    if type(max_chars) is not int or max_chars <= 0:
        raise ValueError("切片长度必须为正整数")
    if type(overlap_chars) is not int or not 0 <= overlap_chars < max_chars:
        raise ValueError("重叠长度必须为非负整数且小于切片长度")
    units = _utf16_units(text)
    chunks = (
        _markdown_chunks(units, max_chars, overlap_chars) if markdown else _text_chunks(units, max_chars, overlap_chars)
    )
    return [_from_utf16_units(chunk) for chunk in chunks]


def _text_chunks(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    if not text.strip(TEXT_WHITESPACE):
        return []
    lines = text.split("\n")
    chunks = []
    start = 0
    while start < len(lines):
        if len(lines[start]) + 1 > max_chars:
            chunks.extend(_long_line(lines[start], max_chars))
            start += 1
            continue
        used = 0
        end = start
        while end < len(lines):
            length = len(lines[end]) + 1
            if used + length > max_chars and end > start:
                break
            used += length
            end += 1
        chunk = "\n".join(lines[start:end])
        if chunk.strip(TEXT_WHITESPACE):
            chunks.append(chunk)
        if end >= len(lines):
            break
        overlap_count = 0
        overlap_lines = 0
        for index in range(end - 1, start - 1, -1):
            if overlap_count >= overlap_chars:
                break
            overlap_count += len(lines[index]) + 1
            overlap_lines += 1
        next_start = end - overlap_lines
        start = next_start if next_start > start else end
    return chunks


def _long_line(line: str, max_chars: int) -> list[str]:
    chunks = []
    offset = 0
    while offset < len(line):
        length = min(len(line) - offset, max_chars)
        if len(line) - offset > max_chars:
            length = _line_cut(line[offset : offset + max_chars + 1], max_chars)
        chunk = line[offset : offset + length]
        if chunk.strip(TEXT_WHITESPACE):
            chunks.append(chunk)
        offset += length
    return chunks


def _line_cut(line: str, max_chars: int) -> int:
    if len(line) <= max_chars:
        return len(line)
    best_position = -1
    best_score = 0
    for index in range(math.floor(max_chars * 0.7), max_chars):
        character = line[index]
        score = (
            4
            if character in ".!?"
            else 3
            if character in ",;:"
            else 2
            if character in " \t"
            else 1
            if character in "-/\\"
            else 0
        )
        if score > 0 and score >= best_score:
            best_score, best_position = score, index + 1
    return best_position if best_position > 0 else max_chars


def _markdown_chunks(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    lines = text.split("\n")
    headings = _scan_headings(lines)
    if not headings:
        return _text_chunks(text, max_chars, overlap_chars)
    sections = []
    if headings[0][0] > 0 and "\n".join(lines[: headings[0][0]]).strip(TEXT_WHITESPACE):
        sections.append((0, headings[0][0] - 1, None, None, []))
    stack = []
    for index, (start, level, heading) in enumerate(headings):
        while stack and stack[-1][0] >= level:
            stack.pop()
        end = headings[index + 1][0] - 1 if index + 1 < len(headings) else len(lines) - 1
        sections.append((start, end, heading, level, [item[1] for item in stack]))
        stack.append((level, heading))
    fences = _fence_lines(lines)
    chunks = []
    for start, end, heading, level, breadcrumb in sections:
        metadata = []
        if heading:
            metadata.append(f"heading: {heading}")
        if level is not None:
            metadata.append(f"heading_level: {level}")
        if breadcrumb:
            metadata.append(f"scope: {'::'.join(breadcrumb)}")
        metadata_text = _fit_text("\n".join(metadata), math.floor(max_chars * 0.25))
        content_size = max(1, max_chars - len(metadata_text) - (1 if metadata_text else 0))
        content_overlap = min(overlap_chars, max(0, content_size - 1))
        windows = _markdown_windows(lines, fences, start, end, content_size, content_overlap)
        if len(windows) > 1:
            chunks.append(_fit_text(heading if heading is not None else "markdown section", content_size))
        chunks.extend(windows)
    return chunks or _text_chunks(text, max_chars, overlap_chars)


def _scan_headings(lines: list[str]) -> list[tuple[int, int, str]]:
    headings = []
    fence = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        trimmed = line.lstrip(TEXT_WHITESPACE)
        if fence:
            if trimmed.startswith(fence):
                fence = ""
        elif trimmed.startswith(("```", "~~~")):
            fence = trimmed[:3]
        else:
            atx = re.fullmatch(rf"(#{{1,6}}){_SPACE}+([^\r\n\u2028\u2029]+?){_SPACE}*#*{_SPACE}*", line)
            if atx:
                headings.append((index, len(atx[1]), atx[2].strip(TEXT_WHITESPACE)))
            elif line.strip(TEXT_WHITESPACE) and index + 1 < len(lines):
                following = lines[index + 1].strip(TEXT_WHITESPACE)
                if re.fullmatch(rf"(?:=+|-+){_SPACE}*", following):
                    headings.append((index, 1 if following.startswith("=") else 2, line.strip(TEXT_WHITESPACE)))
                    index += 1
        index += 1
    return headings


def _fence_lines(lines: list[str]) -> list[bool]:
    flags = [False] * len(lines)
    fence = ""
    for index, line in enumerate(lines):
        trimmed = line.lstrip(TEXT_WHITESPACE)
        if fence:
            flags[index] = True
            if trimmed.startswith(fence):
                fence = ""
        elif trimmed.startswith(("```", "~~~")):
            fence = trimmed[:3]
    return flags


def _markdown_windows(
    lines: list[str], fences: list[bool], start: int, last: int, max_chars: int, overlap_chars: int
) -> list[str]:
    windows = []
    while start <= last:
        if len(lines[start]) + 1 > max_chars:
            windows.extend(_long_line(lines[start], max_chars))
            start += 1
            continue
        end, used = start, 0
        while end <= last:
            length = len(lines[end]) + 1
            if used + length > max_chars and end > start:
                break
            used += length
            end += 1
        if end <= last and end - start > 1:
            best_break = end
            best_score = _break_score(lines, fences, end)
            minimum = start + max(1, math.floor((end - start) * 0.7))
            for index in range(minimum, end + 1):
                score = _break_score(lines, fences, index)
                if score > best_score:
                    best_break, best_score = index, score
            end = best_break
        windows.append("\n".join(lines[start:end]))
        if end > last:
            break
        chars, count = 0, 0
        for index in range(end - 1, start, -1):
            if overlap_chars <= 0:
                break
            chars += len(lines[index]) + 1
            if chars > overlap_chars:
                break
            count += 1
        count = min(count, (end - start) // 2)
        next_start = end - count
        start = next_start if next_start > start else end
    return [window for window in windows if window.strip(TEXT_WHITESPACE)]


def _break_score(lines: list[str], fences: list[bool], index: int) -> int:
    if index <= 0 or index >= len(lines) or fences[index]:
        return 0
    current, previous = lines[index].strip(TEXT_WHITESPACE), lines[index - 1].strip(TEXT_WHITESPACE)
    if re.match(rf"^#{{1,6}}{_SPACE}+", current):
        return 100
    if not previous and not current:
        return 70
    if not previous:
        return 60
    if re.match(rf"^([-*+]|[0-9]+\.){_SPACE}+", current):
        return 35
    if re.match(rf"^>{_SPACE}+", current):
        return 25
    return 10


def _fit_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    if max_chars <= 3:
        return "." * max(0, max_chars)
    end = max_chars - 3
    if 0 < end < len(value) and 0xD800 <= ord(value[end - 1]) <= 0xDBFF and 0xDC00 <= ord(value[end]) <= 0xDFFF:
        end -= 1
    return value[:end].rstrip(TEXT_WHITESPACE) + "..."


def _utf16_units(text: str) -> str:
    def expand(match: re.Match[str]) -> str:
        code = ord(match[0]) - 0x10000
        return chr(0xD800 + (code >> 10)) + chr(0xDC00 + (code & 0x3FF))

    return re.sub(r"[\U00010000-\U0010ffff]", expand, text)


def _from_utf16_units(text: str) -> str:
    return text.encode("utf-16-le", errors="surrogatepass").decode("utf-16-le", errors="surrogatepass")
