"""ReadFile 工具 — 读取文件内容"""

from pathlib import Path

from src.tools.base import BaseTool, ToolDefinition, ToolResult


class ReadFileTool(BaseTool):
    """读取指定文件的内容，支持可选的行范围"""

    MAX_LINES = 2000        # 默认最多读取行数
    MAX_LINE_CHARS = 2000   # 单行最大字符数

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_file",
            description="""\
**从本地文件系统读取文件。** 您可以使用此工具直接访问任何文件。假设此工具能够读取机器上的所有文件。如果用户提供了文件路径，请假定该路径有效。即使读取不存在的文件也可以，系统会返回错误信息。

使用方法：
- **path** 参数必须是绝对路径，而非相对路径。
- 默认从文件开头读取，最多读取 2000 行。
- 可选择指定行偏移量和行数限制（尤其对长文件很方便），但建议不提供这些参数以读取整个文件。
- 任何长度超过 2000 个字符的行都将被截断。
- 结果以 **cat -n** 格式返回，行号从 1 开始。
- 您具备在单次回复中调用多个工具的能力。建议批量推测性读取多个潜在有用的文件，这通常更好。""",
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

        try:
            lines = p.read_text(encoding="utf-8").splitlines()

            # 行范围切片（offset 从 1 开始，limit 默认 MAX_LINES）
            start = (offset - 1) if offset and offset > 0 else 0
            count = limit if limit and limit > 0 else self.MAX_LINES
            end = min(start + count, len(lines))
            selected = lines[start:end]

            # cat -n 格式：行号从 1 开始，超长行截断
            output_lines: list[str] = []
            for i, line in enumerate(selected, start=start + 1):
                if len(line) > self.MAX_LINE_CHARS:
                    line = line[: self.MAX_LINE_CHARS] + "..."
                output_lines.append(f"     {i}\t{line}")

            content = "\n".join(output_lines)
            return ToolResult(content=content)
        except Exception as e:
            return ToolResult(content=f"读取文件失败: {e}", is_error=True)
