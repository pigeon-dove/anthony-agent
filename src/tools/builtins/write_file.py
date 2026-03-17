"""WriteFile 工具 — 创建或覆盖写入文件"""

from pathlib import Path

from src.tools.base import BaseTool, ToolDefinition, ToolResult


class WriteFileTool(BaseTool):
    """将内容写入指定文件（不存在则创建，存在则覆盖）"""

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="write_file",
            description="""\
写入文件到本地文件系统。

使用方法：
- 此工具将覆盖指定路径上已存在的文件。""",
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
        try:
            p = Path(path).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return ToolResult(content=f"已写入 {path}（{len(content)} 字符）")
        except Exception as e:
            return ToolResult(content=f"写入文件失败: {e}", is_error=True)
