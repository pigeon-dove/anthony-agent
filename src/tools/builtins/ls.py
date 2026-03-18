"""LsTool — 列出目录内容"""

import asyncio
from pathlib import Path

from wcmatch import fnmatch as wcfnmatch

from src.tools.base import BaseTool, ToolDefinition, ToolResult

_FN_FLAGS = wcfnmatch.BRACE

_TOOL_DESCRIPTION = """\
列出目录中的文件和子目录，显示名称、类型和大小信息，结果按目录优先、名称字母序排列。

适用场景：
- 快速了解目录结构和文件分布
- 查看某个目录下有哪些文件和子目录

不适用场景：
- 递归查找深层文件 → 请使用 glob 工具
- 按文件内容搜索 → 请使用 grep 工具

使用指南：
- 使用绝对路径指定目标目录
- 仅列出直接子项，不递归
- 可通过 ignore 参数排除不需要的文件（如 `*.pyc`、`__pycache__`、`.git`）"""


def _format_size(num_bytes: int) -> str:
    """将字节数格式化为人类可读的大小"""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _format_entry(entry: Path) -> str:
    """格式化单个条目：目录 → 名称/，文件 → 名称 + 大小"""
    if entry.is_dir():
        return f"[目录] {entry.name}/"
    try:
        size = entry.stat().st_size
    except OSError:
        return f"[文件] {entry.name}  (大小未知)"
    return f"[文件] {entry.name}  ({_format_size(size)})"


def _sync_list(p: Path, ignore_patterns: list[str]) -> list[str]:
    """同步目录列出（在 to_thread 中运行），返回格式化行列表"""
    entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
    return [
        _format_entry(e)
        for e in entries
        if not any(wcfnmatch.fnmatch(e.name, pat, flags=_FN_FLAGS) for pat in ignore_patterns)
    ]


class LsTool(BaseTool):
    """列出给定路径中的文件和目录"""

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="ls",
            description=_TOOL_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要列出内容的目录的绝对路径",
                    },
                    "ignore": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要忽略的 glob 模式数组，如 ['*.pyc', '__pycache__', '.git']，支持花括号展开如 '*.{pyc,pyo}'",
                    },
                },
                "required": ["path"],
            },
        )

    async def execute(self, path: str, ignore: list[str] | None = None) -> ToolResult:
        p = Path(path).resolve()

        if not p.exists():
            return ToolResult(content=f"路径不存在: {path}", is_error=True)
        if not p.is_dir():
            return ToolResult(content=f"不是目录: {path}", is_error=True)

        lines = await asyncio.to_thread(_sync_list, p, ignore or [])
        return ToolResult(content="\n".join(lines) if lines else "(目录为空)")
