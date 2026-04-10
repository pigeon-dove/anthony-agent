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
        self._last_prompt_tokens: int = 0

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
            # 从原始消息中提取最后一次 prompt_tokens（供 UI 恢复进度条）
            for m in reversed(raw):
                usage = m.get("usage")
                if usage and "prompt_tokens" in usage:
                    self._last_prompt_tokens = usage["prompt_tokens"]
                    break
            messages = [{k: v for k, v in m.items() if k != "usage"} for m in raw]
            repaired = self._repair_messages(messages)
            if len(repaired) != len(messages):
                # 有修复，回写持久化
                self._session.overwrite_messages(repaired)
            self._messages = repaired

    @staticmethod
    def _repair_messages(messages: list[dict]) -> list[dict]:
        """修复中途退出导致的不完整消息序列。

        检查所有 assistant 消息中的 tool_calls，如果对应的 tool result 缺失，
        补一个占位消息，避免发送给 API 时报错。
        """
        existing_results = {
            m["tool_call_id"] for m in messages
            if m.get("role") == "tool" and m.get("tool_call_id")
        }
        repaired: list[dict] = []
        for m in messages:
            repaired.append(m)
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    tc_id = tc.get("id")
                    if tc_id and tc_id not in existing_results:
                        repaired.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": "[上次会话中途退出，此工具未执行]",
                        })
                        existing_results.add(tc_id)
        return repaired

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
        # 过滤掉内部标记字段（如 _compacted），不发送给 API
        # 同时确保 assistant 消息的 content 不为缺失（API 要求必须存在）
        cleaned = []
        for m in self._messages:
            d = {k: v for k, v in m.items() if not k.startswith("_")}
            if d.get("role") == "assistant" and "content" not in d:
                d["content"] = ""
            cleaned.append(d)
        return [{"role": "system", "content": prompt}] + cleaned

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
