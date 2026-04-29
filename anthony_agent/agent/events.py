"""Agent 事件流定义"""

from pydantic import BaseModel


class AgentEvent(BaseModel):
    pass


class TextDelta(AgentEvent):
    content: str


class ToolCallStart(AgentEvent):
    tool_name: str
    arguments: dict


class ToolArgsDelta(AgentEvent):
    tool_name: str
    field_name: str
    content: str


class ToolCallResult(AgentEvent):
    tool_name: str
    result: str
    is_error: bool = False


class ResponseComplete(AgentEvent):
    pass


class UsageReport(AgentEvent):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class CompactStart(AgentEvent):
    current_tokens: int
    threshold_tokens: int
    manual: bool = False


class CompactComplete(AgentEvent):
    before_tokens: int
    after_tokens: int


class ToolResultDelta(AgentEvent):
    """流式工具的结果增量（如 task 工具的子 Agent 进度）"""
    tool_name: str
    content: str
