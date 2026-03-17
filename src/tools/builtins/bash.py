"""BashTool — 在持久 shell 会话中执行命令"""

import asyncio
import os

from src.tools.base import BaseTool, ToolDefinition, ToolResult

_TIMEOUT = 120  # 默认超时（秒）
_MAX_TIMEOUT = 600  # 最大超时（秒）
_MAX_OUTPUT = 30_000  # 输出截断阈值（字符）


class BashTool(BaseTool):
    """在持久的 shell 会话中执行命令并返回输出"""

    def __init__(self):
        self._process: asyncio.subprocess.Process | None = None

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="bash",
            description="""\
在持久的 shell 会话中执行命令。

使用说明：
  - `command` 参数是必需的。
  - 可指定 `timeout`（秒），默认 120 秒，最大 600 秒。
  - 超过 30000 字符的输出会被截断。
  - 多个命令用 `;` 或 `&&` 分隔，不要用换行符。
  - 尽量使用绝对路径，避免 `cd`。""",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的 shell 命令"},
                    "timeout": {"type": "integer", "description": "超时（秒），默认 120"},
                },
                "required": ["command"],
            },
        )

    async def _start_shell(self) -> asyncio.subprocess.Process:
        self._process = await asyncio.create_subprocess_shell(
            "/bin/bash --norc --noprofile",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=os.getcwd(),
        )
        return self._process

    async def execute(self, command: str, timeout: int = _TIMEOUT) -> ToolResult:
        timeout = min(timeout, _MAX_TIMEOUT)

        # 确保持久 shell 存活
        proc = self._process
        if proc is None or proc.returncode is not None:
            proc = await self._start_shell()
        assert proc.stdin and proc.stdout

        # 用 sentinel 标记输出边界，携带退出码
        sentinel = f"__DONE_{os.urandom(8).hex()}__"
        proc.stdin.write(f"{command}\necho \"\\n{sentinel} $?\"\n".encode())
        await proc.stdin.drain()

        # 逐行读取直到 sentinel
        lines: list[str] = []
        exit_code = 0
        try:
            while True:
                raw = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
                if not raw:
                    break
                line = raw.decode(errors="replace").rstrip("\n")
                if sentinel in line:
                    parts = line.split(sentinel)[-1].strip()
                    exit_code = int(parts) if parts.isdigit() else 1
                    break
                lines.append(line)
        except asyncio.TimeoutError:
            proc.kill()
            self._process = None
            return ToolResult(content=f"命令超时（{timeout}s）", is_error=True)

        output = "\n".join(lines)

        # 输出过长则截断，保留首尾
        if len(output) > _MAX_OUTPUT:
            half = _MAX_OUTPUT // 2
            output = f"{output[:half]}\n\n... [截断 {len(output) - _MAX_OUTPUT} 字符] ...\n\n{output[-half:]}"

        if exit_code != 0:
            return ToolResult(content=output or f"退出码 {exit_code}", is_error=True)
        return ToolResult(content=output or "(无输出)")
