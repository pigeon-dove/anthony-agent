"""工具基类 — 所有工具的统一协议"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator

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

    def run_streaming(self, **kwargs) -> AsyncGenerator | None:
        """返回事件流的 AsyncGenerator，支持流式输出的工具覆写此方法。

        返回 None 表示不支持流式，走普通 execute 路径。
        产出的事件类型由具体工具决定，最后必须产出 ToolResult。
        """
        return None

    def context_injection(self) -> str | None:
        """返回需要注入到 system prompt 的动态上下文，None 表示无需注入。"""
        return None

    async def cleanup(self) -> None:
        pass
