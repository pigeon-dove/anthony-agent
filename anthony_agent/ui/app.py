"""Textual TUI 应用主类"""

import traceback
import subprocess
import sys
import asyncio

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Footer, Static
from textual import work

from anthony_agent.agent import Agent
from anthony_agent.tools import ToolRegistry
from anthony_agent.ui.styles import APP_CSS
from anthony_agent.ui.renderer import EventRenderer

_NEAR_BOTTOM_THRESHOLD = 3  # 判定“接近底部”的行距阈值


class _MessageArea(VerticalScroll):
    """带滚动位置监听的消息区域，用户向上滚时通知 renderer 暂停自动滚动。"""

    def watch_scroll_y(self, old: float, new: float) -> None:
        """scroll_y 变化时判断是否在底部，通知 renderer。"""
        super().watch_scroll_y(old, new)
        app = self.app
        if isinstance(app, AgentApp) and app._renderer is not None:
            is_at_bottom = (
                self.max_scroll_y == 0
                or new >= self.max_scroll_y - _NEAR_BOTTOM_THRESHOLD
            )
            app._renderer.notify_user_scroll(is_at_bottom)
from anthony_agent.ui.chat_input import ChatInput
from anthony_agent.ui.context_bar import ContextBar
from anthony_agent.ui.banner import BannerWidget


class AgentApp(App):

    CSS = APP_CSS
    BINDINGS = [
        Binding("escape", "cancel", "中断输出", priority=True),
        Binding("ctrl+d", "quit", "退出", priority=True),
        Binding("ctrl+y", "copy_last_reply", "复制回复", priority=True),
        Binding("ctrl+s", "toggle_mouse", "选择模式", priority=True),
        Binding("ctrl+k", "compact", "压缩上下文", priority=True),
        Binding("ctrl+b", "bash_to_background", "转入后台", priority=True),
        Binding("ctrl+q", "noop", show=False),  # 屏蔽终端默认 quit
    ]

    def __init__(self, agent: Agent, session_id: str, tool_registry: ToolRegistry):
        super().__init__()
        self._agent = agent
        self._session_id = session_id
        self._tool_registry = tool_registry
        self._renderer: EventRenderer | None = None
        self._mouse_enabled: bool = True

    def compose(self) -> ComposeResult:
        yield _MessageArea(id="message-area")
        with Vertical(id="bottom-bar"):
            yield ContextBar(id="context-bar")
            yield ChatInput(
                placeholder="输入消息，Enter 发送，Shift+Enter 换行",
                id="input-box",
            )
        yield Footer()

    async def on_mount(self) -> None:
        self.title = f"Anthony Agent — {self._session_id}"
        area = self.query_one("#message-area", _MessageArea)
        context_bar = self.query_one("#context-bar", ContextBar)
        self._renderer = EventRenderer(area, context_bar=context_bar)
        input_box = self.query_one("#input-box", ChatInput)
        input_box.focus()
        # 显示启动 Banner
        await area.mount(BannerWidget())
        # 有历史消息时：先显示加载提示，等首帧渲染完再异步加载
        if self._agent._messages:
            input_box.disabled = True
            # 只统计真实用户发言，跳过工具注入的图片 user message
            n = sum(
                1 for m in self._agent._messages
                if m.get("role") == "user" and not m.get("_tool_call_id")
            )
            await area.mount(Static(
                f"[dim]正在恢复历史会话（{n} 轮对话）…[/]",
                id="history-loading",
                classes="history-hint",
            ))
            self.call_after_refresh(self._load_history)

    @work(exclusive=False, exit_on_error=False)
    async def _load_history(self) -> None:
        """首帧渲染完后加载历史消息。"""
        assert self._renderer is not None
        # 移除加载提示
        loading = self.query_one("#history-loading", Static)
        await loading.remove()
        area = self.query_one("#message-area", _MessageArea)
        # 隐藏区域，避免用户看到从顶部滚到底部的过程
        area.display = False
        try:
            # 批量挂载历史
            await self._renderer.render_history(self._agent._messages)
            # 滚到底部后再显示
            area.scroll_end(animate=False)
        except Exception as e:
            # 历史渲染失败时兜底：展示错误，避免界面永远空白卡死
            traceback.print_exc()
            await area.mount(Static(
                f"[red]\\[历史渲染失败][/] {e}\n继续使用不受影响。",
                classes="status-info",
            ))
        finally:
            self.call_after_refresh(self._reveal_history)

    def _reveal_history(self) -> None:
        """历史加载完成后显示消息区域并启用输入。"""
        area = self.query_one("#message-area", _MessageArea)
        area.scroll_end(animate=False)
        area.display = True
        input_box = self.query_one("#input-box", ChatInput)
        input_box.disabled = False
        input_box.focus()
        # 恢复历史后更新上下文进度条
        self._update_context_bar_from_history()

    def _update_context_bar_from_history(self) -> None:
        """用 agent 加载历史时缓存的 prompt_tokens 更新 ContextBar。"""
        tokens = self._agent._last_prompt_tokens
        if tokens > 0:
            context_bar = self.query_one("#context-bar", ContextBar)
            context_bar.update_usage(tokens)

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        event.stop()
        user_input = event.value.strip()
        if not user_input:
            return
        if user_input.lower() in ("exit", "quit"):
            self.exit()
            return
        if user_input.lower() == "/compact":
            self.query_one("#input-box", ChatInput).disabled = True
            self._run_compact()
            return
        self.query_one("#input-box", ChatInput).disabled = True
        self._run_agent(user_input)

    @work(exclusive=True, exit_on_error=False)
    async def _run_compact(self) -> None:
        """用户手动触发上下文压缩。"""
        input_box = self.query_one("#input-box", ChatInput)
        assert self._renderer is not None
        try:
            await self._renderer.render_event_stream(self._agent.force_compact())
        except Exception as e:
            traceback.print_exc()
            try:
                await self._renderer.render_error(e)
            except Exception:
                pass
        finally:
            input_box.disabled = False
            input_box.focus()

    @work(exclusive=True, exit_on_error=False)
    async def _run_agent(self, user_input: str) -> None:
        input_box = self.query_one("#input-box", ChatInput)
        assert self._renderer is not None
        try:
            await self._renderer.render_user_message(user_input)
            await self._renderer.render_event_stream(self._agent.run(user_input))
            if self._agent.is_cancelled:
                await self._renderer.render_cancelled()
        except asyncio.CancelledError:
            # Ctrl+D 退出时 worker 被取消，静默处理
            return
        except Exception as e:
            traceback.print_exc()
            try:
                await self._renderer.render_error(e)
            except Exception:
                pass
        finally:
            input_box.disabled = False
            input_box.focus()

    def action_toggle_mouse(self) -> None:
        """切换鼠标模式：开启时 Textual 捕获鼠标（可点击/滚动），关闭时终端原生选择（可 Cmd+C 复制）。"""
        driver = self._driver
        if driver is None:
            return
        if self._mouse_enabled:
            driver._disable_mouse_support()  # type: ignore[attr-defined]
            self._mouse_enabled = False
            self.notify(
                "选择模式 [b]ON[/b] — 可用鼠标选择文本并 Cmd+C 复制，再按 Ctrl+S 恢复",
                timeout=3,
            )
        else:
            driver._enable_mouse_support()  # type: ignore[attr-defined]
            self._mouse_enabled = True
            self.notify(
                "选择模式 [b]OFF[/b] — 鼠标交互已恢复",
                timeout=2,
            )

    def action_compact(self) -> None:
        """手动触发上下文压缩。"""
        if self.query_one("#input-box", ChatInput).disabled:
            return  # 正在执行中，不要打断
        self.query_one("#input-box", ChatInput).disabled = True
        self._run_compact()

    def action_cancel(self) -> None:
        if self.query_one("#input-box", ChatInput).disabled:
            self._agent.cancel()

    def action_bash_to_background(self) -> None:
        """将正在执行的 bash 命令转入后台。"""
        from anthony_agent.tools.builtins.bash import BashTool
        bash_tool = self._tool_registry.get("bash")
        if isinstance(bash_tool, BashTool):
            bash_tool.request_background()

    def action_noop(self) -> None:
        pass

    async def action_quit(self) -> None:
        # 先通知 Agent 取消（会传播到子 Agent），再取消 worker
        self._agent.cancel()
        self.workers.cancel_all()
        try:
            await asyncio.wait_for(self._tool_registry.cleanup_all(), timeout=2)
        except (asyncio.TimeoutError, Exception):
            pass
        self.exit()

    def action_copy_last_reply(self) -> None:
        """复制最后一条 LLM 回复到剪贴板。"""
        if self._renderer and self._renderer._last_reply:
            self.copy_to_clipboard(self._renderer._last_reply)
        else:
            self.notify("暂无可复制的回复", severity="warning", timeout=1)

    @staticmethod
    def _get_clip_command() -> list[str] | None:
        """根据操作系统返回剪贴板写入命令，不可用时返回 None。"""
        platform = sys.platform
        if platform == "darwin":
            return ["pbcopy"]
        elif platform == "win32":
            return ["clip"]
        elif platform.startswith("linux"):
            # 优先 xclip，其次 xsel
            import shutil
            if shutil.which("xclip"):
                return ["xclip", "-selection", "clipboard"]
            if shutil.which("xsel"):
                return ["xsel", "--clipboard", "--input"]
        return None

    def copy_to_clipboard(self, text: str) -> None:
        """覆写 Textual 默认的 OSC 52 剪贴板，改用系统原生命令，兼容 VSCode 终端。"""
        self._clipboard = text
        clip_cmd = self._get_clip_command()
        if clip_cmd is None:
            super().copy_to_clipboard(text)
            return
        try:
            subprocess.run(
                clip_cmd,
                input=text.encode("utf-8"),
                check=True,
                timeout=3,
            )
            self.notify("已复制到剪贴板", severity="information", timeout=1.5)
        except Exception:
            # 回退到 Textual 默认的 OSC 52
            super().copy_to_clipboard(text)
