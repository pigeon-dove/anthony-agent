"""上下文使用进度条 — 显示当前 token 使用情况"""

from textual.widgets import Static

from config import app_config


def _format_tokens(n: int) -> str:
    """将 token 数格式化为易读形式：1234 → 1.2K, 123456 → 123K"""
    if n < 1000:
        return str(n)
    elif n < 10000:
        return f"{n / 1000:.1f}K"
    else:
        return f"{n // 1000}K"


class ContextBar(Static):
    """单行上下文使用进度条。

    显示格式：Context ████████░░░░ 65% (83K / 128K)
    颜色随使用率变化：绿色(< 60%) → 黄色(60-80%) → 红色(> 80%)
    """

    DEFAULT_CSS = """
    ContextBar {
        height: 1;
        padding: 0 1;
        background: $surface-darken-1;
    }
    """

    _BAR_WIDTH = 20  # 进度条字符宽度

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._max_tokens = app_config.llm.max_input_tokens
        self._threshold = app_config.compact.compact_threshold
        self._current_tokens = 0

    def on_mount(self) -> None:
        self._render_bar()

    def update_usage(self, prompt_tokens: int) -> None:
        """更新当前 token 使用量并重新渲染。"""
        self._current_tokens = prompt_tokens
        self._render_bar()

    def _render_bar(self) -> None:
        ratio = self._current_tokens / self._max_tokens if self._max_tokens > 0 else 0
        ratio = min(ratio, 1.0)
        pct = int(ratio * 100)

        # 进度条字符
        filled = int(ratio * self._BAR_WIDTH)
        bar_filled = "█" * filled
        bar_empty = "░" * (self._BAR_WIDTH - filled)

        # 颜色选择
        if ratio < 0.6:
            color = "green"
        elif ratio < self._threshold:
            color = "yellow"
        else:
            color = "red"

        # 阈值标记位置
        threshold_pos = int(self._threshold * self._BAR_WIDTH)

        # 构建带阈值标记的进度条
        current_str = _format_tokens(self._current_tokens)
        max_str = _format_tokens(self._max_tokens)

        # 阈值线用 ┃ 标记
        bar_chars = list(bar_filled + bar_empty)
        if 0 < threshold_pos < self._BAR_WIDTH:
            bar_chars[threshold_pos] = "┃"
        bar_str = "".join(bar_chars)

        self.update(
            f"[{color}]Context [{bar_str}] {pct}%[/] "
            f"[dim]({current_str} / {max_str})[/]"
        )
