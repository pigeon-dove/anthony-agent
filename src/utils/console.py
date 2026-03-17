"""Console — 带颜色的终端打印工具"""


class _Color:
    """ANSI 颜色码"""
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"
    RESET = "\033[0m"


class Console:
    """简洁的彩色终端输出"""

    @staticmethod
    def _print(color: str, text: str, **kwargs):
        print(f"{color}{text}{_Color.RESET}", **kwargs)

    @staticmethod
    def red(text: str, **kwargs):
        Console._print(_Color.RED, text, **kwargs)

    @staticmethod
    def green(text: str, **kwargs):
        Console._print(_Color.GREEN, text, **kwargs)

    @staticmethod
    def yellow(text: str, **kwargs):
        Console._print(_Color.YELLOW, text, **kwargs)

    @staticmethod
    def blue(text: str, **kwargs):
        Console._print(_Color.BLUE, text, **kwargs)

    @staticmethod
    def cyan(text: str, **kwargs):
        Console._print(_Color.CYAN, text, **kwargs)

    @staticmethod
    def gray(text: str, **kwargs):
        Console._print(_Color.GRAY, text, **kwargs)


# 单例，直接用 console.red(...) 调用
console = Console()
