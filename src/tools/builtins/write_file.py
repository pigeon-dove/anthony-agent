"""WriteFile 工具 — 创建或覆盖写入文件"""

import asyncio
from pathlib import Path

from src.tools.base import BaseTool, ToolDefinition, ToolResult

_TOOL_DESCRIPTION = """\
创建新文件或完全覆写已有文件的内容。父目录不存在时会自动创建。
使用指南：
- 使用绝对路径指定目标文件
- 文件已存在时内容会被完全覆盖，请谨慎使用
- 修改现有文件的部分内容时，优先使用 edit_file 或 multi_edit 工具
- 仅在创建全新文件或需要完全重写文件时使用"""


class WriteFileTool(BaseTool):
    """将内容写入指定文件（不存在则创建，存在则覆盖）"""

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="write_file",
            description=_TOOL_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件的绝对路径",
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入的文件内容",
                    },
                },
                "required": ["path", "content"],
            },
        )

    async def execute(self, path: str, content: str) -> ToolResult:
        p = Path(path).resolve()
        existed = p.is_file()
        await asyncio.to_thread(lambda: p.parent.mkdir(parents=True, exist_ok=True))
        await asyncio.to_thread(p.write_text, content, encoding="utf-8")
        action = "已覆写" if existed else "已创建"
        return ToolResult(content=f"{action} {path}（{len(content)} 字符）")
