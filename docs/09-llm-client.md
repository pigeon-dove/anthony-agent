# 第九章：LLM 客户端

Agent 的"大脑"是 LLM，但 LLM 只暴露了一个 HTTP API。本章讲解如何把这个 API 包装成 Agent 可用的异步流式客户端。

## 设计目标

客户端需要解决四个问题：

1. **流式输出** — Agent 需要逐 token 渲染，不能等整个响应完成
2. **工具调用解析** — tool_calls 是跨多个 chunk 分片到达的，需要累积拼接
3. **自动重试** — 网络抖动和限流不应让整个对话崩溃
4. **模型无关** — 换一个 `.env` 就能切换 OpenAI / DeepSeek / Qwen / Ollama

## 整体架构

```
┌───────────────────────────────────────────┐
│  Agent                                    │
│   ├── stream_chat(messages, tools)        │
│   │     返回 StreamResponse               │
│   │       async for delta in stream:      │
│   │         处理每个 StreamDelta           │
│   │       msg = stream.message  ← 累积结果 │
│   └── chat(messages, tools)               │
│         返回 Message ← 非流式，用于压缩等  │
└─────────────┬─────────────────────────────┘
              │
       ┌──────▼──────┐
       │ OpenAIClient │
       │  _retry()   │ ← 指数退避重试
       │  _build_params() │
       └──────┬──────┘
              │
       ┌──────▼──────┐
       │ AsyncOpenAI  │ ← openai SDK
       └─────────────┘
```

三个类各司其职：

- **`OpenAIClient`** — 请求构建、重试、参数组装
- **`StreamResponse`** — 流式响应的累积器，解析 chunk 并拼接最终 Message
- **`StreamDelta`** — 单个 chunk 的数据载体

## 数据模型

### StreamDelta：一个 chunk 的内容

```python
class StreamDelta(BaseModel):
    content: str | None = None
    reasoning_content: str | None = None      # thinking 模型的推理片段
    tool_call_index: int | None = None
    tool_call_id: str | None = None
    tool_call_name: str | None = None
    tool_call_arguments: str | None = None    # JSON 片段，不是完整 JSON

    @property
    def is_tool_call(self) -> bool:
        return self.tool_call_index is not None
```

一个 chunk 可能只包含其中一种内容——文本、推理、或工具调用片段。消费端通过字段是否为 `None` 来判断类型。

### Message：一次完整响应

```python
class Message(BaseModel):
    role: str = "assistant"
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
```

Message 提供两种序列化方式：

| 方法 | 用途 | 包含 reasoning_content |
|---|---|---|
| `to_api_dict()` | 回传给 LLM API | 仅当有 tool_calls 时 |
| `to_storage_dict()` | 写入 JSONL 文件 | 仅当有 tool_calls 时 |

为什么 reasoning_content 只在有 tool_calls 时保留？因为某些 thinking 模型要求：**同一轮 agent loop 内部**，assistant 消息的推理内容必须原样回传，否则 API 报错。而 loop 结束后，历史消息里的 reasoning_content 会在内存中清除（省 token），但文件里保留（防中途退出后恢复丢失）。

### ToolCall：单个工具调用

```python
class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str   # 完整的 JSON 字符串

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }
```

`to_dict()` 产出 OpenAI API 要求的嵌套格式。虽然 ToolCall 本身是扁平的（方便内部使用），但 API 要求 `function` 是个嵌套对象。

## StreamResponse：流式累积器

这是最核心的类。它解决了一个关键问题：**工具调用的 JSON 参数是分多个 chunk 到达的**。

```
chunk 1: tool_call_index=0, id="call_abc", name="bash"
chunk 2: tool_call_index=0, arguments='{"comm'
chunk 3: tool_call_index=0, arguments='and": "ls"}'
```

三个 chunk 才拼出一个完整的 tool_call。StreamResponse 用一个 `_tc_map: dict[int, dict]` 按 index 累积：

```python
class StreamResponse:
    def __init__(self, raw_stream):
        self._content_parts: list[str] = []
        self._reasoning_parts: list[str] = []
        self._tc_map: dict[int, dict] = {}     # index → {id, name, arguments}
        self._usage = Usage()

    async def _iterate(self) -> AsyncGenerator[StreamDelta, None]:
        async for chunk in self._raw:
            # 1. 提取 usage（只有最后一个 chunk 带）
            if chunk.usage:
                self._usage = Usage(...)

            choice = chunk.choices[0] if chunk.choices else None
            if not choice:
                continue
            delta = choice.delta

            # 2. reasoning（thinking 模型）
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                self._reasoning_parts.append(reasoning)
                yield StreamDelta(reasoning_content=reasoning)

            # 3. 文本内容
            if delta.content:
                self._content_parts.append(delta.content)
                yield StreamDelta(content=delta.content)

            # 4. 工具调用（按 index 累积）
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
                    yield StreamDelta(...)

    @property
    def message(self) -> Message:
        """迭代结束后调用，返回累积的完整 Message。"""
        return Message(
            content="".join(self._content_parts) or None,
            reasoning_content="".join(self._reasoning_parts) or None,
            tool_calls=[
                ToolCall(id=v["id"], name=v["name"], arguments=v["arguments"])
                for _, v in sorted(self._tc_map.items())
            ],
            usage=self._usage,
        )
```

使用方式是"先迭代、再取结果"：

```python
stream = await client.stream_chat(messages, tools)
async for delta in stream:
    # 实时渲染到 UI
    if delta.content:
        render_text(delta.content)
    elif delta.reasoning_content:
        render_thinking(delta.reasoning_content)

# 迭代结束，取完整消息
msg = stream.message
```

### 关键设计：reasoning_content 用 getattr

```python
reasoning = getattr(delta, "reasoning_content", None)
```

OpenAI 官方 SDK 的 delta 对象没有 `reasoning_content` 属性——这是 DeepSeek 等 thinking 模型的扩展字段。用 `getattr` 而不是 `delta.reasoning_content` 避免 AttributeError，保持对标准模型的兼容。

## OpenAIClient

### 参数构建

```python
def _build_params(self, messages, tools, stream) -> dict:
    params = {
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
```

两个细节：

1. **`stream_options.include_usage`** — 流式模式下默认不返回 usage，必须显式开启。最后一个 chunk 会带 `usage` 字段
2. **tools 可选** — 压缩等场景不需要工具，传 `None` 时不加 `tools` 参数（有些模型不接受空列表）

### 自动重试

```python
_RETRYABLE = (APIConnectionError, RateLimitError)

async def _retry(self, fn):
    last_err = None
    for attempt in range(self._max_retries):
        try:
            return await fn()
        except _RETRYABLE as e:
            last_err = e
            if attempt < self._max_retries - 1:
                await asyncio.sleep(self._retry_delay * 2 ** attempt)
        except APIError:
            raise       # 非重试类错误直接抛出
    raise last_err
```

**指数退避**：第一次等 1 秒，第二次等 2 秒，第三次等 4 秒。只重试网络错误和限流，其他 API 错误（400 参数错误、401 认证失败等）直接抛出——重试也不会好。

### 非流式调用

```python
async def chat(self, messages, tools=None) -> Message:
    resp = await self._retry(
        lambda: self._client.chat.completions.create(
            **self._build_params(messages, tools, stream=False)
        )
    )
    return self._parse_response(resp)
```

非流式用于压缩等不需要实时渲染的场景。`_parse_response` 解析逻辑和 StreamResponse 类似，只是一次性拿到完整响应。

## 配置系统

```python
# ~/.anthony/.env
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
MODEL_NAME=gpt-4o
MAX_COMPLETION_TOKENS=4096
MAX_INPUT_TOKENS=128000
SUPPORTS_VISION=true
```

所有配置通过环境变量注入，`LLMConfig` 用 Pydantic 的 `Field(default_factory=...)` 读取：

```python
class LLMConfig(BaseModel):
    api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    base_url: str = Field(default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    model_name: str = Field(default_factory=lambda: os.getenv("MODEL_NAME", "gpt-4o"))
    max_completion_tokens: int = Field(default_factory=lambda: int(os.getenv("MAX_COMPLETION_TOKENS", "4096")))
    max_input_tokens: int = Field(default_factory=lambda: int(os.getenv("MAX_INPUT_TOKENS", "128000")))
    supports_vision: bool = Field(default_factory=lambda: os.getenv("SUPPORTS_VISION", "true").lower() == "true")
```

这种设计的好处：
- **单一 `.env` 文件切换模型**——改三行就能从 GPT-4o 换到 DeepSeek
- **合理的默认值**——不配也能用（如果有 `OPENAI_API_KEY` 环境变量）
- **`max_input_tokens` 控制压缩阈值**——不同模型窗口大小不同，需要可配

`supports_vision` 控制是否给 LLM 发图片。纯文本模型（如 DeepSeek-R1）设为 `false` 后，`read_file` 读到图片会返回 `[图片文件]` 文本而不是 base64。

## 设计决策

### 为什么不用 OpenAI SDK 的内置重试？

OpenAI Python SDK 自带重试机制（`max_retries` 参数），但我们自己实现有两个原因：

1. **可控性** — 可以精确控制哪些错误重试、退避策略是什么
2. **日志/事件** — 未来可以在重试时 yield 事件通知 UI

### 为什么流式和非流式是两个方法？

返回类型不同：`stream_chat` 返回 `StreamResponse`（可迭代），`chat` 返回 `Message`（直接拿到结果）。合并成一个方法会让调用方每次都要判断类型。

### 为什么 StreamResponse 不是 dataclass？

它有状态（累积的 parts 和 tc_map），有行为（`_iterate` 和 `message` property），是一个真正的对象，不是纯数据。

## 小结

| 组件 | 职责 |
|---|---|
| `StreamDelta` | 单个 chunk 的数据载体 |
| `StreamResponse` | 流式累积器：逐 chunk 产出 delta，最终拼出 Message |
| `Message` | 完整响应，提供 `to_api_dict` / `to_storage_dict` 两种序列化 |
| `OpenAIClient` | 请求构建 + 指数退避重试 + 流式/非流式两种调用 |
| `LLMConfig` | 环境变量驱动的配置，一个 `.env` 切换模型 |

下一章我们进入最后一个话题——TUI 界面，把所有这些组件串起来，变成用户可以交互的终端应用。
