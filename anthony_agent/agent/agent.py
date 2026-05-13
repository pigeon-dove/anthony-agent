"""Agent Loop — 事件驱动的 ReAct 循环"""

import asyncio
import json
from typing import AsyncGenerator

from anthony_agent.client import OpenAIClient
from anthony_agent.client.models import Message
from anthony_agent.tools import ToolRegistry
from anthony_agent.tools.base import BaseTool, ToolResult
from anthony_agent.memory.session import SessionManager
from anthony_agent.memory.compactor import micro_compact, check_compact, do_compact, CompactCheck, calc_total_tokens
from anthony_agent.agent.events import (
    AgentEvent, ReasoningDelta, TextDelta, ToolCallStart, ToolArgsDelta,
    ToolCallResult, ToolResultDelta, ResponseComplete, UsageReport,
    CompactStart, CompactComplete,
)
from anthony_agent.agent.stream_parser import STREAM_FIELDS, ArgumentsStreamParser


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

        # loop 结束，清理历史消息中的 reasoning_content（仅 loop 内部需要保留）
        for m in self._messages:
            m.pop("reasoning_content", None)

    def load_history(self) -> None:
        if self._session:
            raw = self._session.load_messages()
            for m in reversed(raw):
                usage = m.get("usage")
                if usage and "prompt_tokens" in usage:
                    self._last_prompt_tokens = usage["prompt_tokens"]
                    break
            repaired = self._repair_messages(raw)
            if len(repaired) != len(raw):
                self._session.overwrite_messages(repaired)
            self._messages = repaired

    @staticmethod
    def _repair_messages(messages: list[dict]) -> list[dict]:
        """修复中途退出导致的不完整消息序列。"""
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

            if delta.reasoning_content:
                yield ReasoningDelta(content=delta.reasoning_content)

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
                        yield ToolArgsDelta(
                            tool_name=tool_name,
                            field_name=STREAM_FIELDS[tool_name],
                            content=extracted,
                        )

        yield stream.message

    async def _execute_tools(self, msg: Message) -> AsyncGenerator[AgentEvent, None]:
        """执行工具调用。普通工具并行发起，流式工具串行；UI 事件按原始顺序 yield。"""
        # 预解析参数，判断每个工具是否走流式
        parsed: list[tuple] = []  # (tc, args, is_streaming)
        for tc in msg.tool_calls:
            args = json.loads(tc.arguments)
            tool = self._registry.get(tc.name)
            is_streaming = tool is not None and type(tool).run_streaming is not BaseTool.run_streaming
            parsed.append((tc, args, is_streaming))

        # 并行发起所有普通工具
        pending_tasks: dict[str, asyncio.Task] = {}
        for tc, args, is_streaming in parsed:
            if not is_streaming:
                pending_tasks[tc.id] = asyncio.create_task(
                    self._registry.execute(tc.name, args)
                )

        # 图片 user message 必须延后写入：OpenAI 要求 assistant(tool_calls=[A,B]) 之后
        # 必须先连续出现所有 tool messages，之间不能插入其他 role。
        deferred_image_msgs: list[dict] = []

        # 按原始顺序逐个 yield 事件
        for tc, args, is_streaming in parsed:
            if self._cancelled:
                self._persist({"role": "tool", "tool_call_id": tc.id,
                               "content": "[用户中断，此工具未执行]"})
                continue

            yield ToolCallStart(tool_name=tc.name, arguments=args)

            if is_streaming:
                tool = self._registry.get(tc.name)
                assert tool is not None
                stream = tool.run_streaming(**args)
                assert stream is not None
                result_event: ToolCallResult | None = None
                partial_lines: list[str] = []
                async for event in stream:
                    if isinstance(event, ToolCallResult):
                        result_event = event
                    else:
                        if isinstance(event, ToolResultDelta):
                            partial_lines.append(event.content)
                        yield event
                    if self._cancelled and result_event is None:
                        break
                if self._cancelled and result_event is None:
                    partial = "\n".join(partial_lines)
                    if len(partial) > 30_000:
                        half = 15_000
                        partial = f"{partial[:half]}\n\n... [截断 {len(partial) - 30_000} 字符] ...\n\n{partial[-half:]}"
                    content = f"{partial}\n[用户中断，以上是中断前的部分输出]" if partial else "[用户中断，无输出]"
                    result = ToolResult(content=content)
                    # 先 persist 再 yield：yield 后 generator 可能被 close
                    self._persist({"role": "tool", "tool_call_id": tc.id, "content": content})
                    yield ToolCallResult(tool_name=tc.name, result=content)
                    continue
                else:
                    content = result_event.result if result_event else "[流式工具无输出]"
                    is_error = result_event.is_error if result_event else False
                    result = ToolResult(content=content, is_error=is_error)
                    yield result_event or ToolCallResult(tool_name=tc.name, result=content)
            else:
                result = await pending_tasks[tc.id]
                yield ToolCallResult(tool_name=tc.name, result=result.content)

            # 正常完成：tool message 落库
            msgs = result.to_messages(tc.id)
            self._persist(msgs[0])
            deferred_image_msgs.extend(msgs[1:])

        # 所有 tool messages 写完后，再追加图片 user messages
        for image_msg in deferred_image_msgs:
            self._persist(image_msg)

    async def _try_compact(self) -> AsyncGenerator[AgentEvent, None]:
        for _ in range(3):
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

    async def force_compact(self) -> AsyncGenerator[AgentEvent, None]:
        """用户手动触发上下文压缩。"""
        if not self._messages:
            return
        total = calc_total_tokens(self._messages, self._system_prompt)
        check = CompactCheck(current_tokens=total, threshold_tokens=total)
        yield CompactStart(current_tokens=total, threshold_tokens=total, manual=True)
        result = await do_compact(
            messages=self._messages,
            system_prompt=self._system_prompt,
            client=self._client,
            session_manager=self._session,
            check=check,
        )
        yield CompactComplete(before_tokens=result.before_tokens, after_tokens=result.after_tokens)

    # ── 辅助方法 ──────────────────────────────────────────

    def _build_messages(self) -> list[dict]:
        prompt = self._system_prompt
        tool_context = self._registry.collect_context()
        if tool_context:
            prompt += "\n\n" + tool_context
        cleaned = []
        for m in self._messages:
            d = {k: v for k, v in m.items() if not k.startswith("_") and k != "usage"}
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
