"""Text — 文本处理工具函数"""


def truncate(text: str, max_len: int = 100) -> str:
    """截断文本，超出时显示省略号和总字数。"""
    s = str(text)
    if len(s) <= max_len:
        return s
    return f"{s[:max_len]}…(共{len(s)}字)"
