"""GrepTool — 快速内容搜索"""

import asyncio
import re
from pathlib import Path

from wcmatch import fnmatch as wcfnmatch

from src.tools.base import BaseTool, ToolDefinition, ToolResult

MAX_RESULTS = 200  # 单次搜索最大结果行数
_BINARY_CHECK_SIZE = 512  # 二进制文件检测：检查前 512 字节是否包含 \x00
_FN_FLAGS = wcfnmatch.BRACE  # wcmatch 标志：支持 {} 花括号展开

_TOOL_DESCRIPTION = f"""\
在目录中递归搜索匹配正则表达式的文件内容，输出格式为 `文件路径:行号:内容`。
使用指南：
- 支持完整的 Python re 正则语法：`log.*Error`、`def\\s+\\w+`、`TODO|FIXME`
- 可通过 include 参数按文件名过滤（如 `*.py`、`*.{{js,ts}}`），支持花括号展开
- 最多返回 {MAX_RESULTS} 条结果，优先展示最近修改的文件
- 自动跳过二进制文件，仅搜索文本文件
- 按文件名/路径查找请使用 glob 工具
- 可同时发起多个搜索调用以提高效率"""


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
    """
    同步执行搜索逻辑（整块在 to_thread 中运行）。

    策略：先搜索收集匹配行，到上限后提前终止遍历，最后按文件修改时间排序。
    返回 (结果行列表, 是否被截断)。
    """
    # 收集匹配项：(mtime, 相对路径, 行号, 行内容)
    matches: list[tuple[float, str, int, str]] = []
    truncated = False

    for file in root.rglob("*"):
        try:
            if not file.is_file():
                continue
        except (PermissionError, OSError):
            continue

        # include 过滤：用 wcmatch.fnmatch 支持 {js,ts} 花括号展开
        if include and not wcfnmatch.fnmatch(file.name, include, flags=_FN_FLAGS):
            continue

        # 读取文件，跳过二进制文件（一次 IO 完成检测和读取）
        text = _read_text_if_not_binary(file)
        if text is None:
            continue

        rel = str(file.relative_to(root))
        mtime = file.stat().st_mtime

        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append((mtime, rel, lineno, line))
                if len(matches) >= MAX_RESULTS:
                    truncated = True
                    break
        if truncated:
            break

    # 按文件修改时间降序排序
    matches.sort(key=lambda m: m[0], reverse=True)
    results = [f"{rel}:{lineno}:{line}" for _, rel, lineno, line in matches]
    return results, truncated


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
