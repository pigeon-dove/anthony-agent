"""流式工具参数解析器 — 从 JSON 增量中提取指定字段的文本"""

STREAM_FIELDS: dict[str, str] = {
    "write_file": "content",
    "edit_file": "new_string",
    "think": "thought",
}

_ESCAPE_MAP = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


class ArgumentsStreamParser:
    """从工具调用 arguments 的 JSON 增量中提取指定字段的文本。

    启发式状态机：检测到 `"field_name":"` 后进入捕获模式，
    逐字符处理转义，直到遇到未转义的 `"` 结束。
    """

    def __init__(self, field_name: str):
        self._triggers = [
            f'"{field_name}":"',
            f'"{field_name}": "',
            f'"{field_name}" : "',
        ]
        self._buffer = ""
        self._capturing = False
        self._escaped = False
        self._done = False

    def feed(self, chunk: str) -> str:
        if self._done:
            return ""

        result: list[str] = []
        for ch in chunk:
            if not self._capturing:
                self._buffer += ch
                match = self._check_triggers()
                if match is True:
                    self._capturing = True
                    self._buffer = ""
                elif match is False:
                    self._buffer = ch
                    if self._check_triggers() is False:
                        self._buffer = ""
            else:
                if self._escaped:
                    self._escaped = False
                    result.append(_ESCAPE_MAP.get(ch, f"\\{ch}"))
                elif ch == '\\':
                    self._escaped = True
                elif ch == '"':
                    self._done = True
                    break
                else:
                    result.append(ch)

        return "".join(result)

    def _check_triggers(self) -> bool | None:
        """True=完整匹配, False=不匹配, None=前缀匹配中"""
        buf = self._buffer
        if any(buf == t for t in self._triggers):
            return True
        if any(t.startswith(buf) for t in self._triggers):
            return None
        return False
