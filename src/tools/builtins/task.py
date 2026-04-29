"""TaskTool — 将子任务委派给独立的 Sub Agent 执行

在独立上下文中运行一次性探索任务，完成后只将最终结果返回给主 Agent，
中间的工具调用过程不会污染主对话上下文。
"""

from __future__ import annotations

import os
from typing import AsyncGenerator, TYPE_CHECKING

from src.tools.base import BaseTool, ToolDefinition, ToolResult
from src.tools.registry import ToolRegistry
from src.agent.events import AgentEvent, TextDelta, ToolCallStart, ToolCallResult, ToolResultDelta

if TYPE_CHECKING:
    from src.client import OpenAIClient

_MAX_TURNS = 25  # 子 Agent 最大工具调用轮次

_TOOL_DESCRIPTION = """\
将子任务委派给独立的 Sub Agent 执行。Sub Agent 有自己的上下文，完成后只返回最终结果，中间过程不占用当前对话的上下文空间。

**何时应该使用：**
- 探索性任务：需要大量搜索、阅读才能搞清楚的事情（如"这个模块的调用链是什么"），让 Sub Agent 去翻，只拿结论
- 批量操作：检查所有文件的 TODO、统计代码风格问题、批量验证等，结果汇总后返回
- 上下文快满了：当前对话已经很长，把新任务交给 Sub Agent 避免上下文溢出
- 并行探索：可以同时派出多个 Sub Agent 分别调查不同方向

**不要用于：**
- 一两步就能完成的简单操作（直接用对应工具）
- 需要和用户交互确认的任务（Sub Agent 无法与用户对话）

**重要：** 子任务描述必须自包含——写清楚背景、目标、期望输出格式，因为 Sub Agent 看不到当前对话历史。"""

_SUB_AGENT_PROMPT = """\
你是一个任务执行助手，负责完成主 Agent 委派的子任务。

# 环境
- 工作目录：{cwd}
- 系统：{os_name}，Shell：{shell}

# 规则
1. 专注完成给定的任务，不要偏离主题。
2. 所有路径使用绝对路径。
3. 最小变更：只改需要改的部分。
4. 完成后给出清晰简洁的结果总结，包含关键发现、修改的文件路径、重要细节等。
5. 如果任务无法完成，说明原因和已尝试的方法。
"""


class TaskTool(BaseTool):
    """将子任务委派给独立的 Sub Agent 执行，上下文隔离。"""

    def __init__(self, client: "OpenAIClient", registry: ToolRegistry):
        self._client = client
        self._parent_registry = registry

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="task",
            description=_TOOL_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "子任务的详细描述，包含足够的背景信息和期望输出",
                    },
                },
                "required": ["description"],
            },
        )

    async def execute(self, description: str) -> ToolResult:
        """普通 execute 不会被调用，仅作兜底。"""
        result_text = ""
        async for event in self.run_streaming(description=description):
            if isinstance(event, TextDelta):
                result_text += event.content
        return ToolResult(content=result_text or "[子任务完成]")

    async def run_streaming(self, description: str) -> AsyncGenerator[AgentEvent, None]:
        """直接产出事件流，由 Agent loop 转发给 renderer。"""
        from src.agent import Agent

        # 构建子 Agent 的工具注册表（排除 task 自身，防止递归）
        sub_registry = ToolRegistry()
        for name in self._parent_registry.names:
            if name == "task":
                continue
            tool = self._parent_registry.get(name)
            if tool is not None:
                sub_registry.register(tool)

        sub_agent = Agent(
            client=self._client,
            registry=sub_registry,
            system_prompt=_SUB_AGENT_PROMPT.format(
                cwd=os.getcwd(),
                os_name=os.name,
                shell=os.getenv("SHELL", "unknown"),
            ),
            session_manager=None,
        )

        # 运行子任务，将子 Agent 事件转换为 ToolResultDelta
        turn_count = 0
        text_parts: list[str] = []
        text_buffer = ""  # 文本行缓冲

        async for event in sub_agent.run(description):
            if isinstance(event, ToolCallStart):
                args_summary = ", ".join(
                    f"{k}={repr(v)[:50]}" for k, v in list(event.arguments.items())[:3]
                )
                yield ToolResultDelta(tool_name="task", content=f"▶ {event.tool_name}({args_summary})")
                turn_count += 1
                if turn_count >= _MAX_TURNS:
                    sub_agent.cancel()
                    yield ToolResultDelta(tool_name="task", content=f"⚠ 已达最大工具调用次数 ({_MAX_TURNS})，自动终止")
                    break

            elif isinstance(event, ToolCallResult):
                preview = _make_result_preview(event.result)
                yield ToolResultDelta(tool_name="task", content=f"  ✔ {preview}")

            elif isinstance(event, TextDelta):
                text_parts.append(event.content)
                # 按行缓冲：凑够完整行才产出
                text_buffer += event.content
                while "\n" in text_buffer:
                    line, text_buffer = text_buffer.split("\n", 1)
                    if line.strip():
                        yield ToolResultDelta(tool_name="task", content=f"  {line.strip()}")

        # flush 残余文本
        if text_buffer.strip():
            yield ToolResultDelta(tool_name="task", content=f"  {text_buffer.strip()}")

        # 产出最终结果（供 agent 持久化）
        final_text = "".join(text_parts).strip()
        yield ToolCallResult(
            tool_name="task",
            result=final_text or "[子任务完成，无文本输出]",
        )


def _make_result_preview(result: str, max_len: int = 100) -> str:
    """从工具结果中提取第一行有意义的内容作为预览。"""
    for line in result.splitlines():
        stripped = line.strip()
        if not stripped or stripped.isdigit():
            continue
        if len(stripped) <= max_len:
            return stripped
        return stripped[:max_len] + "…"
    fallback = result[:max_len].replace("\n", " ")
    if len(result) > max_len:
        fallback += "…"
    return fallback
