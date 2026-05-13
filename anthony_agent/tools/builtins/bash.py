"""BashTool — 无状态 shell，每次调用独立执行，支持运行中转入后台"""

import asyncio
import os
from typing import AsyncGenerator

from anthony_agent.agent.events import AgentEvent, ToolCallResult, ToolResultDelta, BashBackgroundable
from anthony_agent.tools.base import BaseTool, ToolDefinition, ToolResult

_TIMEOUT = 30
_MAX_TIMEOUT = 600
_MAX_OUTPUT = 30_000
_POLL_INTERVAL = 0.1  # 轮询 stdout 的间隔（秒）

_TOOL_DESCRIPTION = """\
在独立的 bash 子进程中执行命令，**每次调用都是全新的 shell 环境**，命令完成后进程立即销毁。

执行特性：
- 每次调用都从项目根目录启动一个全新的 bash 进程，命令完成后自动销毁
- 不保留跨调用状态：环境变量、工作目录、shell 变量等不会在调用间传递
- 如需在特定目录执行，请在命令中使用 `cd /path && ...`
- 超时默认 30 秒，最大 600 秒；超时后进程会被强制终止

适用场景：
- 快速命令：文件操作、git 操作、包管理、编译构建等
- 一次性任务：脚本执行、数据处理、环境配置等
- 需要即时反馈的操作：测试运行、代码检查、查询命令等

⚠️ 不适用场景（必须改用 background_bash 工具）：
- 长时间运行的进程：dev server、watch 模式、持续编译等
- 持续监控类任务：日志 tail、文件监听等
- 任何不会自动结束的命令或预期运行超过 30 秒的命令
- 如果你不确定命令是否会快速结束，请优先使用 background_bash

使用指南：
- 多条命令用 `;` 或 `&&` 连接，不要用换行符
- 需要保留环境变量时，在同一次调用中完成所有依赖该变量的操作
- 不要执行需要交互式输入的命令"""


class BashTool(BaseTool):
    """无状态 shell：每次调用创建独立子进程，执行完即销毁，支持转入后台"""

    def __init__(self):
        self._background_requested = False

    def request_background(self) -> None:
        """由 UI 层调用，请求将当前 bash 转入后台。"""
        self._background_requested = True

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="bash",
            description=_TOOL_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的 shell 命令"},
                    "timeout": {"type": "integer", "description": "超时（秒），默认 30"},
                },
                "required": ["command"],
            },
        )

    async def execute(self, command: str, timeout: int = _TIMEOUT) -> ToolResult:
        """兜底路径：聚合 run_streaming 的最终结果。"""
        final: ToolCallResult | None = None
        async for event in self.run_streaming(command=command, timeout=timeout):
            if isinstance(event, ToolCallResult):
                final = event
        if final is None:
            return ToolResult(content="（无输出）")
        return ToolResult(content=final.result, is_error=final.is_error)

    async def run_streaming(
        self, command: str, timeout: int = _TIMEOUT
    ) -> AsyncGenerator[AgentEvent, None]:
        """按行流式输出 stdout/stderr，最后产出完整结果。"""
        timeout = min(timeout, _MAX_TIMEOUT)
        self._background_requested = False

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=os.getcwd(),
        )

        collected: list[str] = []
        assert proc.stdout is not None
        stdout = proc.stdout

        async def read_lines() -> None:
            while True:
                raw = await stdout.readline()
                if not raw:
                    break
                collected.append(raw.decode(errors="replace").rstrip("\n"))

        reader = asyncio.create_task(read_lines())
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        emitted = 0
        timed_out = False

        # 通知 UI：此 bash 可被转入后台
        yield BashBackgroundable()

        try:
            while True:
                # 检查用户是否请求转入后台
                if self._background_requested:
                    self._background_requested = False
                    job_id = self._transfer_to_background(proc, command, collected, reader)
                    for line in collected[emitted:]:
                        yield ToolResultDelta(tool_name="bash", content=line)
                    partial = self._truncate("\n".join(collected))
                    output_section = f"{partial}\n" if partial else ""
                    yield ToolCallResult(
                        tool_name="bash",
                        result=(
                            f"{output_section}"
                            f"[用户已将命令转入后台执行，以上是转入前的输出]\n"
                            f"job_id: {job_id}\n"
                            f"后续可用 background_bash 的 status/stop action 跟进此任务。"
                        ),
                    )
                    return

                remaining = deadline - loop.time()
                if remaining <= 0:
                    timed_out = True
                    break

                try:
                    await asyncio.wait_for(
                        asyncio.shield(reader),
                        timeout=min(_POLL_INTERVAL, remaining),
                    )
                    for line in collected[emitted:]:
                        yield ToolResultDelta(tool_name="bash", content=line)
                    emitted = len(collected)
                    break
                except asyncio.TimeoutError:
                    for line in collected[emitted:]:
                        yield ToolResultDelta(tool_name="bash", content=line)
                    emitted = len(collected)
        except asyncio.CancelledError:
            reader.cancel()
            proc.kill()
            await proc.wait()
            raise

        if timed_out:
            reader.cancel()
            proc.kill()
            await proc.wait()
            partial = self._truncate("\n".join(collected).rstrip())
            output_section = f"{partial}\n" if partial else ""
            yield ToolCallResult(
                tool_name="bash",
                result=(
                    f"{output_section}"
                    f"[命令超时（{timeout}s），已强制终止，以上是超时前的输出]\n"
                    f"该命令可能是长时间运行的进程，请改用 background_bash 工具重新执行。"
                ),
                is_error=True,
            )
            return

        await proc.wait()
        exit_code = proc.returncode or 0
        full_output = self._truncate("\n".join(collected).rstrip())

        if exit_code != 0:
            yield ToolCallResult(
                tool_name="bash",
                result=full_output or f"退出码 {exit_code}",
                is_error=True,
            )
        else:
            yield ToolCallResult(
                tool_name="bash",
                result=full_output or "（无输出）",
            )

    def _transfer_to_background(
        self,
        proc: asyncio.subprocess.Process,
        command: str,
        collected: list[str],
        reader: asyncio.Task,
    ) -> str:
        """将进程移交给 BackgroundBashTool，返回 job_id。"""
        from anthony_agent.tools.builtins.bash_background import BackgroundBashTool
        return BackgroundBashTool.adopt(proc, command, collected, reader)

    @staticmethod
    def _truncate(output: str) -> str:
        """输出过长则截断，保留首尾各半"""
        if len(output) <= _MAX_OUTPUT:
            return output
        half = _MAX_OUTPUT // 2
        omitted = len(output) - _MAX_OUTPUT
        return f"{output[:half]}\n\n... [截断 {omitted} 字符] ...\n\n{output[-half:]}"
