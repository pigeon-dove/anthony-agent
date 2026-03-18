"""EditFile 工具 — 搜索替换模式编辑文件"""

import asyncio
from pathlib import Path

from src.tools.base import BaseTool, ToolDefinition, ToolResult

_TOOL_DESCRIPTION = """\
通过**精确字符串匹配**进行搜索替换来编辑文件，自带匹配数量验证以确保安全。

核心规则：
- old_string 必须与文件内容逐字符精确匹配，包括所有空白、缩进和换行
- read_file 输出带行号前缀（空格+行号+制表符），old_string 中不要包含这些前缀
- expected_replacements 默认为 1，匹配数量不符时操作会失败

适用场景：
- 对文件进行单处精确修改
- 建议编辑前先用 read_file 确认文件内容

不适用场景：
- 对同一文件进行多处编辑时，请改用 multi_edit 工具（更高效）
- 创建新文件或完全重写时，请改用 write_file 工具"""


class EditFileTool(BaseTool):
    """通过搜索替换的方式编辑文件"""

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="edit_file",
            description=_TOOL_DESCRIPTION,
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
        if old_string == new_string:
            return ToolResult(content="old_string 与 new_string 相同，无需替换", is_error=True)

        content = await asyncio.to_thread(p.read_text, encoding="utf-8")

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
        await asyncio.to_thread(p.write_text, new_content, encoding="utf-8")
        return ToolResult(content=f"已替换 {count} 处（{path}）")
