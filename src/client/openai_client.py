"""OpenAI 异步客户端封装 — 流式 / 非流式 / 工具调用 / 自动重试"""

import asyncio
from typing import AsyncGenerator, Callable, Awaitable

from openai import AsyncOpenAI, APIError, APIConnectionError, RateLimitError
from pydantic import BaseModel, Field

from config import app_config, LLMConfig


# ── 数据模型 ──────────────────────────────────────────────────

class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str  # JSON 字符串

    def to_dict(self) -> dict:
        """转为 OpenAI tool_calls 数组元素格式"""
        return {"id": self.id, "type": "function", "function": {"name": self.name, "arguments": self.arguments}}


class Message(BaseModel):
    role: str = "assistant"
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    def to_message_dict(self) -> dict:
        """转为可直接 append 到 messages 的 dict（自动省略空字段）"""
        d: dict = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        return d


class StreamDelta(BaseModel):
    """流式增量：文本片段 或 工具调用片段，二选一"""
    content: str | None = None
    tool_call_index: int | None = None
    tool_call_id: str | None = None
    tool_call_name: str | None = None
    tool_call_arguments: str | None = None

    @property
    def is_tool_call(self) -> bool:
        return self.tool_call_index is not None


class StreamResponse:
    """异步流式响应，支持 async for 迭代，结束后通过 .message 获取完整消息"""

    def __init__(self, raw_stream):
        self._raw = raw_stream
        self._message: Message | None = None

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[StreamDelta, None]:
        content_parts: list[str] = []
        tc_map: dict[int, dict] = {}
        usage = Usage()

        async for chunk in self._raw:
            if chunk.usage:
                usage = Usage(
                    prompt_tokens=chunk.usage.prompt_tokens or 0,
                    completion_tokens=chunk.usage.completion_tokens or 0,
                )
            choice = chunk.choices[0] if chunk.choices else None
            if not choice:
                continue
            delta = choice.delta

            if delta.content:
                content_parts.append(delta.content)
                yield StreamDelta(content=delta.content)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    entry = tc_map.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        entry["id"] = tc.id
                    if tc.function and tc.function.name:
                        entry["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        entry["arguments"] += tc.function.arguments
                    yield StreamDelta(
                        tool_call_index=tc.index,
                        tool_call_id=tc.id or None,
                        tool_call_name=tc.function.name if tc.function else None,
                        tool_call_arguments=tc.function.arguments if tc.function else None,
                    )

        self._message = Message(
            content="".join(content_parts) or None,
            tool_calls=[ToolCall(id=v["id"], name=v["name"], arguments=v["arguments"]) for _, v in sorted(tc_map.items())],
            usage=usage,
        )

    @property
    def message(self) -> Message:
        if self._message is None:
            raise RuntimeError("流式响应尚未迭代完成，请先完成 async for 循环")
        return self._message


# ── 客户端 ────────────────────────────────────────────────────

_RETRYABLE = (APIConnectionError, RateLimitError)


class OpenAIClient:
    """异步 OpenAI 客户端"""

    def __init__(self, llm_config: LLMConfig | None = None, max_retries: int = 3, retry_delay: float = 1.0):
        cfg = llm_config or app_config.llm
        self._cfg = cfg
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)

    async def chat(self, messages: list[dict], tools: list[dict] | None = None, **kw) -> Message:
        """非流式调用"""
        resp = await self._retry(lambda: self._client.chat.completions.create(**self._params(messages, tools, stream=False, **kw)))
        return self._parse(resp)

    async def stream_chat(self, messages: list[dict], tools: list[dict] | None = None, **kw) -> StreamResponse:
        """流式调用"""
        raw = await self._retry(lambda: self._client.chat.completions.create(**self._params(messages, tools, stream=True, **kw)))
        return StreamResponse(raw)

    # ── 内部 ──────────────────────────────────────────────

    def _params(self, messages, tools, stream, **kw) -> dict:
        p = {"model": self._cfg.model_name, "messages": messages, "max_completion_tokens": self._cfg.max_tokens, "stream": stream, **kw}
        if stream:
            p["stream_options"] = {"include_usage": True}
        if tools:
            p["tools"] = tools
        return p

    async def _retry(self, fn: Callable[[], Awaitable]):
        """指数退避重试"""
        last_err = None
        for i in range(self._max_retries):
            try:
                return await fn()
            except _RETRYABLE as e:
                last_err = e
                if i < self._max_retries - 1:
                    await asyncio.sleep(self._retry_delay * 2 ** i)
            except APIError:
                raise
        raise last_err  # type: ignore[misc]

    @staticmethod
    def _parse(resp) -> Message:
        msg = resp.choices[0].message
        return Message(
            role=msg.role,
            content=msg.content,
            tool_calls=[ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments) for tc in (msg.tool_calls or [])],
            usage=Usage(prompt_tokens=resp.usage.prompt_tokens or 0, completion_tokens=resp.usage.completion_tokens or 0) if resp.usage else Usage(),
        )
