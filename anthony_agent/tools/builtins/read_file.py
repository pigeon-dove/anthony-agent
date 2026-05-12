"""ReadFile 工具 — 读取文件内容"""

import asyncio
from pathlib import Path

from anthony_agent.tools.base import BaseTool, ToolDefinition, ToolResult
from anthony_agent.utils.image import is_image_file

_MAX_LINES = 2000  # 默认最多读取行数
_MAX_LINE_CHARS = 2000  # 单行最大字符数
_MAX_OUTPUT = 60_000  # 总输出字符上限

_TOOL_DESCRIPTION = """\
读取文件内容，以带行号的格式输出（行号从 1 开始），**行号前缀不属于文件内容，编辑时不要包含**。

适用场景：
- 查看文件完整内容或指定行范围
- 编辑前确认文件当前状态
- 可同时发起多个读取调用以提高效率
- 读取图片文件（png/jpg/jpeg/gif/webp）时，图片会自动注入到下一条消息，你可直接看到图片内容

使用指南：
- 使用绝对路径指定文件
- 小文件建议一次性读取全部内容，不必指定 offset/limit
- 长文件可通过 offset（起始行号）和 limit（行数）参数指定读取范围"""


def _read_lines(p: Path, start: int, count: int) -> tuple[list[str], int]:
    """
    流式逐行读取 [start, start+count)，返回 (选中行列表, 文件总行数)。

    不会将整个文件加载到内存。
    """
    selected: list[str] = []
    total = 0
    with p.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            if total >= start and len(selected) < count:
                selected.append(line.rstrip("\n"))
            total += 1
    return selected, total


def _format_output(lines: list[str], start: int, total: int) -> str:
    """将行列表格式化为 cat -n 风格输出，受单行字符和总输出双重限制。"""
    parts: list[str] = []
    budget = _MAX_OUTPUT
    shown = 0

    for i, line in enumerate(lines, start=start + 1):
        if len(line) > _MAX_LINE_CHARS:
            line = line[:_MAX_LINE_CHARS] + "..."
        formatted = f"     {i}\t{line}"
        if budget - len(formatted) - 1 < 0:  # -1 for '\n'
            break
        parts.append(formatted)
        budget -= len(formatted) + 1
        shown += 1

    end = start + shown
    result = "\n".join(parts)

    if end < total:
        result += f"\n\n(显示第 {start + 1}-{end} 行，共 {total} 行，剩余 {total - end} 行未显示)"

    return result


class ReadFileTool(BaseTool):
    """读取指定文件的内容，支持可选的行范围"""

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_file",
            description=_TOOL_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件的绝对路径",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "起始行号（从 1 开始），不传则从头开始",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "读取的行数，不传则读取到末尾",
                    },
                },
                "required": ["path"],
            },
        )

    async def execute(self, path: str, offset: int | None = None, limit: int | None = None) -> ToolResult:
        p = Path(path).resolve()
        if not p.exists():
            return ToolResult(content=f"文件不存在: {path}", is_error=True)
        if not p.is_file():
            return ToolResult(content=f"不是文件: {path}", is_error=True)

        # 图片文件：不读文本，返回带 images 的结果，ToolResult.to_messages 会自动注入图片 user message
        if is_image_file(p):
            return ToolResult(
                content=f"已读取图片: {p}\n图片已作为附件注入到下一条消息，请根据图片内容回答。",
                images=[str(p)],
            )

        start = (offset - 1) if offset and offset > 0 else 0
        count = limit if limit and limit > 0 else _MAX_LINES

        lines, total = await asyncio.to_thread(_read_lines, p, start, count)
        return ToolResult(content=_format_output(lines, start, total))
