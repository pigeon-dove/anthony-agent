"""BashTool — 在持久 shell 会话中执行命令"""

import asyncio
import os
import time

from src.tools.base import BaseTool, ToolDefinition, ToolResult

_TIMEOUT = 120
_MAX_TIMEOUT = 600
_MAX_OUTPUT = 30_000

_TOOL_DESCRIPTION = """\
在持久的 bash shell 会话中执行命令，可跨多次调用保持状态（环境变量、工作目录等）。
使用指南：
- 可以执行任何 bash 命令，包括管道、重定向、循环等
- 命令用 `;` 或 `&&` 连接，不要用换行符
- 超时默认 120 秒，最大 600 秒
- 输出超过 30000 字符会被截断（保留首尾各半）
- 长时间运行的命令请设置合适的 timeout
- 优先使用绝对路径；仅在必须切换工作目录时使用 cd
- 不要使用此工具进行需要交互式输入的命令"""


class BashTool(BaseTool):
    """在持久的 shell 会话中执行命令并返回输出"""

    def __init__(self) -> None:
        super().__init__()
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="bash",
            description=_TOOL_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的 shell 命令"},
                    "timeout": {"type": "integer", "description": "超时（秒），默认 120"},
                },
                "required": ["command"],
            },
        )

    async def execute(self, command: str, timeout: int = _TIMEOUT) -> ToolResult:
        timeout = min(timeout, _MAX_TIMEOUT)

        async with self._lock:
            proc = await self._ensure_alive()
            assert proc.stdin and proc.stdout

            sentinel = f"__DONE_{os.urandom(8).hex()}__"
            proc.stdin.write(f'{command}\necho "\\n{sentinel} $?"\n'.encode())
            await proc.stdin.drain()

            lines, exit_code = await self._read_until_sentinel(proc.stdout, sentinel, timeout)

        # 超时
        if lines is None:
            proc.kill()
            self._process = None
            return ToolResult(content=f"命令超时（{timeout}s）", is_error=True)

        output = self._truncate("\n".join(lines))

        if exit_code != 0:
            return ToolResult(content=output or f"退出码 {exit_code}", is_error=True)
        return ToolResult(content=output or "(无输出)")

    async def _ensure_alive(self) -> asyncio.subprocess.Process:
        """保证持久 shell 存活，必要时重新创建"""
        if self._process is None or self._process.returncode is not None:
            self._process = await asyncio.create_subprocess_shell(
                "/bin/bash --norc --noprofile",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=os.getcwd(),
            )
        return self._process

    async def _read_until_sentinel(
        self,
        stdout: asyncio.StreamReader,
        sentinel: str,
        timeout: int,
    ) -> tuple[list[str] | None, int]:
        """逐行读取直到遇到 sentinel，返回 (lines, exit_code)。超时返回 (None, -1)。"""
        deadline = time.monotonic() + timeout
        lines: list[str] = []
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                raw = await asyncio.wait_for(stdout.readline(), timeout=remaining)
                if not raw:
                    # 进程意外退出
                    self._process = None
                    return lines, 1
                line = raw.decode(errors="replace").rstrip("\n")
                if sentinel in line:
                    code_str = line.split(sentinel)[-1].strip()
                    return lines, int(code_str) if code_str.isdigit() else 1
                lines.append(line)
        except asyncio.TimeoutError:
            return None, -1

    @staticmethod
    def _truncate(output: str) -> str:
        """输出过长则截断，保留首尾各半"""
        if len(output) <= _MAX_OUTPUT:
            return output
        half = _MAX_OUTPUT // 2
        omitted = len(output) - _MAX_OUTPUT
        return f"{output[:half]}\n\n... [截断 {omitted} 字符] ...\n\n{output[-half:]}"
