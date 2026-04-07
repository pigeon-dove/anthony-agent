"""工具注册中心 — 聚合所有来源的工具，统一管理"""

from src.tools.base import BaseTool, ToolResult


class ToolRegistry:
    """
    工具注册中心。

    聚合固定工具、动态 Skill 工具、MCP 工具，提供：
    - register / unregister：注册和注销工具
    - get_definitions()：生成提交给 LLM 的 tools 参数
    - execute()：按名称分发执行工具
    """

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """注册一个工具"""
        name = tool.definition().name
        self._tools[name] = tool

    def register_many(self, tools: list[BaseTool]) -> None:
        """批量注册工具"""
        for tool in tools:
            self.register(tool)

    def unregister(self, name: str) -> None:
        """注销一个工具"""
        self._tools.pop(name, None)

    def get(self, name: str) -> BaseTool | None:
        """按名称获取工具实例"""
        return self._tools.get(name)

    @property
    def names(self) -> list[str]:
        """所有已注册的工具名"""
        return list(self._tools.keys())

    def get_definitions(self) -> list[dict]:
        """
        生成 OpenAI function calling 格式的 tools 参数。

        返回格式:
            [{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}]
        """
        return [
            {
                "type": "function",
                "function": tool.definition().model_dump(),
            }
            for tool in self._tools.values()
        ]

    async def execute(self, name: str, arguments: dict) -> ToolResult:
        """按名称执行工具"""
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(content=f"未知工具: {name}", is_error=True)
        try:
            return await tool.execute(**arguments)
        except Exception as e:
            return ToolResult(content=f"工具执行异常: {e}", is_error=True)

    def collect_context(self) -> str | None:
        """
        收集所有工具的动态上下文信息，拼接为一个字符串。

        遍历所有注册工具，调用 context_injection()，将非空结果合并。
        返回 None 表示所有工具均无上下文需要注入。
        """
        parts = []
        for tool in self._tools.values():
            ctx = tool.context_injection()
            if ctx:
                parts.append(ctx)
        return "\n\n".join(parts) if parts else None

    async def cleanup_all(self) -> None:
        """清理所有工具的资源"""
        for tool in self._tools.values():
            await tool.cleanup()
