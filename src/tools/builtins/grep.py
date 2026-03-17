"""GrepTool — 快速内容搜索"""

import re
from pathlib import Path

from src.tools.base import BaseTool, ToolDefinition, ToolResult

# 单次搜索最大结果行数
MAX_RESULTS = 200


class GrepTool(BaseTool):
    """基于 Python re 模块的快速内容搜索工具"""

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="grep",
            description="""\
快速内容搜索工具，在文件中搜索匹配正则表达式的行。

- 输出格式为 "文件路径:行号:匹配内容"，结果按文件修改时间排序
- 支持完整的 Python 正则语法（例如 "log.*Error"、"def\\s+\\w+"、"TODO|FIXME"）
- 可通过 include 参数限定文件类型（例如 "*.py"、"*.{{ts,tsx}}"），默认搜索所有文件
- 最多返回 {max_results} 条结果
- 适用于：查找函数定义、变量引用、错误信息、特定代码模式等
- 不适用于：按文件名查找文件（请用 glob）
- 您有能力在单个响应中调用多个工具。将可能用到的多个搜索推测性地批量执行，通常效果更佳""".format(max_results=MAX_RESULTS),
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
                        "description": "按文件名模式过滤（可选），例如 '*.py'、'*.{js,ts}'。不指定则搜索所有文件",
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

        # 收集所有匹配的文件，按修改时间降序排序
        files = sorted(
            (f for f in root.rglob(include or "*") if f.is_file()),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        # 逐文件逐行搜索，收集匹配结果
        results: list[str] = []
        for file in files:
            try:
                text = file.read_text(errors="ignore")
            except (OSError, PermissionError):
                continue

            rel = file.relative_to(root)
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    results.append(f"{rel}:{lineno}:{line}")
                    if len(results) >= MAX_RESULTS:
                        results.append(f"\n(结果已截断，共显示 {MAX_RESULTS} 条)")
                        return ToolResult(content="\n".join(results))

        if not results:
            return ToolResult(content=f"没有匹配 '{pattern}' 的内容")

        return ToolResult(content="\n".join(results))