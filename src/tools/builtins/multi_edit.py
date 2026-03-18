"""MultiEdit 工具 — 对同一文件执行多次搜索替换"""

import asyncio
from pathlib import Path

from src.tools.base import BaseTool, ToolDefinition, ToolResult

_TOOL_DESCRIPTION = """\
对单个文件执行多次搜索替换操作，原子性执行（全部成功或全部回滚）。
使用指南：
- 编辑按顺序依次应用，每次基于前一次的结果
- 每个编辑的 old_string 必须与当时的文件内容精确匹配（包括所有空白和缩进）
- old_string 与 new_string 不能相同
- 匹配数量必须等于 expected_replacements（默认 1），否则整体失败
- 创建新文件：第一个编辑的 old_string 设为空字符串，new_string 为文件内容
- 对同一文件做多处修改时，优先使用此工具而非多次调用 edit_file"""


class MultiEditTool(BaseTool):
    """对同一文件按顺序执行多次搜索替换"""

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="multi_edit",
            description=_TOOL_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件的绝对路径",
                    },
                    "edits": {
                        "type": "array",
                        "description": "编辑操作列表，按顺序依次执行",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_string": {
                                    "type": "string",
                                    "description": "要被替换的原始文本（必须精确匹配）",
                                },
                                "new_string": {
                                    "type": "string",
                                    "description": "替换后的新文本",
                                },
                                "expected_replacements": {
                                    "type": "integer",
                                    "description": "预期替换次数，默认为 1",
                                },
                            },
                            "required": ["old_string", "new_string"],
                        },
                    },
                },
                "required": ["path", "edits"],
            },
        )

    async def execute(self, path: str, edits: list[dict]) -> ToolResult:
        if not edits:
            return ToolResult(content="edits 数组为空", is_error=True)

        p = Path(path).resolve()

        # 文件存在 → 读取；不存在且首个 old_string 为空 → 创建；否则报错
        if p.is_file():
            content = await asyncio.to_thread(p.read_text, encoding="utf-8")
        elif edits[0].get("old_string", "") == "":
            content = ""
        else:
            return ToolResult(content=f"文件不存在: {path}", is_error=True)

        # 在内存中依次应用每个编辑，任一失败则整体不写回（原子性）
        for i, edit in enumerate(edits, start=1):
            old = edit.get("old_string", "")
            new = edit.get("new_string", "")
            expected = edit.get("expected_replacements", 1)

            # old_string 为空 → 追加内容（用于创建新文件或向文件末尾追加）
            if old == "":
                content += new
                continue

            if old == new:
                return ToolResult(content=f"编辑 #{i}: old_string 与 new_string 相同", is_error=True)

            count = content.count(old)
            if count != expected:
                hint = "未找到匹配" if count == 0 else f"预期 {expected} 处，实际 {count} 处"
                return ToolResult(content=f"编辑 #{i}: {hint}", is_error=True)

            content = content.replace(old, new)

        # 全部通过，写回文件
        await asyncio.to_thread(lambda: p.parent.mkdir(parents=True, exist_ok=True))
        await asyncio.to_thread(p.write_text, content, encoding="utf-8")

        return ToolResult(content=f"已编辑文件，共应用 {len(edits)} 处编辑（{path}）")
