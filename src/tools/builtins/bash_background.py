"""BackgroundBashTool — 后台运行长时间命令，不阻塞对话"""

import asyncio
import os
import time
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from src.tools.base import BaseTool, ToolDefinition, ToolResult

# ── 常量 ──

_MAX_JOBS = 5  # 最大并发后台任务数
_MAX_BUFFER = 3000  # 缓冲区最大行数，超过时截断
_DEFAULT_TAIL = 50  # status 默认返回行数
_MAX_TAIL = 1000  # status 最大返回行数
_INIT_WAIT = 1  # start 后等待初始输出的秒数
_STOP_TIMEOUT = 5  # terminate 后等待进程退出的秒数

_TOOL_DESCRIPTION = """\
在后台运行长时间命令，**异步执行，不阻塞对话**。启动后立即返回 job_id，随后可随时查看输出或终止任务。

执行模式：
- 命令在后台异步运行，启动后等待 1 秒获取初始输出即返回
- 通过 job_id 随时查看输出、终止任务，不影响其他操作
- 最多同时运行 5 个后台任务

适用场景：
- 长时间运行的服务：dev server、数据库、API 服务等
- 持续性任务：watch 模式、文件监听、日志 tail 等
- 耗时操作：大项目编译、批量数据处理等

不适用场景（请改用 bash 工具）：
- 快速命令：文件操作、git 命令等预期几秒内完成的任务
- 需要即时获取完整输出的一次性操作

操作说明：
- action="start", command="..."：启动后台命令，返回 job_id
- action="status", job_id="..."：查看最近输出（默认 50 行，可通过 tail 调整，最大 1000）
- action="stop", job_id="..."：终止后台任务
- action="list"：列出所有后台任务"""


class _BackgroundJob(BaseModel):
    """后台任务状态"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    job_id: str
    command: str
    process: asyncio.subprocess.Process
    output_buffer: list[str] = []
    started_at: float
    is_alive: bool = True


class BackgroundBashTool(BaseTool):
    """后台运行长时间命令，支持启动/查看输出/停止/列出"""

    _jobs: ClassVar[dict[str, _BackgroundJob]] = {}
    _tasks: ClassVar[dict[str, asyncio.Task]] = {}  # job_id -> reader task

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="background_bash",
            description=_TOOL_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["start", "status", "stop", "list"],
                        "description": "操作类型",
                    },
                    "command": {
                        "type": "string",
                        "description": "要执行的命令（action=start 时必填）",
                    },
                    "job_id": {
                        "type": "string",
                        "description": "任务 ID（action=status/stop 时必填）",
                    },
                    "tail": {
                        "type": "integer",
                        "description": "status 时返回最近多少行输出（默认 50，最大 1000）",
                    },
                },
                "required": ["action"],
            },
        )

    async def execute(self, action: str, command: str = "", job_id: str = "", tail: int = 0) -> ToolResult:
        match action:
            case "start":
                return await self._start(command)
            case "status":
                return self._status(job_id, tail)
            case "stop":
                return await self._stop(job_id)
            case "list":
                return self._list()
            case _:
                return ToolResult(content=f"未知 action: {action}", is_error=True)

    # ── 内部工具方法 ──

    def _get_job(self, job_id: str) -> _BackgroundJob | None:
        """查找任务，不存在返回 None"""
        return self._jobs.get(job_id)

    def _tail_output(self, job: _BackgroundJob, n: int = _DEFAULT_TAIL) -> str:
        """返回缓冲区最近 n 行，附带截断提示"""
        total = len(job.output_buffer)
        lines = job.output_buffer[-n:]
        output = "\n".join(lines) or "(暂无输出)"
        truncated = f"(显示最近 {len(lines)}/{total} 行)\n" if total > n else ""
        return f"{truncated}{output}"

    def _format_header(self, job: _BackgroundJob) -> str:
        """格式化任务状态头：[状态 | 时长] job_id"""
        status = "运行中" if job.is_alive else "已结束"
        elapsed = self._fmt_duration(job.started_at)
        return f"[{status} | {elapsed}] {job.job_id}"

    # ── start ──

    async def _start(self, command: str) -> ToolResult:
        if not command:
            return ToolResult(content="action=start 时 command 不能为空", is_error=True)

        alive_count = sum(1 for j in self._jobs.values() if j.is_alive)
        if alive_count >= _MAX_JOBS:
            return ToolResult(content=f"后台任务已达上限（{_MAX_JOBS}），请先停止部分任务", is_error=True)

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=os.getcwd(),
        )

        job_id = f"bg_{os.urandom(4).hex()}"
        job = _BackgroundJob(job_id=job_id, command=command, process=proc, started_at=time.monotonic())
        self._jobs[job_id] = job
        self._tasks[job_id] = asyncio.create_task(self._reader_loop(job))

        await asyncio.sleep(_INIT_WAIT)

        header = self._format_header(job)
        output = self._tail_output(job)
        return ToolResult(content=f"{header}\n$ {command}\n{output}")

    # ── status ──

    def _status(self, job_id: str, tail: int = 0) -> ToolResult:
        job = self._get_job(job_id)
        if not job:
            return ToolResult(content=f"任务不存在: {job_id}", is_error=True)

        n = min(tail, _MAX_TAIL) if tail > 0 else _DEFAULT_TAIL
        header = self._format_header(job)
        output = self._tail_output(job, n)
        return ToolResult(content=f"{header}\n{output}")

    # ── stop ──

    async def _stop(self, job_id: str) -> ToolResult:
        job = self._get_job(job_id)
        if not job:
            return ToolResult(content=f"任务不存在: {job_id}", is_error=True)

        if job.is_alive:
            job.process.terminate()
            try:
                await asyncio.wait_for(job.process.wait(), timeout=_STOP_TIMEOUT)
            except asyncio.TimeoutError:
                job.process.kill()
            job.is_alive = False

        # 清理 reader task
        task = self._tasks.pop(job_id, None)
        if task and not task.done():
            task.cancel()

        output = self._tail_output(job)
        del self._jobs[job_id]
        return ToolResult(content=f"[已终止] {job_id}\n{output}")

    # ── list ──

    def _list(self) -> ToolResult:
        if not self._jobs:
            return ToolResult(content="当前没有后台任务")

        lines = []
        for job in self._jobs.values():
            status = "运行中" if job.is_alive else "已结束"
            elapsed = self._fmt_duration(job.started_at)
            cmd = job.command[:60] + ("..." if len(job.command) > 60 else "")
            lines.append(f"  {job.job_id} | {status} | {elapsed} | {cmd}")

        return ToolResult(content="[后台任务列表]\n" + "\n".join(lines))

    # ── 后台读取协程 ──

    async def _reader_loop(self, job: _BackgroundJob) -> None:
        """持续读取进程输出到缓冲区"""
        assert job.process.stdout
        try:
            while True:
                line = await job.process.stdout.readline()
                if not line:
                    break
                job.output_buffer.append(line.decode(errors="replace").rstrip("\n"))
                if len(job.output_buffer) > _MAX_BUFFER:
                    job.output_buffer = job.output_buffer[-_MAX_BUFFER:]
        except asyncio.CancelledError:
            pass
        finally:
            job.is_alive = False

    # ── 生命周期 ──

    async def cleanup(self) -> None:
        """终止所有后台任务并清理资源"""
        for job in self._jobs.values():
            if job.is_alive:
                job.process.kill()
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
        self._jobs.clear()
        self._tasks.clear()

    def context_injection(self) -> str | None:
        """返回活跃任务摘要，供 system prompt 注入"""
        alive = [j for j in self._jobs.values() if j.is_alive]
        if not alive:
            return None
        lines = [f"- {j.job_id}: {j.command} (运行中, {self._fmt_duration(j.started_at)})" for j in alive]
        return "[background_bash 活跃后台任务]\n" + "\n".join(lines)

    @staticmethod
    def _fmt_duration(started_at: float) -> str:
        """格式化运行时长"""
        secs = int(time.monotonic() - started_at)
        if secs < 60:
            return f"{secs}s"
        mins, secs = divmod(secs, 60)
        return f"{mins}m{secs:02d}s"
