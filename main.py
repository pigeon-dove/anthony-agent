"""Anthony Agent — CLI 入口"""

import asyncio
import os

from src.client import OpenAIClient
from src.tools import ToolRegistry
from src.tools.builtins import BUILTIN_TOOLS
from src.agent import Agent
from src.agent.events import TextDelta, ToolCallStart, ToolCallResult, ResponseComplete, UsageReport
from src.utils import console

# ── 系统提示词 ─────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """\
你是一个 AI 助手，可以执行用户指定的任务。

注意事项：在调用工具之前，请先用一句话说明你要做什么。
"""

# ── 主函数 ───────────────────────────────────────────────────

async def main():
    registry = ToolRegistry()
    registry.register_many([tool() for tool in BUILTIN_TOOLS])

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(cwd=os.getcwd())
    agent = Agent(client=OpenAIClient(), registry=registry, system_prompt=system_prompt)

    print("Anthony Agent (输入 exit 退出)\n")
    while True:
        user_input = input("> ").strip()
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break

        async for event in agent.run(user_input):
            if isinstance(event, TextDelta):
                console.red(event.content, end="", flush=True)
            elif isinstance(event, ToolCallStart):
                console.green(f"[Call]\t{event.tool_name}({event.arguments})")
            elif isinstance(event, ToolCallResult):
                console.green(f"[Tool]\t{event.tool_name} → {event.result}")
            elif isinstance(event, ResponseComplete):
                print()
            elif isinstance(event, UsageReport):
                console.gray(f"[Usage]\tprompt={event.prompt_tokens} completion={event.completion_tokens} total={event.total_tokens}")


if __name__ == "__main__":
    asyncio.run(main())