"""Agent 事件流定义"""

from pydantic import BaseModel


class AgentEvent(BaseModel):
    pass


class TextDelta(AgentEvent):
    content: str


class ToolCallStart(AgentEvent):
    tool_name: str
    arguments: dict


class ToolCallArgumentsDelta(AgentEvent):
    tool_name: str
    field_name: str
    delta: str


class ToolCallResult(AgentEvent):
    tool_name: str
    result: str


class ResponseComplete(AgentEvent):
    pass


class UsageReport(AgentEvent):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class CompactStart(AgentEvent):
    current_tokens: int
    threshold_tokens: int


class CompactComplete(AgentEvent):
    before_tokens: int
    after_tokens: int
