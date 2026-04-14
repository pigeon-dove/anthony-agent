"""ThinkTool — 无副作用的深度思考工具，用于复杂推理"""

from src.tools.base import BaseTool, ToolDefinition, ToolResult

_TOOL_DESCRIPTION = """\
停下来深度思考。无副作用，思考内容原样返回。

**何时必须使用：**
- 你即将做一个不可逆操作（编辑文件、执行命令）前，对方案还不确定
- 你收集了大量信息（读了多个文件、搜了多次），需要整理线索再行动
- 用户的需求有多种理解方式，你需要推理出最合理的那个
- 你连续调用工具 3 次以上仍未解决问题，需要换个思路

**不要用于：**
- 简单的下一步决策（如"接下来读哪个文件"）
- 复述用户的问题"""


class ThinkTool(BaseTool):
    """无副作用的思考工具：输入思考内容，原样返回"""

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="think",
            description=_TOOL_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "thought": {
                        "type": "string",
                        "description": "你的思考内容：分析、推理、规划等",
                    },
                },
                "required": ["thought"],
            },
        )

    async def execute(self, thought: str) -> ToolResult:
        return ToolResult(content=thought)
