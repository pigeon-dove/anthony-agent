"""LsTool — 列出目录内容"""

from fnmatch import fnmatch
from pathlib import Path

from src.tools.base import BaseTool, ToolDefinition, ToolResult


class LsTool(BaseTool):
    """列出给定路径中的文件和目录"""

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="ls",
            description="""\
列出给定路径中的文件和目录。

- 路径参数必须是绝对路径，而非相对路径。
- 您可以选择性地通过 ignore 参数提供一个全局模式（glob patterns）数组来忽略某些文件。""",
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
                        "description": "要忽略的 glob 模式数组，如 ['*.pyc', '__pycache__', '.git']",
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

        ignore_patterns = ignore or []

        try:
            entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        except PermissionError:
            return ToolResult(content=f"没有权限访问: {path}", is_error=True)

        lines = [
            self._format_entry(entry)
            for entry in entries
            if not any(fnmatch(entry.name, pat) for pat in ignore_patterns)
        ]

        return ToolResult(content="\n".join(lines) if lines else "(目录为空)")

    @staticmethod
    def _format_entry(entry: Path) -> str:
        """格式化单个条目：目录显示名称/，文件显示名称 + 大小"""
        if entry.is_dir():
            return f"[目录] {entry.name}/"
        size = entry.stat().st_size
        return f"[文件] {entry.name}  ({LsTool._format_size(size)})"

    @staticmethod
    def _format_size(num_bytes: int) -> str:
        """将字节数格式化为人类可读的大小"""
        size = float(num_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
