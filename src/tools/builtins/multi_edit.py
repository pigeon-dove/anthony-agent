"""MultiEdit 工具 — 对同一文件执行多次搜索替换"""

from pathlib import Path

from src.tools.base import BaseTool, ToolDefinition, ToolResult


class MultiEditTool(BaseTool):
    """对同一文件按顺序执行多次搜索替换"""

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="multi_edit",
            description="""\
这是一个用于在单次操作中对单个文件进行多次编辑的工具。它构建在编辑工具之上，允许您高效地执行多次查找和替换操作。当您需要对同一文件进行多次编辑时，应优先使用此工具而非编辑工具。

要进行多次文件编辑，请提供以下信息：
1. path：要修改的文件的绝对路径（必须是绝对路径，而非相对路径）
2. edits：要执行的一系列编辑操作数组，其中每个编辑操作包含：
   - old_string：要替换的文本（必须与文件内容完全匹配，包括所有空白字符和缩进）
   - new_string：用于替换 old_string 的编辑后文本
   - expected_replacements：您期望执行的替换次数。如果未指定，默认为1。

重要说明：
- 所有编辑操作将按您提供的顺序依次应用
- 每个编辑操作都基于前一个编辑操作的结果进行
- 所有编辑操作必须有效才能使操作成功 - 如果任何编辑失败，则不会应用任何编辑
- 当您需要对同一文件的不同部分进行多次更改时，此工具非常理想

关键要求：
1. 所有编辑操作都遵循与单次编辑工具相同的要求
2. 编辑操作具有原子性 - 要么全部成功，要么全部不应用
3. 请仔细规划您的编辑操作，避免顺序操作之间的冲突

警告：
- 如果 edits.old_string 匹配多个位置且未指定 edits.expected_replacements，该工具将失败
- 如果匹配数量不等于指定的 edits.expected_replacements，该工具将失败
- 如果 edits.old_string 与文件内容不完全匹配（包括空白字符），该工具将失败
- 如果 edits.old_string 和 edits.new_string 相同，该工具将失败
- 由于编辑操作是按顺序应用的，请确保较早的编辑不会影响较晚编辑尝试查找的文本

进行编辑时：
- 确保所有编辑结果都生成地道的、正确的代码
- 不要将代码留在损坏的状态
- 始终使用绝对文件路径（以 / 开头）

如果您想创建新文件，请使用：
- 一个新的文件路径，如果需要包含目录名
- 第一次编辑：空字符串作为 old_string，新文件内容作为 new_string
- 后续编辑：对已创建内容进行常规编辑操作""",
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
            content = p.read_text(encoding="utf-8")
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
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except Exception as e:
            return ToolResult(content=f"写入文件失败: {e}", is_error=True)

        return ToolResult(content=f"已编辑文件，共应用 {len(edits)} 处编辑（{path}）")
