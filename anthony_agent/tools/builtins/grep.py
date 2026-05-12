"""GrepTool — 快速内容搜索"""

import asyncio
import re
from pathlib import Path

from wcmatch import fnmatch as wcfnmatch

from anthony_agent.tools.base import BaseTool, ToolDefinition, ToolResult

MAX_RESULTS = 200  # 单次搜索最大结果行数
_BINARY_CHECK_SIZE = 512  # 二进制文件检测：检查前 512 字节是否包含 \x00
_FN_FLAGS = wcfnmatch.BRACE  # wcmatch 标志：支持 {} 花括号展开
_SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "__pycache__", ".tox", ".mypy_cache", "dist", "build"})

_TOOL_DESCRIPTION = f"""\
在目录中递归搜索匹配正则表达式的**文件内容**，输出格式为 `文件路径:行号:内容`。

适用场景：
- 按内容查找代码：函数定义、变量引用、TODO/FIXME 标记等
- 支持完整的 Python re 正则语法：`log.*Error`、`def\\s+\\w+`、`TODO|FIXME`
- 可通过 include 参数按文件名过滤（如 `*.py`、`*.{{js,ts}}`），支持花括号展开
- 可同时发起多个搜索调用以提高效率
- 自动跳过二进制文件和常见非项目目录（.git、node_modules、.venv、__pycache__ 等）

不适用场景：
- 按文件名/路径查找 → 请使用 glob 工具
- 查看目录结构 → 请使用 ls 工具"""


def _read_text_if_not_binary(file: Path) -> str | None:
    """读取文件字节，若为二进制则返回 None，否则解码为文本返回"""
    try:
        raw = file.read_bytes()
    except (OSError, PermissionError):
        return None
    if b"\x00" in raw[:_BINARY_CHECK_SIZE]:
        return None
    return raw.decode(errors="ignore")


def _sync_search(
    root: Path,
    regex: re.Pattern,
    include: str | None,
) -> tuple[list[str], bool]:
    """同步递归搜索，边遍历边匹配，找够即停。"""
    matches: list[str] = []
    truncated = False

    for file in root.rglob("*"):
        try:
            if any(p in _SKIP_DIRS for p in file.relative_to(root).parts):
                continue
            if not file.is_file():
                continue
            if include and not wcfnmatch.fnmatch(file.name, include, flags=_FN_FLAGS):
                continue
        except (PermissionError, OSError):
            continue

        text = _read_text_if_not_binary(file)
        if text is None:
            continue

        abs_path = str(file)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append(f"{abs_path}:{lineno}:{line}")
                if len(matches) >= MAX_RESULTS:
                    truncated = True
                    break
        if truncated:
            break

    return matches, truncated


class GrepTool(BaseTool):
    """基于 Python re 模块的快速内容搜索工具"""

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="grep",
            description=_TOOL_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "要搜索的正则表达式模式（Python re 语法），例如 'def\\s+main'、'import.*os'",
                    },
                    "path": {
                        "type": "string",
                        "description": "搜索的起始目录绝对路径，会递归搜索所有子目录",
                    },
                    "include": {
                        "type": "string",
                        "description": "按文件名模式过滤（可选），例如 '*.py'、'*.{js,ts}'。仅匹配文件名，不含路径",
                    },
                },
                "required": ["pattern", "path"],
            },
        )

    async def execute(self, pattern: str, path: str, include: str | None = None) -> ToolResult:
        root = Path(path).resolve()

        if not root.exists():
            return ToolResult(content=f"路径不存在: {path}", is_error=True)
        if not root.is_dir():
            return ToolResult(content=f"不是目录: {path}", is_error=True)

        try:
            regex = re.compile(pattern)
        except re.error as e:
            return ToolResult(content=f"无效的正则表达式: {e}", is_error=True)

        results, truncated = await asyncio.to_thread(_sync_search, root, regex, include)

        if not results:
            return ToolResult(content=f"没有匹配 '{pattern}' 的内容")

        if truncated:
            results.append(f"\n(结果已截断，共显示 {MAX_RESULTS} 条)")
        return ToolResult(content="\n".join(results))
