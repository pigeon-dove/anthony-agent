"""多行聊天输入框 — Enter 发送，Shift+Enter 换行"""

from textual import events
from textual.binding import Binding, BindingsMap
from textual.message import Message
from textual.widgets import TextArea


class ChatInput(TextArea):

    # 覆盖 TextArea 的 ctrl+d / ctrl+y，转发到 App 级 action；
    # 顺序与 App.BINDINGS 一致，确保 Footer 显示稳定。
    BINDINGS = [
        Binding("escape", "app.cancel", "中断输出", priority=True, show=True),
        Binding("ctrl+d", "app.quit", "退出", priority=True, show=True),
        Binding("ctrl+y", "app.copy_last_reply", "复制回复", priority=True, show=True),
    ]

    @classmethod
    def _merge_bindings(cls) -> BindingsMap:
        """确保 BINDINGS 声明顺序优先，修正 TextArea 父类合并导致的 Footer 乱序。"""
        merged = super()._merge_bindings()
        desired_keys = [b.key for b in cls.__dict__.get("BINDINGS", [])]
        ordered: dict[str, list[Binding]] = {}
        for dk in desired_keys:
            if dk in merged.key_to_bindings:
                ordered[dk] = merged.key_to_bindings[dk]
        for key, bindings in merged.key_to_bindings.items():
            if key not in ordered:
                ordered[key] = bindings
        return BindingsMap.from_keys(ordered)

    class Submitted(Message):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    async def _on_key(self, event: events.Key) -> None:
        if self.read_only:
            return

        if event.key == "shift+enter":
            event.stop()
            event.prevent_default()
            start, end = self.selection
            self.replace("\n", start, end)
            return

        if event.key == "enter":
            event.stop()
            event.prevent_default()
            value = self.text.strip()
            if value:
                self.clear()
                self.post_message(self.Submitted(value))
            return

        await super()._on_key(event)
