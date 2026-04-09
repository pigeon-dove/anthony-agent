"""Agent Loop — 事件驱动的 ReAct 循环"""

import json
from typing import AsyncGenerator

from src.client import OpenAIClient
from src.client.models import Message
from src.tools import ToolRegistry
from src.memory.session import SessionManager
from src.memory.compactor import micro_compact, check_compact, do_compact
from src.agent.events import (
    AgentEvent, TextDelta, ToolCallStart, ToolCallArgumentsDelta,
    ToolCallResult, ResponseComplete, UsageReport,
    CompactStart, CompactComplete,
)
from src.agent.stream_parser import STREAM_FIELDS, ArgumentsStreamParser


class Agent:
    """事件驱动的 Agent Loop：流式对话 + 工具调用循环。

    通过 AsyncGenerator[AgentEvent] 向外部输出所有状态变化。
    """

    def __init__(
        self,
        client: OpenAIClient,
        registry: ToolRegistry,
        system_prompt: str,
        session_manager: SessionManager | None = None,
    ):
        self._client = client
        self._registry = registry
        self._system_prompt = system_prompt
        self._session = session_manager
        self._messages: list[dict] = []
        self._cancelled = False

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    async def run(self, user_input: str) -> AsyncGenerator[AgentEvent, None]:
        self._cancelled = False
        self._persist({"role": "user", "content": user_input})

        async for event in self._loop():
            yield event
            if self._cancelled:
                break

    def load_history(self) -> None:
        if self._session:
            raw = self._session.load_messages()
            self._messages = [{k: v for k, v in m.items() if k != "usage"} for m in raw]

    # ── 核心循环 ──────────────────────────────────────────

    async def _loop(self) -> AsyncGenerator[AgentEvent, None]:
        check_context = True

        while True:
            if check_context:
                async for event in self._try_compact():
                    yield event

            micro_compact(self._messages)

            msg: Message | None = None
            async for item in self._stream_llm():
                if isinstance(item, Message):
                    msg = item
                else:
                    yield item

            assert msg is not None

            if self._cancelled:
                self._save_cancelled(msg)
                yield ResponseComplete()
                yield self._make_usage_report(msg)
                break

            self._persist(msg.to_api_dict(), storage_dict=msg.to_storage_dict())

            if msg.content:
                yield ResponseComplete()

            yield self._make_usage_report(msg)

            if not msg.has_tool_calls:
                break

            check_context = False
            async for event in self._execute_tools(msg):
                yield event

    # ── 子流程 ────────────────────────────────────────────

    async def _stream_llm(self) -> AsyncGenerator[AgentEvent | Message, None]:
        messages = self._build_messages()
        tools = self._registry.get_definitions() or None
        stream = await self._client.stream_chat(messages=messages, tools=tools)

        parsers: dict[int, tuple[str, ArgumentsStreamParser]] = {}

        async for delta in stream:
            if self._cancelled:
                break

            if delta.content:
                yield TextDelta(content=delta.content)

            if delta.is_tool_call and delta.tool_call_index is not None:
                idx = delta.tool_call_index
                if delta.tool_call_name and idx not in parsers:
                    field = STREAM_FIELDS.get(delta.tool_call_name)
                    if field:
                        parsers[idx] = (delta.tool_call_name, ArgumentsStreamParser(field))

                if delta.tool_call_arguments and idx in parsers:
                    tool_name, parser = parsers[idx]
                    extracted = parser.feed(delta.tool_call_arguments)
                    if extracted:
                        yield ToolCallArgumentsDelta(
                            tool_name=tool_name,
                            field_name=STREAM_FIELDS[tool_name],
                            delta=extracted,
                        )

        yield stream.message

    async def _execute_tools(self, msg: Message) -> AsyncGenerator[AgentEvent, None]:
        for tc in msg.tool_calls:
            args = json.loads(tc.arguments)
            yield ToolCallStart(tool_name=tc.name, arguments=args)

            result = await self._registry.execute(tc.name, args)
            self._persist(result.to_message_dict(tc.id))

            yield ToolCallResult(tool_name=tc.name, result=result.content)

    async def _try_compact(self) -> AsyncGenerator[AgentEvent, None]:
        for _ in range(3):  # 最多压缩 3 次
            check = check_compact(messages=self._messages, system_prompt=self._system_prompt)
            if not check:
                return

            yield CompactStart(
                current_tokens=check.current_tokens,
                threshold_tokens=check.threshold_tokens,
            )
            result = await do_compact(
                messages=self._messages,
                system_prompt=self._system_prompt,
                client=self._client,
                session_manager=self._session,
                check=check,
            )
            yield CompactComplete(
                before_tokens=result.before_tokens,
                after_tokens=result.after_tokens,
            )

    # ── 辅助方法 ──────────────────────────────────────────

    def _build_messages(self) -> list[dict]:
        prompt = self._system_prompt
        tool_context = self._registry.collect_context()
        if tool_context:
            prompt += "\n\n" + tool_context
        return [{"role": "system", "content": prompt}] + self._messages

    def _persist(self, api_dict: dict, storage_dict: dict | None = None) -> None:
        self._messages.append(api_dict)
        if self._session:
            self._session.append_message(storage_dict or api_dict)

    def _save_cancelled(self, msg: Message) -> None:
        content = (msg.content or "") + "\n[用户中断输出]"
        api_dict = {"role": "assistant", "content": content}
        storage_dict = msg.to_storage_dict()
        storage_dict.pop("tool_calls", None)
        storage_dict["content"] = content
        self._persist(api_dict, storage_dict=storage_dict)

    @staticmethod
    def _make_usage_report(msg: Message) -> UsageReport:
        return UsageReport(
            prompt_tokens=msg.usage.prompt_tokens,
            completion_tokens=msg.usage.completion_tokens,
            total_tokens=msg.usage.total_tokens,
        )
