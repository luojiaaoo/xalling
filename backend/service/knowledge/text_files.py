"""移植 zvec-grep 的文件类型表、二进制嗅探与 UTF-8 解码（99cf43f）。

Ported from zvec-ai/zvec-grep, Apache-2.0; Python translation.
See THIRD-PARTY-NOTICES.
"""

from pathlib import Path
from typing import Literal, TypedDict

_CODE_FORMATS = {
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
    ".go": "go",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "jsx",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".py": "python",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".cs": "csharp",
    ".scala": "scala",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".sql": "sql",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".vue": "vue",
    ".svelte": "svelte",
}
_DATA_FORMATS = {".csv": "csv", ".json": "json", ".jsonc": "json", ".toml": "toml", ".yaml": "yaml", ".yml": "yaml"}
_TEXT_FORMATS = {
    ".md": "markdown",
    ".mdx": "markdown",
    ".rst": "rst",
    ".txt": "text",
    ".html": "html",
    ".htm": "html",
    ".xml": "xml",
}
_IMAGE_FORMATS = {".gif": "gif", ".jpeg": "jpeg", ".jpg": "jpeg", ".png": "png", ".webp": "webp"}
_BINARY_EXTENSIONS = {
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".exe",
    ".dll",
    ".dylib",
    ".so",
    ".a",
    ".o",
    ".obj",
    ".wasm",
    ".class",
    ".jar",
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".mp3",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".db",
    ".sqlite",
}

_BINARY_SNIFF_BYTES = 8192
_ALLOWED_CONTROL_BYTES = frozenset({7, 8, 9, 10, 12, 13, 27})
TEXT_WHITESPACE = "\u0009\u000a\u000b\u000c\u000d \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


class FileType(TypedDict):
    kind: Literal["code", "data", "text", "image"]
    format: str


def detect_file_type(source: Path) -> FileType | None:
    if source.name in {"Dockerfile", "Makefile"}:
        return {"kind": "code", "format": source.name.lower()}
    extension = source.suffix.lower()
    if not extension and source.name.endswith(".") and source.name not in {".", ".."}:
        extension = "."
    for kind, formats in (
        ("code", _CODE_FORMATS),
        ("data", _DATA_FORMATS),
        ("text", _TEXT_FORMATS),
        ("image", _IMAGE_FORMATS),
    ):
        if extension in formats:
            return {"kind": kind, "format": formats[extension]}
    if extension in _BINARY_EXTENSIONS:
        return None
    return {"kind": "text", "format": extension[1:] if extension else "text"}


def decode_text(data: bytes) -> str:
    """与上游一致：只检查前 8 KiB，解码替换无效字节，保留 UTF-8 BOM。"""
    sample = data[:_BINARY_SNIFF_BYTES]
    suspicious = sum(value < 32 and value not in _ALLOWED_CONTROL_BYTES for value in sample)
    if b"\x00" in sample or (sample and suspicious / len(sample) > 0.3):
        raise ValueError("文件包含二进制内容。")
    return data.decode("utf-8", errors="replace")


def utf8_text(text: str) -> str:
    """将孤立的 UTF-16 代理字符转换为可写入 UTF-8 模型和索引的替换字符。"""
    return text.encode("utf-16-le", errors="surrogatepass").decode("utf-16-le", errors="replace")
