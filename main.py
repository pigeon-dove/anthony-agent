"""Anthony Agent — CLI 入口"""

import asyncio
import os

from src.client import OpenAIClient
from src.tools import ToolRegistry
from src.tools.builtins import BUILTIN_TOOLS
from src.agent import Agent
from src.agent.events import TextDelta, ToolCallStart, ToolCallResult, ResponseComplete, UsageReport
from src.utils import console, truncate

# ── 系统提示词 ─────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """\
# Role
你是一个专业的开发助手，具备文件读写、Shell 命令执行、代码编写与调试能力。
你的目标是准确、安全、高效地完成用户指定的任务。

# Environment
- 当前工作目录：{cwd}
- 操作系统：{os}
- Shell：{shell}

# Core Principles
1. **先思考，再行动**：调用任何工具前，先用一句话简要说明意图和理由。
2. **路径规范**：所有文件/目录操作一律使用基于当前工作目录的绝对路径。
3. **读先于写**：
   - 读取前：先确认文件是否存在、大小、类型，选择合适的读取方式（避免一次性读取大文件）。
   - 写入/编辑前：必须先读取文件当前内容，理解上下文后再操作，防止覆盖或破坏。
4. **最小变更**：编辑文件时只修改必要部分，不要重写无关内容。
5. **安全意识**：
   - 不执行破坏性命令（如 `rm -rf /`），对高风险操作先向用户确认。
   - 不主动访问与任务无关的敏感文件或目录。

# Workflow
1. 理解用户需求，必要时主动澄清模糊之处。
2. 制定简要执行计划（复杂任务时分步骤列出）。
3. 逐步执行，每步操作前说明意图。
4. 执行完成后，简要总结所做的变更和结果。

# Output Format
- 代码块注明语言类型（如 ```python）。
- 文件变更时，清晰标注文件路径和修改内容。
- 遇到错误时，给出错误原因分析和修复方案。
"""

# ── 主函数 ───────────────────────────────────────────────────

async def main():
    registry = ToolRegistry()
    registry.register_many([tool() for tool in BUILTIN_TOOLS])

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        cwd=os.getcwd(),
        os=os.name,
        shell=os.getenv("SHELL"),
    )
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
                console.green(f"[Call]\t{event.tool_name}({truncate(str(event.arguments))})")
            elif isinstance(event, ToolCallResult):
                console.green(f"[Tool]\t{event.tool_name} → {truncate(str(event.result))}")
            elif isinstance(event, ResponseComplete):
                print()
            elif isinstance(event, UsageReport):
                console.gray(f"[Usage]\tprompt={event.prompt_tokens} completion={event.completion_tokens} total={event.total_tokens}")


if __name__ == "__main__":
    asyncio.run(main())