"""EditFile 工具 — 搜索替换模式编辑文件"""

from pathlib import Path

from src.tools.base import BaseTool, ToolDefinition, ToolResult


class EditFileTool(BaseTool):
    """通过搜索替换的方式编辑文件"""

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="edit_file",
            description="""\
在文件中执行精确的字符串替换，并进行严格的出现次数验证。

用法：
- 当编辑来自阅读工具输出的文本时，请确保保留行号前缀之后显示的精确缩进（制表符/空格）。行号前缀格式为：空格 + 行号 + 制表符。制表符之后的所有内容是需要匹配的实际文件内容。切勿在 old_string 或 new_string 中包含行号前缀的任何部分。
- 始终优先编辑代码库中的现有文件。除非明确要求，否则切勿创建新文件。""",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件的绝对路径",
                    },
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
                        "description": "预期替换次数，默认为 1。用于验证 old_string 在文件中的匹配数量是否符合预期。",
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
        )

    async def execute(self, path: str, old_string: str, new_string: str, expected_replacements: int = 1) -> ToolResult:
        p = Path(path).resolve()
        if not p.exists():
            return ToolResult(content=f"文件不存在: {path}", is_error=True)
        if not p.is_file():
            return ToolResult(content=f"不是文件: {path}", is_error=True)

        try:
            content = p.read_text(encoding="utf-8")

            # 校验匹配次数
            count = content.count(old_string)
            if count == 0:
                return ToolResult(content="old_string 在文件中未找到匹配", is_error=True)
            if count != expected_replacements:
                return ToolResult(
                    content=f"预期替换 {expected_replacements} 处，但找到 {count} 处匹配",
                    is_error=True,
                )

            # 执行替换并写回
            new_content = content.replace(old_string, new_string)
            p.write_text(new_content, encoding="utf-8")
            return ToolResult(content=f"已替换 {count} 处（{path}）")
        except Exception as e:
            return ToolResult(content=f"编辑文件失败: {e}", is_error=True)
