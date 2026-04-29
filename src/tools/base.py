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
    images: list[str] = []  # 工具读取到的图片绝对路径列表；会作为附加 user message 注入对话

    def to_messages(self, tool_call_id: str) -> list[dict]:
        """转成要追加到对话的消息序列：必然包含 1 条 tool message，
        若有图片则额外追加 1 条带 _tool_call_id 标记的 user message。
        """
        from src.utils.image import image_to_data_url
        from config import app_config

        msgs: list[dict] = [
            {"role": "tool", "tool_call_id": tool_call_id, "content": self.content}
        ]
        if not self.images:
            return msgs

        supports_vision = app_config.llm.supports_vision
        parts: list[dict] = [{"type": "text", "text": "[工具读取的图片]"}]
        for path in self.images:
            if not supports_vision:
                parts.append({"type": "text", "text": f"[图片: {path}（当前模型不支持视觉输入，已跳过）]"})
                continue
            try:
                data_url = image_to_data_url(path)
                parts.append({"type": "image_url", "image_url": {"url": data_url}})
            except Exception as e:
                parts.append({"type": "text", "text": f"[图片加载失败 {path}: {e}]"})

        msgs.append({
            "role": "user",
            "content": parts,
            "_tool_call_id": tool_call_id,  # 标记：这条 user 属于哪个 tool_call
        })
        return msgs


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
