"""ThinkTool — 无副作用的深度思考工具，用于复杂推理"""

from src.tools.base import BaseTool, ToolDefinition, ToolResult

_TOOL_DESCRIPTION = """\
用于复杂推理和深度思考的工具。调用此工具不会产生任何副作用，思考内容会原样返回。

当你面对以下场景时，应该先调用此工具进行思考，而不是急于行动：
- 需要分析多个文件的关系、理清复杂的调用链或依赖关系
- 在多个可行方案之间权衡取舍
- 调试时需要根据已收集的信息推理根因
- 多步骤任务中需要规划执行顺序和策略
- 用户需求有歧义，需要梳理可能的解读
- 工具调用链中间需要停下来整理已有信息，再决定下一步

不要用此工具做简单的事情（如"我要读取文件"），只在真正需要深度推理时使用。"""


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
