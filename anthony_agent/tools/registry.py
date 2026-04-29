"""工具注册中心"""

from anthony_agent.tools.base import BaseTool, ToolResult


class ToolRegistry:

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.definition().name] = tool

    def register_many(self, tools: list[BaseTool]) -> None:
        for tool in tools:
            self.register(tool)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    @property
    def names(self) -> list[str]:
        return list(self._tools.keys())

    def get_definitions(self) -> list[dict]:
        return [
            {"type": "function", "function": tool.definition().model_dump()}
            for tool in self._tools.values()
        ]

    async def execute(self, name: str, arguments: dict) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(content=f"未知工具: {name}", is_error=True)
        try:
            return await tool.execute(**arguments)
        except Exception as e:
            return ToolResult(content=f"工具执行异常: {e}", is_error=True)

    def collect_context(self) -> str | None:
        parts = [ctx for tool in self._tools.values() if (ctx := tool.context_injection())]
        return "\n\n".join(parts) if parts else None

    async def cleanup_all(self) -> None:
        for tool in self._tools.values():
            await tool.cleanup()
