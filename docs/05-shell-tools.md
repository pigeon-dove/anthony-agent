# 第五章：命令执行 — bash / background_bash / 转后台

这是整个项目最复杂的两个工具。涉及子进程管理、流式输出、超时控制，以及一个有趣的运行时进程移交机制。

## 两种执行模式

编码助手需要执行 Shell 命令，但命令有两种性质：

| | 前台 `bash` | 后台 `background_bash` |
|---|---|---|
| 典型场景 | `git status`、`npm test`、`ls -la` | `npm run dev`、`tail -f log`、长编译 |
| 生命周期 | 执行完自动销毁 | 持久驻留，手动终止 |
| 输出方式 | 流式实时输出给 UI | 缓冲到内存，按需查看 |
| 阻塞对话 | 是（等命令结束才继续） | 否（立即返回 job_id） |

两者的执行模型本质不同，所以分成两个工具，而不是一个工具加 mode 参数。

## bash — 前台流式执行

### 流式输出

bash 是项目中第一个**流式工具**——它覆写了 `run_streaming()`，边执行边输出每一行：

```python
async def run_streaming(self, command: str, timeout: int = 30):
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,  # stderr 合并到 stdout
        cwd=os.getcwd(),
    )

    collected: list[str] = []

    async def read_lines():
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            collected.append(raw.decode(errors="replace").rstrip("\n"))

    reader = asyncio.create_task(read_lines())
```

关键设计：`read_lines` 是一个独立的 Task，持续从 stdout 读行写入 `collected` 列表。主循环定时检查 `collected`，把新增的行 yield 出去：

```python
while True:
    try:
        await asyncio.wait_for(asyncio.shield(reader), timeout=0.1)
        # reader 完成了（进程结束）
        for line in collected[emitted:]:
            yield ToolResultDelta(tool_name="bash", content=line)
        break
    except asyncio.TimeoutError:
        # 还没结束，输出已有的新行
        for line in collected[emitted:]:
            yield ToolResultDelta(tool_name="bash", content=line)
        emitted = len(collected)
```

为什么要分离 reader Task？因为 `readline()` 是阻塞的——如果直接在主循环里 `await readline()`，就没法同时检查超时和转后台请求。分离后，主循环每 100ms 醒一次，检查三件事：

1. 有没有新输出？有就 yield
2. 超时了吗？超了就 kill
3. 用户按 Ctrl+B 了吗？按了就转后台

### 超时机制

```python
loop = asyncio.get_running_loop()
deadline = loop.time() + timeout

while True:
    remaining = deadline - loop.time()
    if remaining <= 0:
        timed_out = True
        break
    await asyncio.wait_for(asyncio.shield(reader), timeout=min(0.1, remaining))
```

用 `loop.time()` + deadline 而不是累计计时，避免多次 `asyncio.sleep` 的误差累积。

超时后强制终止：

```python
if timed_out:
    reader.cancel()
    proc.kill()
    await proc.wait()
    yield ToolCallResult(
        result=f"{partial}\n[命令超时（{timeout}s），已强制终止，以上是超时前的输出]",
        is_error=True,
    )
```

注意输出里包含了超时前已经产出的内容——模型能看到命令跑了什么，而不是只看到一个"超时"错误。

### 输出截断

```python
@staticmethod
def _truncate(output: str) -> str:
    if len(output) <= 30_000:
        return output
    half = 30_000 // 2
    omitted = len(output) - 30_000
    return f"{output[:half]}\n\n... [截断 {omitted} 字符] ...\n\n{output[-half:]}"
```

保留首尾各半，中间截断。首部通常有初始化信息，尾部有最终结果/错误——中间的大量重复输出（如编译日志）可以丢弃。

## background_bash — 后台持久运行

### 多 Action 设计

background_bash 是一个"多 action"工具——通过 `action` 参数区分四种操作：

```python
async def execute(self, action: str, command: str = "", job_id: str = "", tail: int = 0):
    match action:
        case "start":   return await self._start(command)
        case "status":  return self._status(job_id, tail)
        case "stop":    return await self._stop(job_id)
        case "list":    return self._list()
```

为什么用一个工具而不是四个（`bg_start`、`bg_status`、`bg_stop`、`bg_list`）？因为这四个操作共享状态（`_jobs` 字典），语义上是同一个工具的不同操作，拆开反而让模型困惑。

### 任务状态管理

```python
@dataclass
class _BackgroundJob:
    job_id: str
    command: str
    process: asyncio.subprocess.Process
    started_at: float
    output_buffer: list[str] = field(default_factory=list)
    is_alive: bool = True
```

所有任务存储在类变量 `_jobs: ClassVar[dict]` 中——用 `ClassVar` 而不是实例变量，保证 `adopt()` 类方法也能访问。

### 缓冲区与 reader

每个任务有一个 reader 协程持续读 stdout 写入 `output_buffer`：

```python
@staticmethod
async def _reader_loop(job: _BackgroundJob) -> None:
    while True:
        line = await job.process.stdout.readline()
        if not line:
            break
        job.output_buffer.append(line.decode(errors="replace").rstrip("\n"))
        if len(job.output_buffer) > 3000:
            job.output_buffer[:] = job.output_buffer[-3000:]
    job.is_alive = False
```

缓冲区超过 3000 行时**原地裁剪**（`[:]` 赋值），保留最近的行。用 `[:]` 而不是重新赋值，是因为 `adopt()` 场景下 `output_buffer` 可能被外部共享引用，原地修改才能保持引用不断。

### start 流程

```python
async def _start(self, command):
    proc = await asyncio.create_subprocess_shell(command, ...)
    job = _BackgroundJob(job_id=..., command=command, process=proc, ...)
    self._jobs[job_id] = job
    self._tasks[job_id] = asyncio.create_task(self._reader_loop(job))

    await asyncio.sleep(1)  # 等 1 秒获取初始输出

    return ToolResult(content=f"{header}\n$ {command}\n{output}")
```

`sleep(1)` 是为了拿到初始输出——模型立即知道命令是否启动成功（比如端口占用报错），而不是只得到一个 job_id 后一无所知。

### stop 的优雅终止

```python
async def _stop(self, job_id):
    job.process.terminate()  # 先 SIGTERM
    try:
        await asyncio.wait_for(job.process.wait(), timeout=5)
    except asyncio.TimeoutError:
        job.process.kill()  # 5 秒后还没退出就 SIGKILL
```

先 `terminate`（给进程清理的机会），等 5 秒，不行再 `kill`。

### 上下文注入

```python
def context_injection(self) -> str | None:
    alive = [j for j in self._jobs.values() if j.is_alive]
    if not alive:
        return None
    lines = [f"- {j.job_id}: {j.command} (运行中, {elapsed})" for j in alive]
    return "[background_bash 活跃后台任务]\n" + "\n".join(lines)
```

这是第二章讲的 `context_injection` 机制的实际应用——每次 LLM 调用前，活跃的后台任务列表会被注入到 system prompt，让模型知道"当前有哪些命令在跑"。

## 转后台机制

最有趣的部分：用户按 Ctrl+B，把正在前台跑的 bash 命令无缝转入后台。

### 交互流程

```
1. 模型调用 bash("npm run build")
2. UI 显示流式输出 + "按 Ctrl+B 转入后台" 提示
3. 用户觉得太久了，按 Ctrl+B
4. bash 检测到 flag → 移交进程给 background_bash
5. bash 返回结果告诉模型"已转入后台，job_id: xxx"
6. 模型后续可用 background_bash 跟进
```

### 实现：flag 检查

UI 按键 → 调用 `BashTool.request_background()` → 设置 flag：

```python
def request_background(self):
    self._background_requested = True
```

bash 的主循环每 100ms 检查一次：

```python
while True:
    if self._background_requested:
        self._background_requested = False
        job_id = self._transfer_to_background(proc, command, collected, reader)
        yield ToolCallResult(result=f"...\njob_id: {job_id}\n...")
        return
    # ... 正常的超时检查和输出
```

### 实现：进程移交

```python
def _transfer_to_background(self, proc, command, collected, reader):
    return BackgroundBashTool.adopt(proc, command, collected, reader)
```

`adopt` 是关键——它把 bash 的进程、输出缓冲和 reader task 移交给 background_bash：

```python
@classmethod
def adopt(cls, proc, command, collected, reader):
    job_id = f"bg_{os.urandom(4).hex()}"
    job = _BackgroundJob(
        job_id=job_id,
        command=command,
        process=proc,
        started_at=time.monotonic(),
        output_buffer=collected,  # 共享引用！
    )
    cls._jobs[job_id] = job

    async def watch_reader():
        try:
            await reader  # 等 bash 的 reader 自然结束
        finally:
            job.is_alive = False

    cls._tasks[job_id] = asyncio.create_task(watch_reader())
    return job_id
```

两个关键设计：

1. **共享 `collected` 引用**——`output_buffer=collected` 不是 copy，是同一个 list。bash 的 `read_lines` 闭包还在往里写，background_bash 的 `output_buffer` 自动就有新数据。

2. **不取消 reader**——bash 的 reader task 正在 `await stdout.readline()`。如果 cancel 它，会破坏 asyncio StreamReader 的内部状态，后续再 `readline` 会直接返回 EOF。所以用 `watch_reader` 包装：等 reader 自然完成，然后标记 job 结束。

## 小结

| 概念 | 说明 |
|---|---|
| **流式工具** | `run_streaming()` 返回 AsyncGenerator，边执行边 yield 事件 |
| **reader 分离** | 独立 Task 读 stdout，主循环定时检查 + 超时 + 转后台 |
| **多 action 工具** | 一个工具四种操作，共享状态 |
| **进程移交** | 共享 list 引用 + 不 cancel reader + watch 包装 |
| **上下文注入** | 活跃任务列表自动注入 system prompt |

