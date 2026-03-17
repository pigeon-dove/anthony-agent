"""工具基类 — 所有工具的统一协议"""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class ToolDefinition(BaseModel):
    """工具定义（提交给 LLM 的 JSON Schema 描述）"""
    name: str
    description: str
    parameters: dict  # JSON Schema 格式


class ToolResult(BaseModel):
    """工具执行结果"""
    content: str
    is_error: bool = False

    def to_message_dict(self, tool_call_id: str) -> dict:
        """转为 role=tool 的消息 dict，可直接 append 到 messages"""
        return {"role": "tool", "tool_call_id": tool_call_id, "content": self.content}


class BaseTool(ABC):
    """
    工具基类 — 所有工具（固定工具、动态 Skill、MCP 工具）都实现此协议。

    - definition() 是方法而非属性，每次调用时动态生成，支持描述随时变化的场景
    - execute() 是异步方法，适配项目的 async 架构
    """

    @abstractmethod
    def definition(self) -> ToolDefinition:
        """返回工具的定义（name + description + parameters JSON Schema）"""
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """执行工具，返回结果"""
        ...
