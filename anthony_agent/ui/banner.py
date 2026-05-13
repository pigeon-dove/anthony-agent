"""启动 Banner — 在消息区域顶部显示金色渐变 ASCII 艺术字"""

from textual.widgets import Static

# ASCII art: 'anthony' (ansi_shadow 风格) — 金色渐变
# 从亮金 rgb(255,215,0) 渐变到深金 rgb(184,134,11)
_GRADIENT = [
    (255, 215, 0),    # 亮金
    (240, 195, 0),
    (224, 175, 0),
    (208, 160, 5),
    (196, 147, 8),
    (184, 134, 11),   # 深金
]

_RAW_LINES = [
    " █████╗ ███╗   ██╗████████╗██╗  ██╗ ██████╗ ███╗   ██╗██╗   ██╗",
    "██╔══██╗████╗  ██║╚══██╔══╝██║  ██║██╔═══██╗████╗  ██║╚██╗ ██╔╝",
    "███████║██╔██╗ ██║   ██║   ███████║██║   ██║██╔██╗ ██║ ╚████╔╝ ",
    "██╔══██║██║╚██╗██║   ██║   ██╔══██║██║   ██║██║╚██╗██║  ╚██╔╝  ",
    "██║  ██║██║ ╚████║   ██║   ██║  ██║╚██████╔╝██║ ╚████║   ██║   ",
    "╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝   ╚═╝",
]

ICON_LINES = [
    f"[rgb({r},{g},{b})]{line}[/]"
    for line, (r, g, b) in zip(_RAW_LINES, _GRADIENT)
]

ICON_ART = "\n".join(ICON_LINES)

BANNER_TEXT = (
    ICON_ART + "\n\n"
    "[bold cyan]  Anthony Agent[/]  [dim]— AI Coding Assistant[/]"
)


class BannerWidget(Static):
    """启动时显示的金色渐变 ASCII 艺术字 Banner。"""

    DEFAULT_CSS = """
    BannerWidget {
        width: 100%;
        content-align: center middle;
        text-align: center;
        margin: 1 0;
    }
    """

    def __init__(self) -> None:
        super().__init__(BANNER_TEXT)
