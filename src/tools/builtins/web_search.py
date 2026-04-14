"""WebSearchTool — 联网搜索，基于 Tavily Search API"""

import asyncio
import os

from tavily import TavilyClient

from src.tools.base import BaseTool, ToolDefinition, ToolResult

_MAX_RESULTS = 5

_TOOL_DESCRIPTION = """\
联网搜索（基于 Tavily API），返回最相关的网页结果，每条包含标题、URL 和内容摘要，最多 5 条。

适用场景：
- 查询实时信息：最新文档、新闻事件、技术方案对比等
- 查找特定资源：库的官方文档、API 参考、错误信息的解决方案等
- 中英文关键词均支持，建议用英文搜索技术内容以获得更好的结果

不适用场景：
- 已知确切 URL → 请直接使用 web_fetch 工具抓取
- 项目内的代码或文件搜索 → 请使用 grep / glob 工具

使用指南：
- 关键词尽量具体，避免过于宽泛的查询
- 搜索结果中的 URL 可直接传给 web_fetch 获取完整网页内容"""


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
            response = await asyncio.to_thread(
                self._client.search, query=query, max_results=_MAX_RESULTS,
            )
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
