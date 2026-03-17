"""Agent 事件流模型"""

from pydantic import BaseModel


class AgentEvent(BaseModel):
    """Agent 事件基类"""
    pass


class TextDelta(AgentEvent):
    """LLM 流式输出的文本片段"""
    content: str


class ToolCallStart(AgentEvent):
    """LLM 决定调用工具（工具执行前触发）"""
    tool_name: str
    arguments: dict


class ToolCallResult(AgentEvent):
    """工具调用完成的结果"""
    tool_name: str
    result: str


class ResponseComplete(AgentEvent):
    """LLM 文本回复结束"""
    pass


class UsageReport(AgentEvent):
    """单次 LLM 调用的 token 用量"""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
