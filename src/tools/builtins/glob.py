"""GlobTool — 快速文件模式匹配"""

from pathlib import Path

from src.tools.base import BaseTool, ToolDefinition, ToolResult


class GlobTool(BaseTool):
    """基于 glob 模式的快速文件搜索工具"""

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="glob",
            description="""\
快速文件模式匹配工具，适用于任意规模的代码库。

- 支持 glob 模式，例如 "**/*.py" 或 "src/**/*.ts"
- 返回按修改时间排序的匹配文件路径
- 当需要按文件名模式查找文件时，使用此工具
- 当您进行可能需要多轮 glob 和 grep 的开放性搜索时，请使用 Agent 工具
- 您有能力在单个响应中调用多个工具。将可能用到的多个搜索推测性地批量执行，通常效果更佳""",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "要搜索的 glob 模式，例如 '**/*.py'",
                    },
                    "path": {
                        "type": "string",
                        "description": "搜索的起始目录绝对路径",
                    },
                },
                "required": ["pattern", "path"],
            },
        )

    async def execute(self, pattern: str, path: str) -> ToolResult:
        root = Path(path).resolve()

        if not root.exists():
            return ToolResult(content=f"路径不存在: {path}", is_error=True)
        if not root.is_dir():
            return ToolResult(content=f"不是目录: {path}", is_error=True)

        try:
            # glob 匹配，只保留文件
            files = [f for f in root.glob(pattern) if f.is_file()]
        except ValueError as e:
            return ToolResult(content=f"无效的 glob 模式: {e}", is_error=True)

        if not files:
            return ToolResult(content=f"没有匹配 '{pattern}' 的文件")

        # 按修改时间降序排序
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

        # 输出相对于搜索根目录的路径
        lines = [str(f.relative_to(root)) for f in files]
        return ToolResult(content="\n".join(lines))
