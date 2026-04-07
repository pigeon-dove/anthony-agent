"""Agent Loop — 最简核心循环"""

import json
from typing import AsyncGenerator

from src.client import OpenAIClient
from src.tools import ToolRegistry
from src.agent.events import (
    AgentEvent, TextDelta, ToolCallStart, ToolCallArgumentsDelta,
    ToolCallResult, ResponseComplete, UsageReport,
)

SYSTEM_PROMPT = "You are a helpful assistant."

# 需要流式输出的工具字段映射：tool_name → 要流式显示的字段名
_STREAM_FIELDS: dict[str, str] = {
    "write_file": "content",
    "edit_file": "new_string",
}


class _ArgumentsStreamParser:
    """从工具调用 arguments 的 JSON 增量中，提取指定字段的文本增量。

    使用启发式状态机：检测到 `"field_name":"` 或 `"field_name": "` 后进入捕获模式，
    逐字符处理转义，直到遇到未转义的 `"` 结束。

    支持多种 JSON 格式（有无空格）：
    - {"content":"value"}
    - {"content": "value"}
    - {"content" : "value"}
    """

    def __init__(self, field_name: str):
        self._field_name = field_name
        # 多种可能的 trigger 格式
        self._triggers = [
            f'"{field_name}":"',    # 无空格
            f'"{field_name}": "',   # 冒号后一个空格
            f'"{field_name}" : "',  # 冒号前后各一个空格
        ]
        self._buffer = ""       # 累积 buffer，用于检测 trigger
        self._capturing = False # 是否正在捕获字段值
        self._escaped = False   # 上一个字符是否为反斜杠（转义状态）
        self._done = False      # 字段值已结束

    def _check_triggers(self) -> bool | None:
        """检查 buffer 是否匹配任一 trigger。

        返回:
            True  — 完整匹配某个 trigger，应进入捕获模式
            False — buffer 不是任何 trigger 的前缀，应重置
            None  — buffer 是某个 trigger 的前缀，继续累积
        """
        full_match = any(self._buffer == t for t in self._triggers)
        if full_match:
            return True
        prefix_match = any(t.startswith(self._buffer) for t in self._triggers)
        return None if prefix_match else False

    def feed(self, chunk: str) -> str:
        """喂入一段 arguments 增量，返回提取到的字段文本增量（可能为空）"""
        if self._done:
            return ""

        result: list[str] = []

        for ch in chunk:
            if not self._capturing:
                # 还没进入捕获模式，累积 buffer 检测 trigger
                self._buffer += ch
                match = self._check_triggers()
                if match is True:
                    # 完整匹配 trigger，进入捕获模式
                    self._capturing = True
                    self._buffer = ""
                elif match is False:
                    # 不匹配任何 trigger，重置 buffer
                    # 当前字符可能是新 trigger 的开头
                    self._buffer = ch
                    if self._check_triggers() is False:
                        self._buffer = ""
                # match is None: 是某个 trigger 的前缀，继续累积
            else:
                # 正在捕获字段值
                if self._escaped:
                    # 上一个字符是 \，当前字符是被转义的
                    self._escaped = False
                    result.append(self._unescape(ch))
                elif ch == '\\':
                    self._escaped = True
                elif ch == '"':
                    # 未转义的引号，字段值结束
                    self._done = True
                    break
                else:
                    result.append(ch)

        return "".join(result)

    @staticmethod
    def _unescape(ch: str) -> str:
        """处理 JSON 字符串转义"""
        return {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}.get(ch, f"\\{ch}")


class Agent:
    """Agent Loop：流式对话 + 工具调用循环"""

    def __init__(self, client: OpenAIClient, registry: ToolRegistry, system_prompt: str = SYSTEM_PROMPT):
        self._client = client
        self._registry = registry
        self._system_prompt = system_prompt
        self._messages: list[dict] = []

    async def run(self, user_input: str) -> AsyncGenerator[AgentEvent, None]:
        """处理一轮用户输入，yield 事件流"""
        self._messages.append({"role": "user", "content": user_input})
        async for event in self._loop():
            yield event

    def _build_messages(self) -> list[dict]:
        """构建提交给 LLM 的 messages：system prompt + 工具动态上下文 + 对话历史"""
        prompt = self._system_prompt
        tool_context = self._registry.collect_context()
        if tool_context:
            prompt += "\n\n" + tool_context

        return [{"role": "system", "content": prompt}] + self._messages

    async def _loop(self) -> AsyncGenerator[AgentEvent, None]:
        """核心循环：调用 LLM → 执行工具 → 重复，直到 LLM 不再调用工具"""
        while True:
            # 构建本次调用的 messages：注入工具动态上下文
            messages = self._build_messages()

            # 流式调用 LLM，逐 token yield 文本 / 工具参数增量
            tools = self._registry.get_definitions() or None
            stream = await self._client.stream_chat(messages, tools=tools)

            # 每个工具调用的增量解析器：index → (tool_name, parser)
            parsers: dict[int, tuple[str, _ArgumentsStreamParser]] = {}

            async for delta in stream:
                if delta.content:
                    yield TextDelta(content=delta.content)

                if delta.is_tool_call and delta.tool_call_index is not None:
                    idx = delta.tool_call_index
                    # 工具名首次出现时，创建解析器
                    if delta.tool_call_name and idx not in parsers:
                        field = _STREAM_FIELDS.get(delta.tool_call_name)
                        if field:
                            parsers[idx] = (delta.tool_call_name, _ArgumentsStreamParser(field))

                    # 有 arguments 增量时，喂给解析器
                    if delta.tool_call_arguments and idx in parsers:
                        tool_name, parser = parsers[idx]
                        extracted = parser.feed(delta.tool_call_arguments)
                        if extracted:
                            yield ToolCallArgumentsDelta(
                                tool_name=tool_name,
                                field_name=_STREAM_FIELDS[tool_name],
                                delta=extracted,
                            )

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
