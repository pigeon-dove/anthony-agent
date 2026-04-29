"""LLM 客户端数据模型"""

from pydantic import BaseModel, Field


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


class Message(BaseModel):
    role: str = "assistant"
    content: str | None = None
    reasoning_content: str | None = None  # DeepSeek/Qwen 等 thinking 模型的推理内容，需原样回传
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    def to_api_dict(self) -> dict:
        d: dict = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        elif self.tool_calls:
            # OpenAI API 要求 assistant 消息有 tool_calls 时 content 必须存在
            d["content"] = ""
        if self.reasoning_content:
            d["reasoning_content"] = self.reasoning_content
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        return d

    def to_storage_dict(self) -> dict:
        d: dict = {"role": self.role}
        if self.usage.total_tokens > 0:
            d["usage"] = {
                "prompt_tokens": self.usage.prompt_tokens,
                "completion_tokens": self.usage.completion_tokens,
                "total_tokens": self.usage.total_tokens,
            }
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        return d


class StreamDelta(BaseModel):
    content: str | None = None
    reasoning_content: str | None = None
    tool_call_index: int | None = None
    tool_call_id: str | None = None
    tool_call_name: str | None = None
    tool_call_arguments: str | None = None

    @property
    def is_tool_call(self) -> bool:
        return self.tool_call_index is not None
