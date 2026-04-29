"""文本处理工具"""


def truncate(text: str, max_len: int = 100) -> str:
    s = str(text)
    if len(s) <= max_len:
        return s
    return f"{s[:max_len]}…(共{len(s)}字)"
