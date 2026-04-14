"""WebSearchTool — 联网搜索，基于 Tavily Search API"""

import os

from tavily import TavilyClient

from src.tools.base import BaseTool, ToolDefinition, ToolResult

_MAX_RESULTS = 5

_TOOL_DESCRIPTION = """\
联网搜索（基于 Tavily API），返回最相关的网页结果，最多 5 条。中英文关键词均支持。

每条结果包含：标题、可直接访问的 URL、内容摘要。
可配合 web_fetch 使用返回的 URL 抓取网页详情。"""


class WebSearchTool(BaseTool):
    """联网搜索工具，基于 Tavily Search API"""

    def __init__(self) -> None:
        api_key = os.environ.get("TAVILY_API_KEY", "")
        self._client = TavilyClient(api_key=api_key) if api_key else None

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web_search",
            description=_TOOL_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词",
                    },
                },
                "required": ["query"],
            },
        )

    async def execute(self, query: str) -> ToolResult:
        if not self._client:
            return ToolResult(
                content="未配置 TAVILY_API_KEY，请在 .env 中设置。",
                is_error=True,
            )

        try:
            response = self._client.search(query=query, max_results=_MAX_RESULTS)
        except Exception as e:
            return ToolResult(content=f"搜索失败: {e}", is_error=True)

        results = response.get("results", [])
        if not results:
            return ToolResult(content="未找到相关结果。")

        return ToolResult(content=self._format_results(results))

    @staticmethod
    def _format_results(results: list[dict]) -> str:
        """将搜索结果格式化为带编号的文本列表。"""
        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "无标题")
            url = r.get("url", "")
            snippet = r.get("content", "")
            lines.append(f"[{i}] {title}\n    {url}\n    {snippet}")
        return "\n\n".join(lines)
