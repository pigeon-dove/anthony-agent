# 第二章：工具系统 — 让 Agent 拥有能力

上一章的 Agent 只能调一个硬编码的 bash。这一章把工具抽象出来——定义一套协议，让工具可以自描述、动态注册、统一管理。

## 为什么需要工具系统

上一章的最简 Agent 里，工具是硬编码的：

```python
async def execute_tool(name: str, arguments: dict) -> str:
    if name == "bash":
        ...
    return f"未知工具: {name}"
```

这样做的问题：
- 加一个工具就得改 `execute_tool` 函数
- 工具定义（告诉模型有哪些工具）和工具实现（执行逻辑）散落在不同地方
- 没法动态注册 / 卸载工具

我们需要一套机制，让每个工具**自描述**（我叫什么、接受什么参数、干什么），然后统一注册到一个中心，Agent 只跟中心打交道。

## 设计三件套

整个工具系统只有三个核心概念：

```
BaseTool（基类）          定义工具的协议：名称、参数、执行逻辑
    ↓ 继承
BashTool / ReadFileTool   具体工具实现
    ↓ 注册到
ToolRegistry（注册中心）   统一管理：发现、查询、执行、导出定义
```

### 1. ToolDefinition — 工具的身份证

```python
class ToolDefinition(BaseModel):
    name: str           # 工具名，如 "bash"
    description: str    # 给模型看的说明
    parameters: dict    # JSON Schema 格式的参数定义
```

这直接对应 OpenAI API 的 `tools` 参数格式。模型看到这些信息后就知道有哪些工具可用、每个工具接受什么参数。

### 2. ToolResult — 工具的返回值

```python
class ToolResult(BaseModel):
    content: str          # 文字结果，会写入 tool message
    is_error: bool        # 是否执行出错
    images: list[str]     # 图片路径列表（如 read_file 读取图片时）
```

工具执行完后返回 `ToolResult`，Agent 把 `content` 写进对话历史的 `tool` 消息。

`images` 是一个巧妙的设计：有些工具（如 `read_file` 读图片）需要把图片注入对话。但 OpenAI API 要求图片放在 `user` 消息里，不能放在 `tool` 消息里。所以 `ToolResult.to_messages()` 会生成两条消息——一条 `tool` 消息（文字结果）和一条 `user` 消息（图片）：

```python
def to_messages(self, tool_call_id: str) -> list[dict]:
    msgs = [{"role": "tool", "tool_call_id": tool_call_id, "content": self.content}]
    if self.images:
        # 额外生成一条带图片的 user message
        parts = [{"type": "image_url", "image_url": {"url": data_url}}]
        msgs.append({"role": "user", "content": parts, "_tool_call_id": tool_call_id})
    return msgs
```

### 3. BaseTool — 工具的协议

```python
class BaseTool(ABC):

    @abstractmethod
    def definition(self) -> ToolDefinition:
        """返回工具定义（名称 + 参数 schema）。"""
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """执行工具，返回结果。"""
        ...

    def run_streaming(self, **kwargs) -> AsyncGenerator | None:
        """流式执行（可选）。返回 None 表示不支持。"""
        return None

    def context_injection(self) -> str | None:
        """注入到 system prompt 的动态上下文（可选）。"""
        return None

    async def cleanup(self) -> None:
        """退出时清理资源（可选）。"""
        pass
```

四个方法，只有前两个是必须实现的：

| 方法 | 必须 | 说明 |
|---|---|---|
| `definition()` | ✅ | 返回工具名、描述、参数 schema |
| `execute()` | ✅ | 执行工具逻辑 |
| `run_streaming()` | ❌ | 流式输出（`bash`、`task` 用到） |
| `context_injection()` | ❌ | 动态注入 system prompt（`skill` 用到，注入可用技能列表） |
| `cleanup()` | ❌ | 退出时清理（`background_bash` 用到，终止后台进程） |

### 实现一个最简工具

以 `think` 工具为例——它是最简单的工具，输入什么就返回什么：

```python
class ThinkTool(BaseTool):

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="think",
            description="停下来深度思考。无副作用，思考内容原样返回。",
            parameters={
                "type": "object",
                "properties": {
                    "thought": {
                        "type": "string",
                        "description": "你的思考内容",
                    },
                },
                "required": ["thought"],
            },
        )

    async def execute(self, thought: str) -> ToolResult:
        return ToolResult(content=thought)
```

就这么简单。`definition()` 告诉模型"我叫 think，接受一个 thought 参数"；`execute()` 原样返回。

注意 `execute` 的参数名 `thought` 和 schema 里的 `properties.thought` 一致——Agent 在调用时会把模型返回的 JSON 参数用 `**kwargs` 解包传入。

## ToolRegistry — 注册中心

注册中心是工具和 Agent 之间的桥梁：

```python
class ToolRegistry:

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}  # name → tool 实例

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.definition().name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def get_definitions(self) -> list[dict]:
        """导出所有工具定义，直接传给 OpenAI API 的 tools 参数。"""
        return [
            {"type": "function", "function": tool.definition().model_dump()}
            for tool in self._tools.values()
        ]

    async def execute(self, name: str, arguments: dict) -> ToolResult:
        """按名称执行工具，自动处理异常。"""
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(content=f"未知工具: {name}", is_error=True)
        try:
            return await tool.execute(**arguments)
        except Exception as e:
            return ToolResult(content=f"工具执行异常: {e}", is_error=True)
```

三个关键方法：

- `register()` — 注册工具实例
- `get_definitions()` — 导出所有工具定义给 LLM API
- `execute()` — 按名称执行工具，包了一层异常处理

### 注册流程

启动时一行代码注册所有内置工具：

```python
registry = ToolRegistry()
registry.register_many([tool() for tool in BUILTIN_TOOLS])
# BUILTIN_TOOLS = [ReadFileTool, WriteFileTool, BashTool, ...]
```

每个工具类无参构造，注册中心从 `definition().name` 拿到名字作为 key。

### 与 Agent 的对接

回顾第一章的 Agent Loop，工具系统在两个地方被使用：

```python
# 1. 调用 LLM 时，把工具定义传给 API
tools = registry.get_definitions()  # → [{"type": "function", "function": {...}}, ...]
response = await client.chat(messages=messages, tools=tools)

# 2. 执行工具时，按名称查找并执行
result = await registry.execute("bash", {"command": "ls"})
# 内部：registry.get("bash").execute(command="ls")
```

## 高级机制

### 流式工具

大多数工具是"调用 → 等完成 → 返回结果"。但有些工具（`bash`、`task`）需要**边执行边输出**——用户想实时看到命令输出或子 Agent 进度。

流式工具覆写 `run_streaming()`，返回一个 AsyncGenerator：

```python
class BashTool(BaseTool):

    async def run_streaming(self, command: str, timeout: int = 30):
        proc = await asyncio.create_subprocess_shell(command, ...)

        # 边读边 yield
        async for line in proc.stdout:
            yield ToolResultDelta(tool_name="bash", content=line)

        # 最后 yield 完整结果
        yield ToolCallResult(tool_name="bash", result=full_output)
```

Agent 判断一个工具是否支持流式：

```python
is_streaming = type(tool).run_streaming is not BaseTool.run_streaming
```

如果子类没覆写 `run_streaming`，它还是 `BaseTool` 的默认实现（返回 None），走普通 `execute` 路径。

### 上下文注入

有些工具需要在 system prompt 里动态注入信息。比如 `skill` 工具需要告诉模型"当前有哪些可用技能"：

```python
class SkillTool(BaseTool):

    def context_injection(self) -> str | None:
        skills = list_skills()
        if not skills:
            return None
        lines = ["# 可用技能"]
        for s in skills:
            lines.append(f"- **{s.name}**：{s.description}")
        return "\n".join(lines)
```

注册中心在构建 system prompt 时收集所有注入：

```python
def collect_context(self) -> str | None:
    parts = [ctx for tool in self._tools.values() if (ctx := tool.context_injection())]
    return "\n\n".join(parts) if parts else None
```

Agent 在 `_build_messages` 时把它拼到 system prompt 末尾。

## 设计决策

**为什么工具定义用 JSON Schema 而不是 Python 类型注解？**

因为 OpenAI API 要求 `tools` 参数是 JSON Schema 格式。直接用 JSON Schema 可以 1:1 传给 API，不需要中间转换层。虽然写起来比 Pydantic 模型啰嗦一点，但省掉了一个转换步骤，代码更直接。

**为什么 `execute` 用 `**kwargs` 而不是具体参数？**

基类签名是 `async def execute(self, **kwargs)`，但子类实现时写的是具体参数：

```python
# 基类
async def execute(self, **kwargs) -> ToolResult: ...

# 子类
async def execute(self, command: str, timeout: int = 30) -> ToolResult: ...
```

Agent 调用时用 `tool.execute(**args)` 解包，Python 会自动匹配参数名。这样每个工具的 `execute` 签名就是自文档化的。

**为什么注册中心包一层异常处理？**

```python
async def execute(self, name: str, arguments: dict) -> ToolResult:
    try:
        return await tool.execute(**arguments)
    except Exception as e:
        return ToolResult(content=f"工具执行异常: {e}", is_error=True)
```

工具代码可能有 bug，但不应该让 Agent 循环崩溃。catch 住异常，把错误信息作为 `ToolResult` 返回给模型，模型会看到错误并尝试换个方式解决。

## 小结

| 概念 | 职责 |
|---|---|
| `ToolDefinition` | 工具的名称 + 描述 + 参数 schema，传给 LLM API |
| `ToolResult` | 工具执行结果，写入对话历史的 tool message |
| `BaseTool` | 工具协议：`definition()` + `execute()`，可选流式和上下文注入 |
| `ToolRegistry` | 注册中心：注册、查询、执行、导出定义、收集上下文注入 |

