"""Anthony Agent — CLI 入口"""

import asyncio

from src.client import OpenAIClient
from src.tools import ToolRegistry, BaseTool, ToolDefinition, ToolResult
from src.agent import Agent
from src.agent.events import TextDelta, ToolCallStart, ToolCallResult, ResponseComplete, UsageReport

# ── 系统提示词 ─────────────────────────────────────────────

SYSTEM_PROMPT = """\
你是一个 AI 助手，可以执行用户指定的任务。

注意事项：
1. 在调用工具之前，请先用一句话说明你要做什么。
"""

# ── 示例工具（后续移到 src/tools/builtins/）──────────────────

class GetWeatherTool(BaseTool):
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_weather",
            description="查询指定城市的当前天气",
            parameters={
                "type": "object",
                "properties": {"city": {"type": "string", "description": "城市名称，如：北京"}},
                "required": ["city"],
            },
        )

    async def execute(self, city: str) -> ToolResult:
        return ToolResult(content=f"{city}：晴，25°C，微风")


# ── 主函数 ───────────────────────────────────────────────────

async def main():
    registry = ToolRegistry()
    registry.register(GetWeatherTool())

    agent = Agent(client=OpenAIClient(), registry=registry, system_prompt=SYSTEM_PROMPT)

    print("Anthony Agent (输入 exit 退出)\n")
    while True:
        user_input = input("> ").strip()
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break

        async for event in agent.run(user_input):
            if isinstance(event, TextDelta):
                print(f"\033[31m{event.content}\033[0m", end="", flush=True)
            elif isinstance(event, ToolCallStart):
                print(f"\033[32m[Call]\t{event.tool_name}({event.arguments})\033[0m")
            elif isinstance(event, ToolCallResult):
                print(f"\033[32m[Tool]\t{event.tool_name} → {event.result}\033[0m")
            elif isinstance(event, ResponseComplete):
                print() # 文本输出完毕换行
            elif isinstance(event, UsageReport):
                print(f"\033[90m[Usage]\tprompt={event.prompt_tokens} completion={event.completion_tokens} total={event.total_tokens}\033[0m")


if __name__ == "__main__":
    asyncio.run(main())