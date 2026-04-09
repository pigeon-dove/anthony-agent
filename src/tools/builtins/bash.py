"""BashTool — 无状态 shell，每次调用独立执行"""

import asyncio
import os

from src.tools.base import BaseTool, ToolDefinition, ToolResult

_TIMEOUT = 30
_MAX_TIMEOUT = 600
_MAX_OUTPUT = 30_000

_TOOL_DESCRIPTION = """\
在独立的 bash 子进程中执行命令，**每次调用都是全新的 shell 环境**，命令完成后进程立即销毁。

执行特性：
- 每次调用都从项目根目录启动一个全新的 bash 进程，命令完成后自动销毁
- 不保留跨调用状态：环境变量、工作目录、shell 变量等不会在调用间传递
- 如需在特定目录执行，请在命令中使用 `cd /path && ...`
- 超时默认 30 秒，最大 600 秒；超时后进程会被强制终止
- 输出超过 30000 字符会被截断（保留首尾各半）

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
    """无状态 shell：每次调用创建独立子进程，执行完即销毁"""

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
        timeout = min(timeout, _MAX_TIMEOUT)

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=os.getcwd(),
        )

        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult(
                content=(
                    f"命令超时（{timeout}s），已强制终止。"
                    f"该命令可能是长时间运行的进程，请改用 background_bash 工具重新执行。"
                ),
                is_error=True,
            )

        output = self._truncate(stdout.decode(errors="replace").rstrip())
        exit_code = proc.returncode or 0

        if exit_code != 0:
            return ToolResult(content=output or f"退出码 {exit_code}", is_error=True)
        return ToolResult(content=output or "（无输出）")

    @staticmethod
    def _truncate(output: str) -> str:
        """输出过长则截断，保留首尾各半"""
        if len(output) <= _MAX_OUTPUT:
            return output
        half = _MAX_OUTPUT // 2
        omitted = len(output) - _MAX_OUTPUT
        return f"{output[:half]}\n\n... [截断 {omitted} 字符] ...\n\n{output[-half:]}"
