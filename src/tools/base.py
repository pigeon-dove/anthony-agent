"""工具基类 — 所有工具的统一协议"""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: dict


class ToolResult(BaseModel):
    content: str
    is_error: bool = False

    def to_message_dict(self, tool_call_id: str) -> dict:
        return {"role": "tool", "tool_call_id": tool_call_id, "content": self.content}


class BaseTool(ABC):

    @abstractmethod
    def definition(self) -> ToolDefinition:
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        ...

    def context_injection(self) -> str | None:
        """返回需要注入到 system prompt 的动态上下文，None 表示无需注入。"""
        return None

    async def cleanup(self) -> None:
        pass
