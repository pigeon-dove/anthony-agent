"""Agent 事件流渲染器 — 将 Agent 事件流渲染到 Textual TUI"""

from typing import AsyncIterable

import json
from rich.markup import escape as rich_escape
from rich.text import Text as RichText
from textual.containers import VerticalScroll
from textual.widgets import Static, Markdown, Collapsible
from textual.widgets._markdown import MarkdownStream

from anthony_agent.agent.events import (
    AgentEvent, TextDelta, ToolCallStart, ToolArgsDelta,
    ToolCallResult, ResponseComplete, UsageReport,
    CompactStart, CompactComplete, ToolResultDelta,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from anthony_agent.ui.context_bar import ContextBar


class EventRenderer:
    """将 Agent 事件流渲染为 Textual Widget。

    职责单一：消费 AsyncIterable[AgentEvent]，不依赖 Agent 类型。
    """

    _TASK_WINDOW_LINES = 10  # task 工具进度窗口显示的行数

    _HANDLERS: dict[type, str] = {
        TextDelta: "_on_text_delta",
        ToolArgsDelta: "_on_tool_args_delta",
        ToolCallStart: "_on_tool_call_start",
        ToolCallResult: "_on_tool_call_result",
        ToolResultDelta: "_on_tool_result_delta",
        ResponseComplete: "_on_response_complete",
        UsageReport: "_on_usage_report",
        CompactStart: "_on_compact_start",
        CompactComplete: "_on_compact_complete",
    }

    def __init__(self, area: VerticalScroll, context_bar: "ContextBar | None" = None):
        self._area = area
        self._context_bar = context_bar
        self._last_reply = ""
        self._reset()

    def _reset(self) -> None:
        self._md_widget: Markdown | None = None
        self._md_stream: MarkdownStream | None = None
        self._streaming_text = False
        self._last_reply_text = ""
        # 工具卡片状态
        self._tool_card: Collapsible | None = None
        self._tool_card_result: Static | None = None
        # task 工具进度窗口状态
        self._task_progress_widget: Static | None = None
        self._task_progress_lines: list[str] = []
        # 流式参数输出状态（融入卡片内部）
        self._streaming_tool = False
        self._tool_stream_static: Static | None = None
        self._tool_stream_header = ""
        self._tool_stream_content = ""
        # 延迟 anchor：等到有实际内容输出时才锚定，避免内容少时被推到底部
        self._needs_anchor = False
        # 用户主动向上滚动标志：为 True 时暂停自动滚动
        self._user_scrolled_away = False

    # ── 公开接口 ──────────────────────────────────────────

    async def render_history(self, messages: list[dict]) -> None:
        """将历史消息恢复渲染到 UI。

        忠实展示 messages 中的内容：
        - 压缩过的对话会显示摘要提示
        - user/assistant 文本正常展示
        - 工具调用显示为折叠卡片

        所有 widget 先构建好再一次性挂载，避免逐条 mount 导致闪屏。
        """
        if not messages:
            return

        widgets: list = []  # 待挂载的 widget 列表
        pending_results: dict[str, Static] = {}  # tool_call_id → result widget
        last_assistant_content = ""

        # 检测是否压缩过（压缩后第一条消息带 _compact_marker 标记）
        is_compacted = (
            len(messages) >= 1
            and messages[0].get("_compact_marker", False)
        )
        if is_compacted:
            widgets.append(Static(
                "[dim]\\[已恢复] 早期对话已被压缩[/]",
                classes="history-hint",
            ))

        for msg in messages:
            role = msg.get("role", "")
            # 跳过工具注入的图片 user message：它的 content 是 list（多模态 parts），
            # 作为 tool_call 的附件，不需要单独渲染成用户发言。
            if msg.get("_tool_call_id"):
                continue
            content = msg.get("content", "") or ""
            # 防御：若 content 意外为 list（多模态），扁平化为纯文本占位
            if isinstance(content, list):
                content = "[多模态内容]"

            if role == "user":
                escaped = rich_escape(content)
                widgets.append(Static(f"> {escaped}", classes="user-msg"))

            elif role == "assistant":
                if content:
                    widgets.append(Markdown(content, classes="llm-markdown"))
                    last_assistant_content = content

                for tc in msg.get("tool_calls", []):
                    tc_id = tc.get("id", "")
                    func = tc.get("function", {})
                    name = func.get("name", "unknown")
                    args_str = func.get("arguments", "{}")
                    try:
                        args_dict = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except (json.JSONDecodeError, TypeError):
                        args_dict = {}
                    args_widget = Static(self._format_args(args_dict), classes="tool-card-args")
                    result_widget = Static("[dim]（历史记录）[/]", classes="tool-card-result")
                    card = Collapsible(
                        args_widget,
                        result_widget,
                        title=name,
                        collapsed=True,
                        collapsed_symbol="▶ [Tool]",
                        expanded_symbol="▼ [Tool]",
                        classes="tool-card",
                    )
                    widgets.append(card)
                    if tc_id:
                        pending_results[tc_id] = result_widget

            elif role == "tool":
                tool_call_id = msg.get("tool_call_id", "")
                result_text = content[:200] + "…" if len(content) > 200 else content
                result_content = RichText.assemble(
                    RichText("✔ 结果:\n", style="green"),
                    RichText(result_text),
                )
                widget = pending_results.pop(tool_call_id, None)
                if widget is not None:
                    widget.update(result_content)

        if last_assistant_content:
            self._last_reply = last_assistant_content

        widgets.append(Static(
            "[dim]─── 以上为历史消息 ───[/]",
            classes="history-separator",
        ))

        # 一次性挂载所有 widget，只触发一次布局刷新
        await self._area.mount_all(widgets)
        self._area.scroll_end(animate=False)

    async def render_user_message(self, text: str) -> None:
        escaped = rich_escape(text)
        await self._area.mount(Static(f"> {escaped}", classes="user-msg"))
        self._area.scroll_end(animate=False)

    async def render_error(self, error: Exception) -> None:
        await self._area.mount(
            Static(f"[red]\\[Error][/] {rich_escape(str(error))}", classes="status-info")
        )

    async def render_cancelled(self) -> None:
        await self._area.mount(
            Static("[yellow]\\[中断][/] 输出已被用户终止", classes="status-info")
        )

    def notify_user_scroll(self, is_at_bottom: bool) -> None:
        """由 App 层的滚动监听调用，更新用户滚动状态。

        用户往上滑 → 停止跟随；用户滑回底部 → 恢复跟随。
        """
        self._user_scrolled_away = not is_at_bottom

    async def render_event_stream(self, events: AsyncIterable[AgentEvent]) -> None:
        self._reset()
        self._needs_anchor = True
        try:
            async for event in events:
                await self._dispatch(event)
        finally:
            try:
                await self._stop_md_stream()
            except Exception:
                pass

    # ── 事件分发 ──────────────────────────────────────────

    async def _dispatch(self, event: AgentEvent) -> None:
        handler_name = self._HANDLERS.get(type(event))
        if handler_name:
            await getattr(self, handler_name)(event)

    # ── 事件处理 ──────────────────────────────────────────

    async def _on_text_delta(self, event: TextDelta) -> None:
        if not self._streaming_text:
            self._md_widget = Markdown("", classes="llm-markdown")
            await self._area.mount(self._md_widget)
            self._md_stream = Markdown.get_stream(self._md_widget)
            self._streaming_text = True
        self._last_reply_text += event.content
        if self._md_stream is not None:
            await self._md_stream.write(event.content)
        self._auto_scroll()

    async def _on_tool_args_delta(self, event: ToolArgsDelta) -> None:
        if self._streaming_text:
            self._streaming_text = False
            self._md_widget = None

        if not self._streaming_tool:
            # 提前创建卡片，流式内容作为卡片内子 widget
            self._tool_stream_header = f"[green]\\[Write][/] {event.field_name}:\n"
            self._tool_stream_content = ""
            self._tool_stream_static = Static(self._tool_stream_header, classes="tool-stream-inner")
            self._tool_card_result = Static("[dim]⏳ 等待执行…[/]", classes="tool-card-result")
            self._tool_card = Collapsible(
                self._tool_stream_static,
                self._tool_card_result,
                title=f"{event.tool_name}",
                collapsed=False,
                collapsed_symbol="▶ [Tool]",
                expanded_symbol="▼ [Tool]",
                classes="tool-card",
            )
            await self._area.mount(self._tool_card)
            self._streaming_tool = True

        self._tool_stream_content += event.content
        if self._tool_stream_static is not None:
            self._tool_stream_static.update(
                self._tool_stream_header + rich_escape(self._tool_stream_content)
            )
        self._auto_scroll()

    async def _on_tool_call_start(self, event: ToolCallStart) -> None:
        self._end_text_stream()

        if self._tool_card is not None:
            # 卡片已由流式参数创建，更新执行状态
            if self._tool_card_result is not None:
                self._tool_card_result.update("[dim]⏳ 执行中…[/]")
        else:
            # 非流式工具，正常创建卡片
            args_content = self._format_args(event.arguments)
            args_widget = Static(args_content, classes="tool-card-args")
            self._tool_card_result = Static("[dim]⏳ 执行中…[/]", classes="tool-card-result")
            self._tool_card = Collapsible(
                args_widget,
                self._tool_card_result,
                title=f"{event.tool_name}",
                collapsed=False,
                collapsed_symbol="▶ [Tool]",
                expanded_symbol="▼ [Tool]",
                classes="tool-card",
            )
            await self._area.mount(self._tool_card)

        self._streaming_tool = False
        self._tool_stream_static = None
        self._auto_scroll()

    async def _on_tool_result_delta(self, event: ToolResultDelta) -> None:
        """流式工具结果事件处理，内容显示在卡片内的滚动窗口中。"""
        self._task_progress_lines.append(event.content)

        # 只保留最近 N 行
        if len(self._task_progress_lines) > self._TASK_WINDOW_LINES:
            self._task_progress_lines = self._task_progress_lines[-self._TASK_WINDOW_LINES:]

        display = "\n".join(self._task_progress_lines)
        escaped = rich_escape(display)
        content = f"[dim]\\[Sub Agent][/]\n{escaped}"

        if self._task_progress_widget is not None:
            self._task_progress_widget.update(content)
        elif self._tool_card is not None:
            # 首次收到进度，在卡片内创建进度窗口 widget
            self._task_progress_widget = Static(content, classes="task-progress-window")
            await self._tool_card.mount(self._task_progress_widget, before=self._tool_card_result)
        self._auto_scroll()

    async def _on_tool_call_result(self, event: ToolCallResult) -> None:
        # 清理 task 进度窗口状态
        self._task_progress_widget = None
        self._task_progress_lines = []

        label = RichText("✔ 结果:\n", style="green")
        body = RichText(str(event.result))
        content = RichText.assemble(label, body)
        if self._tool_card_result is not None:
            self._tool_card_result.update(content)
        else:
            header = RichText.assemble(
                RichText("[Tool] ", style="green"),
                RichText(f"{event.tool_name} → "),
                body,
            )
            await self._area.mount(Static(header, classes="tool-info"))
        if self._tool_card is not None:
            self._tool_card.collapsed = True
        self._tool_card = None
        self._tool_card_result = None
        self._auto_scroll()

    async def _on_response_complete(self, _event: ResponseComplete) -> None:
        await self._stop_md_stream()
        self._streaming_text = False
        self._md_widget = None
        if self._last_reply_text:
            self._last_reply = self._last_reply_text
            self._last_reply_text = ""

    async def _on_usage_report(self, event: UsageReport) -> None:
        # 更新上下文进度条
        if self._context_bar is not None:
            self._context_bar.update_usage(event.prompt_tokens)
        await self._area.mount(Static(
            f"[dim]\\[Usage] prompt={event.prompt_tokens} "
            f"completion={event.completion_tokens} total={event.total_tokens}[/]",
            classes="status-info",
        ))

    async def _on_compact_start(self, event: CompactStart) -> None:
        if event.manual:
            text = f"[dim]\\[Compact] 手动压缩中... ({event.current_tokens} tokens)[/]"
        else:
            text = (
                f"[dim]\\[Compact] 上下文压缩中... "
                f"({event.current_tokens} tokens，阈值 {event.threshold_tokens})[/]"
            )
        await self._area.mount(Static(text, classes="status-info"))
        self._auto_scroll()

    async def _on_compact_complete(self, event: CompactComplete) -> None:
        saved = event.before_tokens - event.after_tokens
        await self._area.mount(Static(
            f"[dim]\\[Compact] 压缩完成: {event.before_tokens} → "
            f"{event.after_tokens} tokens (节省 {saved})[/]",
            classes="status-info",
        ))
        if self._context_bar is not None:
            self._context_bar.update_usage(event.after_tokens)
        self._auto_scroll()

    # ── 内部辅助 ──────────────────────────────────────────

    def _auto_scroll(self) -> None:
        if self._needs_anchor:
            self._needs_anchor = False
            self._user_scrolled_away = False
            self._area.scroll_end(animate=False)
            return
        if not self._user_scrolled_away:
            self._area.scroll_end(animate=False)

    def _end_text_stream(self) -> None:
        self._streaming_text = False
        self._md_widget = None

    async def _stop_md_stream(self) -> None:
        if self._md_stream is not None:
            await self._md_stream.stop()
            self._md_stream = None

    @staticmethod
    def _format_args(arguments: dict) -> RichText:
        if not arguments:
            return RichText("（无参数）", style="dim")
        parts: list[RichText | str] = [RichText("参数:\n", style="dim")]
        for i, (k, v) in enumerate(arguments.items()):
            if i > 0:
                parts.append("\n")
            parts.append(RichText(f"  {k}", style="cyan"))
            parts.append(" = ")
            parts.append(RichText(str(v)))
        return RichText.assemble(*parts)
