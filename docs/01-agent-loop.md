# 第一章：Agent Loop — ReAct 循环的核心

> 本章目标：理解 Agent 的核心运行机制 —— ReAct 循环，并用最少的代码实现一个能调用工具的 Agent。

## 什么是 Agent

一个普通的 LLM 调用是单轮的：你发消息，模型回复，结束。

Agent 不一样。它是一个**循环**：模型不仅能回复文字，还能决定"我需要调用一个工具来获取信息"，然后拿到工具结果后继续思考，直到它认为任务完成。

这就是 **ReAct**（Reasoning + Acting）模式：

```
用户输入
  │
  ▼
┌─────────────────────────┐
│  LLM 思考 + 决策        │◄──────────┐
│  输出文字 和/或 工具调用  │           │
└────────┬────────────────┘           │
         │                            │
    有工具调用？                       │
    ├── 否 → 结束，返回文字回复        │
    └── 是 → 执行工具 → 把结果给 LLM ──┘
```

每一轮循环中，模型可以：
- **只输出文字**（任务完成，循环结束）
- **调用一个或多个工具**（循环继续，把工具结果喂回去让模型继续思考）

## 最简 Agent 实现

先不考虑流式输出、上下文压缩、会话持久化这些，只实现最核心的循环。

### 消息协议

OpenAI 的 Chat API 用一个消息列表来维护对话状态，每条消息有一个 `role`：

```python
messages = [
    {"role": "system", "content": "你是一个编程助手"},
    {"role": "user", "content": "当前目录有哪些文件？"},
    {"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_1", "type": "function",
         "function": {"name": "bash", "arguments": '{"command": "ls"}'}}
    ]},
    {"role": "tool", "tool_call_id": "call_1", "content": "main.py\nREADME.md"},
    {"role": "assistant", "content": "当前目录有两个文件：main.py 和 README.md"},
]
```

关键点：
- `assistant` 消息的 `tool_calls` 字段告诉我们模型想调用哪些工具
- `tool` 消息通过 `tool_call_id` 关联到对应的工具调用，携带工具的执行结果
- 模型看到工具结果后，会在下一轮决定继续调用工具还是直接回复

### 核心循环

```python
import json
from openai import AsyncOpenAI

client = AsyncOpenAI()

# 工具定义（告诉模型有哪些工具可用）
tools = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "执行 shell 命令",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"}
                },
                "required": ["command"],
            },
        },
    }
]


async def execute_tool(name: str, arguments: dict) -> str:
    """执行工具，返回结果字符串。"""
    if name == "bash":
        import asyncio
        proc = await asyncio.create_subprocess_shell(
            arguments["command"],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode()
    return f"未知工具: {name}"


async def agent_loop(user_input: str):
    """最简 Agent Loop：不断调用 LLM → 执行工具 → 直到模型不再调用工具。"""
    messages = [
        {"role": "system", "content": "你是一个编程助手，可以执行 shell 命令。"},
        {"role": "user", "content": user_input},
    ]

    while True:
        # 1. 调用 LLM
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=tools,
        )
        msg = response.choices[0].message

        # 2. 把 assistant 消息加入历史
        messages.append(msg.model_dump())

        # 3. 如果有文字输出，打印
        if msg.content:
            print(f"Agent: {msg.content}")

        # 4. 如果没有工具调用，循环结束
        if not msg.tool_calls:
            break

        # 5. 执行所有工具调用
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            print(f"  [调用工具] {tc.function.name}({args})")
            result = await execute_tool(tc.function.name, args)
            print(f"  [工具结果] {result[:200]}")

            # 6. 把工具结果加入历史
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

        # 回到 while True 顶部，带着工具结果再次调用 LLM
```

这 50 行代码就是一个完整的 Agent。运行效果：

```
>>> await agent_loop("帮我看看当前目录有什么文件，然后统计 Python 文件的总行数")

  [调用工具] bash({"command": "ls"})
  [工具结果] main.py
  README.md
  utils.py

  [调用工具] bash({"command": "wc -l *.py"})
  [工具结果]   42 main.py
    18 utils.py
    60 total

Agent: 当前目录有 3 个文件，其中 2 个 Python 文件，总共 60 行代码。
```

模型自主决定了需要两次工具调用：先 `ls` 看有什么，再 `wc -l` 统计行数。这就是 ReAct 循环的威力。

## 从简到繁：项目中的实际实现

上面的最简版本能跑，但缺很多东西。项目中的 `Agent._loop` 在此基础上增加了：

### 1. 流式输出

最简版本用 `client.chat.completions.create()` 等全部生成完才返回。实际项目中用流式调用，模型边生成边输出：

```python
# 最简版本：等全部生成完
response = await client.chat.completions.create(...)
msg = response.choices[0].message

# 项目实际：流式逐 token 输出
stream = await client.stream_chat(messages, tools)
async for delta in stream:
    if delta.content:
        yield TextDelta(content=delta.content)  # 实时推给 UI
msg = stream.message  # 流结束后拿到完整消息
```

### 2. 事件驱动

最简版本直接 `print`。项目中 Agent 不直接操作 UI，而是通过 `yield` 产出事件对象，由外层的 Renderer 负责渲染：

```python
yield TextDelta(content="...")        # 文字增量
yield ToolCallStart(tool_name="bash") # 工具开始
yield ToolCallResult(result="...")    # 工具结果
yield ResponseComplete()              # 本轮结束
```

这样 Agent 和 UI 完全解耦——同一个 Agent 可以接 TUI、Web、API 等不同界面。

### 3. 工具并行执行

最简版本逐个执行工具。项目中普通工具并行执行（`asyncio.create_task`），流式工具串行：

```python
# 并行发起普通工具
pending = {}
for tc, args, is_streaming in parsed:
    if not is_streaming:
        pending[tc.id] = asyncio.create_task(registry.execute(tc.name, args))

# 按原始顺序消费结果
for tc, args, is_streaming in parsed:
    if is_streaming:
        async for event in tool.run_streaming(**args):
            yield event
    else:
        result = await pending[tc.id]
        yield ToolCallResult(result=result.content)
```

### 4. 用户中断

项目中支持 Esc 中断。中断时需要把已有的部分输出保存下来，让模型下一轮能看到：

```python
if self._cancelled:
    content = f"{partial}\n[用户中断，以上是中断前的部分输出]"
    self._persist({"role": "tool", "tool_call_id": tc.id, "content": content})
```

### 5. 上下文压缩

循环开始前检查 token 是否超限，超了就压缩旧对话（这部分在第四章详细讲）。

## 完整 Loop 的伪代码

把上面所有增强合在一起，项目中的 `_loop` 大致结构如下：

```python
async def _loop(self):
    while True:
        # 上下文压缩检查（第四章）
        await self._try_compact()
        # 旧工具输出裁剪（第四章）
        micro_compact(self._messages)

        # 流式调用 LLM，逐 token yield 事件
        msg = await self._stream_llm()

        # 保存 assistant 消息到历史
        self._persist(msg)

        # 没有工具调用 → 结束
        if not msg.has_tool_calls:
            break

        # 执行工具，yield 事件，保存 tool 消息
        await self._execute_tools(msg)
        # 回到 while True，带着工具结果再调 LLM
```

对比最简版本，结构完全一致——仍然是 `while True` + 调 LLM + 判断工具 + 执行工具 + 循环。所有的增强都是在这个骨架上叠加的。

## 小结

| 概念 | 说明 |
|---|---|
| **ReAct 循环** | `while True: LLM → 有工具？→ 执行 → 再 LLM`，直到模型不再调用工具 |
| **消息历史** | `list[dict]`，按 `role` 区分 user / assistant / tool，工具通过 `tool_call_id` 关联 |
| **事件驱动** | Agent 只 yield 事件，不操作 UI，实现解耦 |
| **并行执行** | 普通工具 `asyncio.create_task` 并行，流式工具串行 |

下一章我们来实现工具系统——如何定义工具基类、注册工具、以及 Agent 如何发现和调用它们。
