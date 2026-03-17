"""Agent Loop — 最简核心循环"""

import json
from typing import AsyncGenerator

from src.client import OpenAIClient
from src.tools import ToolRegistry
from src.agent.events import AgentEvent, TextDelta, ToolCallStart, ToolCallResult, ResponseComplete, UsageReport

SYSTEM_PROMPT = "You are a helpful assistant."


class Agent:
    """Agent Loop：流式对话 + 工具调用循环"""

    def __init__(self, client: OpenAIClient, registry: ToolRegistry, system_prompt: str = SYSTEM_PROMPT):
        self._client = client
        self._registry = registry
        self._messages: list[dict] = [{"role": "system", "content": system_prompt}]

    async def run(self, user_input: str) -> AsyncGenerator[AgentEvent, None]:
        """处理一轮用户输入，yield 事件流"""
        self._messages.append({"role": "user", "content": user_input})
        async for event in self._loop():
            yield event

    async def _loop(self) -> AsyncGenerator[AgentEvent, None]:
        """核心循环：调用 LLM → 执行工具 → 重复，直到 LLM 不再调用工具"""
        while True:
            # 流式调用 LLM，逐 token yield 文本
            tools = self._registry.get_definitions() or None
            stream = await self._client.stream_chat(self._messages, tools=tools)
            async for delta in stream:
                if delta.content:
                    yield TextDelta(content=delta.content)

            msg = stream.message
            self._messages.append(msg.to_message_dict())

            # 有文本输出，标记文本输出结束
            if msg.content:
                yield ResponseComplete()

            # 报告用量
            yield UsageReport(
                prompt_tokens=msg.usage.prompt_tokens,
                completion_tokens=msg.usage.completion_tokens,
                total_tokens=msg.usage.total_tokens,
            )

            # 无工具调用，结束循环
            if not msg.has_tool_calls:
                break

            # 执行所有工具调用，把结果喂回 messages
            for tc in msg.tool_calls:
                args = json.loads(tc.arguments)
                yield ToolCallStart(tool_name=tc.name, arguments=args)
                result = await self._registry.execute(tc.name, args)
                self._messages.append(result.to_message_dict(tc.id))
                yield ToolCallResult(tool_name=tc.name, result=result.content)
