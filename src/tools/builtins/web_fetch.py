"""WebFetchTool — 抓取网页内容并转为 Markdown"""

import asyncio

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
import html2text

from src.tools.base import BaseTool, ToolDefinition, ToolResult

_TIMEOUT = 15
_MAX_CONTENT = 20_000

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_TOOL_DESCRIPTION = """\
抓取指定 URL 的网页内容，支持两种模式：

**阅读模式（默认）：** 不传 link_keywords，返回网页正文纯文本。
原网页中可点击的超链接文本会用 [[双方括号]] 标记（如 [[百度百科]]），表示该文本有对应的 URL。

**链接提取模式：** 传入 link_keywords（关键词列表），只返回链接文本匹配关键词的链接及其完整 URL，不返回正文。

**典型用法：** 先用阅读模式获取网页内容，看到感兴趣的 [[链接文本]] 后，再次调用并传入 link_keywords 获取其真实 URL。"""


class WebFetchTool(BaseTool):
    """网页抓取工具：支持阅读模式和链接提取模式"""

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web_fetch",
            description=_TOOL_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "要抓取的网页 URL",
                    },
                    "link_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "链接提取关键词（如 [\"百度百科\", \"田园猫\"]）。"
                            "传入后进入链接提取模式：只返回链接文本包含任一关键词的链接及其完整 URL。"
                            "用于获取阅读模式中 [[标记文本]] 对应的真实 URL。"
                        ),
                    },
                },
                "required": ["url"],
            },
        )

    async def execute(self, url: str, link_keywords: list[str] | None = None) -> ToolResult:
        try:
            html = await self._fetch(url)
        except Exception as e:
            return ToolResult(content=f"抓取失败: {e}", is_error=True)

        if link_keywords:
            text = await asyncio.to_thread(self._extract_links, html, link_keywords)
        else:
            text = await asyncio.to_thread(self._html_to_markdown, html)

        if not text or not text.strip():
            return ToolResult(content="无法提取内容（页面可能需要 JS 渲染或内容为空）。")

        text = text.strip()
        if len(text) > _MAX_CONTENT:
            text = text[:_MAX_CONTENT] + f"\n\n... [截断，共 {len(text)} 字符]"

        # 阅读模式下，在末尾追加提示，引导使用链接提取模式
        if not link_keywords and "[[" in text:
            text += (
                "\n\n---\n"
                "💡 上文中 [[双方括号]] 包裹的文本表示原网页中可点击的链接。"
                "如需获取某个链接的真实 URL，请再次调用 web_fetch，"
                "传入相同的 url 和 link_keywords 参数（填入你感兴趣的关键词）。"
            )

        return ToolResult(content=text)

    # ── 内部方法 ──────────────────────────────────────────────

    @staticmethod
    async def _fetch(url: str) -> str:
        """用 curl_cffi 抓取网页 HTML，自动处理 SSL 证书问题。"""
        last_err: Exception | None = None
        for verify in (True, False):
            try:
                async with AsyncSession(
                    headers=_HEADERS,
                    timeout=_TIMEOUT,
                    impersonate="chrome131",
                    verify=verify,
                ) as session:
                    resp = await session.get(url, allow_redirects=True)
                    resp.raise_for_status()
                    return resp.text
            except Exception as e:
                last_err = e
        raise last_err  # type: ignore[misc]

    @staticmethod
    def _html_to_markdown(html: str) -> str:
        """将 HTML 转为纯文本，有链接的文本用 [[]] 标记。"""
        soup = BeautifulSoup(html, "html.parser")

        # 将 <a href="...">文本</a> 替换为 [[文本]]，无 href 或无效链接的直接保留文本
        for a in soup.find_all("a"):
            text = a.get_text(strip=True)
            href = str(a.get("href") or "").strip()
            if text and href and not href.startswith(("javascript:", "#")):
                a.replace_with(f"[[{text}]]")
            else:
                a.replace_with(text)

        converter = html2text.HTML2Text()
        converter.ignore_links = True
        converter.ignore_images = True
        converter.ignore_emphasis = False
        converter.body_width = 0
        converter.unicode_snob = True
        return converter.handle(str(soup))

    @staticmethod
    def _extract_links(html: str, keywords: list[str]) -> str:
        """从 HTML 中提取链接文本包含任一关键词的 <a> 链接，返回 Markdown 列表。"""
        soup = BeautifulSoup(html, "html.parser")
        kw_lower = [k.lower() for k in keywords]
        seen: set[str] = set()
        lines: list[str] = []

        for a in soup.find_all("a", href=True):
            href = str(a["href"]).strip()
            text = a.get_text(strip=True)
            if not text or not href or href.startswith(("javascript:", "#")):
                continue
            if not any(kw in text.lower() for kw in kw_lower):
                continue
            key = f"{text}|{href}"
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- [{text}]({href})")

        if not lines:
            return "未找到匹配的链接。"
        result = "\n".join(lines)
        result += (
            "\n\n---\n"
            "💡 以上是匹配到的链接，请直接用 web_fetch 访问这些 URL 获取详情，"
            "无需再调用 web_search。"
        )
        return result
