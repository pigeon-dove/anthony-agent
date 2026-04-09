"""OpenAI 异步客户端封装"""

import asyncio
from typing import AsyncGenerator, Callable, Awaitable

from openai import AsyncOpenAI, APIError, APIConnectionError, RateLimitError

from config import app_config, LLMConfig
from src.client.models import Usage, ToolCall, Message, StreamDelta

_RETRYABLE = (APIConnectionError, RateLimitError)


class StreamResponse:
    """流式响应包装器：async for 迭代 StreamDelta，通过 .message 获取累积消息。"""

    def __init__(self, raw_stream):
        self._raw = raw_stream
        self._content_parts: list[str] = []
        self._tc_map: dict[int, dict] = {}
        self._usage = Usage()

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[StreamDelta, None]:
        async for chunk in self._raw:
            if chunk.usage:
                self._usage = Usage(
                    prompt_tokens=chunk.usage.prompt_tokens or 0,
                    completion_tokens=chunk.usage.completion_tokens or 0,
                )

            choice = chunk.choices[0] if chunk.choices else None
            if not choice:
                continue

            delta = choice.delta
            if delta.content:
                self._content_parts.append(delta.content)
                yield StreamDelta(content=delta.content)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    entry = self._tc_map.setdefault(
                        tc.index, {"id": "", "name": "", "arguments": ""}
                    )
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

    @property
    def message(self) -> Message:
        return Message(
            content="".join(self._content_parts) or None,
            tool_calls=[
                ToolCall(id=v["id"], name=v["name"], arguments=v["arguments"])
                for _, v in sorted(self._tc_map.items())
            ],
            usage=self._usage,
        )


class OpenAIClient:
    """异步 OpenAI 客户端（流式 / 非流式 / 自动重试）"""

    def __init__(
        self,
        llm_config: LLMConfig | None = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        cfg = llm_config or app_config.llm
        self._cfg = cfg
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> Message:
        resp = await self._retry(
            lambda: self._client.chat.completions.create(
                **self._build_params(messages, tools, stream=False)
            )
        )
        return self._parse_response(resp)

    async def stream_chat(self, messages: list[dict], tools: list[dict] | None = None) -> StreamResponse:
        raw = await self._retry(
            lambda: self._client.chat.completions.create(
                **self._build_params(messages, tools, stream=True)
            )
        )
        return StreamResponse(raw)

    def _build_params(self, messages: list[dict], tools: list[dict] | None, stream: bool) -> dict:
        params: dict = {
            "model": self._cfg.model_name,
            "messages": messages,
            "max_completion_tokens": self._cfg.max_completion_tokens,
            "stream": stream,
        }
        if stream:
            params["stream_options"] = {"include_usage": True}
        if tools:
            params["tools"] = tools
        return params

    async def _retry(self, fn: Callable[[], Awaitable]):
        last_err = None
        for attempt in range(self._max_retries):
            try:
                return await fn()
            except _RETRYABLE as e:
                last_err = e
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(self._retry_delay * 2 ** attempt)
            except APIError:
                raise
        raise last_err  # type: ignore[misc]

    @staticmethod
    def _parse_response(resp) -> Message:
        msg = resp.choices[0].message
        usage = Usage(
            prompt_tokens=resp.usage.prompt_tokens or 0,
            completion_tokens=resp.usage.completion_tokens or 0,
        ) if resp.usage else Usage()
        return Message(
            role=msg.role,
            content=msg.content,
            tool_calls=[
                ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments)
                for tc in (msg.tool_calls or [])
            ],
            usage=usage,
        )
