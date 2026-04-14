"""GlobTool — 快速文件模式匹配"""

import asyncio
from pathlib import Path

from wcmatch import glob as wcglob

from src.tools.base import BaseTool, ToolDefinition, ToolResult

_GLOB_FLAGS = wcglob.BRACE | wcglob.GLOBSTAR  # wcmatch 标志：支持 ** 递归 + {} 花括号展开
_MAX_RESULTS = 200  # 最大返回文件数，防止 token 爆炸

_TOOL_DESCRIPTION = """\
基于 glob 模式**快速查找文件路径**，返回按修改时间降序排列的匹配文件列表。

适用场景：
- 按文件名、扩展名或目录结构查找文件
- 支持标准 glob 语法及花括号展开：`**/*.py`、`src/**/*.{js,ts}`、`**/test_*`
- 可同时发起多个搜索调用以提高效率

不适用场景：
- 按文件内容搜索 → 请使用 grep 工具
- 查看目录直接子项 → 请使用 ls 工具

输出限制：
- 最多返回 200 条结果，按文件修改时间降序排列
- 返回结果为绝对路径，便于后续直接传给其他工具"""


def _safe_mtime(f: Path) -> float:
    try:
        return f.stat().st_mtime
    except (PermissionError, OSError):
        return 0.0


def _sync_search(root: Path, pattern: str) -> list[Path]:
    """同步执行 glob 匹配 + 过滤 + 排序（整块在 to_thread 中运行）"""
    full_pattern = str(root / pattern)
    files: list[Path] = []
    for m in wcglob.iglob(full_pattern, flags=_GLOB_FLAGS):
        p = Path(m)
        try:
            if p.is_file():
                files.append(p)
        except (PermissionError, OSError):
            continue
    files.sort(key=lambda f: _safe_mtime(f), reverse=True)
    return files


class GlobTool(BaseTool):
    """基于 glob 模式的快速文件搜索工具"""

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="glob",
            description=_TOOL_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "要搜索的 glob 模式，例如 '**/*.py'、'**/*.{js,ts}'",
                    },
                    "path": {
                        "type": "string",
                        "description": "搜索的起始目录绝对路径",
                    },
                },
                "required": ["pattern", "path"],
            },
        )

    async def execute(self, pattern: str, path: str) -> ToolResult:
        root = Path(path).resolve()

        if not root.exists():
            return ToolResult(content=f"路径不存在: {path}", is_error=True)
        if not root.is_dir():
            return ToolResult(content=f"不是目录: {path}", is_error=True)

        files = await asyncio.to_thread(_sync_search, root, pattern)

        if not files:
            return ToolResult(content=f"没有匹配 '{pattern}' 的文件")

        # 截断并提示
        truncated = len(files) > _MAX_RESULTS
        files = files[:_MAX_RESULTS]

        # 输出绝对路径，减少后续再次拼接路径时的出错概率
        lines = [str(f) for f in files]
        if truncated:
            lines.append(f"\n(结果已截断，仅显示前 {_MAX_RESULTS} 条)")
        return ToolResult(content="\n".join(lines))
