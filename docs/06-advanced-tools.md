# 第六章：高级工具 — think / task / skill / web_search / web_fetch

> 本章目标：实现五个各有特色的高级工具，覆盖思考、委派、技能扩展和联网能力。

## think — 给模型一张草稿纸

### 为什么需要 think 工具

模型的 `content` 输出会直接展示给用户。但有些时候模型需要"自言自语"——整理线索、权衡方案、推理逻辑——这些中间过程不适合直接展示。

think 工具就是模型的草稿纸：输入思考内容，原样返回，写入对话历史。模型下一轮能看到自己想过什么，但用户看到的只是一次工具调用。

### 实现

整个项目最简单的工具：

```python
class ThinkTool(BaseTool):

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="think",
            description="停下来深度思考。无副作用，思考内容原样返回。",
            parameters={
                "type": "object",
                "properties": {
                    "thought": {"type": "string", "description": "你的思考内容"},
                },
                "required": ["thought"],
            },
        )

    async def execute(self, thought: str) -> ToolResult:
        return ToolResult(content=thought)
```

### 上下文压缩时的特殊处理

think 的内容对后续对话没有价值（结论已经体现在模型的 content 输出里），所以在上下文压缩时，3 轮之前的 think 调用会被**彻底删除**——不是替换为占位符，而是连 tool_call 和 tool message 一起丢弃。这在第七章上下文管理中会详细讲。

## task — 子 Agent 委派

### 解决什么问题

主 Agent 的对话上下文是有限的。如果一个任务需要大量搜索和读取（比如"梳理这个模块的完整调用链"），中间产生的工具输出会快速填满上下文。

task 工具把子任务交给一个**独立的 Sub Agent**——它有自己的上下文，完成后只把最终结论返回给主 Agent，中间的工具调用过程不会污染主对话。

```
主 Agent 上下文：
  user: "帮我梳理 auth 模块的调用链"
  assistant: [调用 task]
  tool: "auth 模块被 3 个地方调用：..."   ← 只有结论，不含中间过程

Sub Agent 上下文（独立，用完即弃）：
  user: "梳理 auth 模块的调用链"
  assistant: [调用 grep]
  tool: [大量搜索结果]
  assistant: [调用 read_file]
  tool: [文件内容]
  ... （可能十几轮工具调用）
  assistant: "auth 模块被 3 个地方调用：..."
```

### 核心实现

task 是第二个流式工具（第一个是 bash），它用 `run_streaming` 把子 Agent 的进度实时推给 UI：

```python
async def run_streaming(self, description: str):
    # 构建子 Agent（排除 task 自身，防止递归）
    sub_registry = ToolRegistry()
    for name in self._parent_registry.names:
        if name == "task":
            continue
        tool = self._parent_registry.get(name)
        if tool is not None:
            sub_registry.register(tool)

    sub_agent = Agent(
        client=self._client,
        registry=sub_registry,
        system_prompt=SUB_AGENT_PROMPT,
        session_manager=None,  # 子 Agent 不持久化
    )

    # 运行子任务，转发事件
    text_parts = []
    async for event in sub_agent.run(description):
        if isinstance(event, ToolCallStart):
            yield ToolResultDelta(tool_name="task", content=f"▶ {event.tool_name}(...)")
        elif isinstance(event, ToolCallResult):
            yield ToolResultDelta(tool_name="task", content=f"  ✔ {preview}")
        elif isinstance(event, TextDelta):
            text_parts.append(event.content)

    # 最终结果
    yield ToolCallResult(tool_name="task", result="".join(text_parts))
```

### 关键设计

**1. 排除 task 自身**

```python
if name == "task":
    continue
```

子 Agent 不能调用 task 工具——否则会无限递归。

**2. 不持久化**

```python
session_manager=None
```

子 Agent 的对话不写入文件，用完即弃。它的价值全在最终返回的文本里。

**3. 依赖注入**

TaskTool 是唯一需要构造参数的工具——它需要 `client` 和 `registry`：

```python
class TaskTool(BaseTool):
    def __init__(self, client: OpenAIClient, registry: ToolRegistry):
        self._client = client
        self._parent_registry = registry
```

所以在 `cli.py` 中单独注册：

```python
registry.register_many([tool() for tool in BUILTIN_TOOLS])  # 其他工具无参构造
registry.register(TaskTool(client=client, registry=registry))  # task 单独注册
```

**4. 最大轮次保护**

```python
_MAX_TURNS = 25

if turn_count >= _MAX_TURNS:
    sub_agent.cancel()
    yield ToolResultDelta(content=f"⚠ 已达最大工具调用次数 ({_MAX_TURNS})")
    break
```

防止子 Agent 陷入死循环。

## skill — 技能加载

### 设计理念

skill 工具让 Agent 获得**可扩展的领域能力**。技能本质上是一段注入到对话的指令文本——告诉 Agent "当你做 X 任务时，按以下步骤执行"。

格式兼容 Claude Code 和 OpenClaw，用户可以从社区下载技能直接使用。

### 实现

```python
async def execute(self, name: str) -> ToolResult:
    skill = _find_skill(name)
    if skill is None:
        available = [s.name for s in _list_skills()]
        return ToolResult(content=f"技能 '{name}' 不存在。可用：{available}", is_error=True)

    content = skill.skill_file.read_text(encoding="utf-8")

    parts = [f"已加载技能 [{name}]，请严格按照以下指令行事：\n\n{content}"]
    if extra_files:
        parts.append(f"技能目录：{skill.skill_dir}")
        parts.append(f"额外资源文件：{extra_files}")

    return ToolResult(content="\n".join(parts))
```

技能加载就是读文件 → 返回文本。文本作为 `tool` 消息写入对话历史，模型后续能看到它，就像收到了一份操作手册。

### context_injection

skill 工具通过 `context_injection` 把可用技能列表注入 system prompt：

```python
def context_injection(self) -> str | None:
    skills = _list_skills()
    if not skills:
        return None
    lines = ["# 可用技能（通过 skill 工具加载）"]
    for s in skills:
        lines.append(f"- **{s.name}**：{s.description}")
    return "\n".join(lines)
```

每次 LLM 调用时，模型都能在 system prompt 末尾看到可用技能清单，自行判断是否需要加载。

### 技能发现

支持两种格式：

```python
def _list_skills() -> list[SkillInfo]:
    # 1. 目录形式：~/.anthony/skills/my-skill/SKILL.md
    for d in SKILLS_DIR.iterdir():
        skill_file = d / "SKILL.md"
        if skill_file.is_file():
            ...

    # 2. 单文件形式：~/.anthony/skills/quick-fix.md
    for f in SKILLS_DIR.glob("*.md"):
        ...
```

从 `SKILL.md` 的 YAML frontmatter 中读取 `name` 和 `description`。

## web_search — 联网搜索

基于 Tavily Search API，最简单的封装：

```python
class WebSearchTool(BaseTool):

    def __init__(self):
        api_key = os.environ.get("TAVILY_API_KEY", "")
        self._client = TavilyClient(api_key=api_key) if api_key else None

    async def execute(self, query: str) -> ToolResult:
        if not self._client:
            return ToolResult(content="未配置 TAVILY_API_KEY", is_error=True)

        response = await asyncio.to_thread(
            self._client.search, query=query, max_results=5,
        )
        return ToolResult(content=self._format_results(response["results"]))
```

关键点：
- **API Key 可选**：没配置不报错，调用时才提示
- **同步 API 走线程池**：Tavily SDK 是同步的，用 `to_thread` 包装
- **结果格式化**：每条包含标题、URL、内容摘要，模型能根据摘要决定是否用 `web_fetch` 深入

## web_fetch — 网页抓取

### 双模式设计

```
阅读模式（默认）：返回网页正文，链接文本用 [[双方括号]] 标记
链接提取模式：传入关键词，只返回匹配的链接和 URL
```

这个设计解决了一个实际问题：模型看到网页正文后想点某个链接，但纯文本里没有 URL。双方括号标记告诉模型"这里原来有个链接"，再用链接提取模式拿到真实 URL。

### 阅读模式

```python
@staticmethod
def _html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # 把 <a href="...">文本</a> 替换为 [[文本]]
    for a in soup.find_all("a"):
        text = a.get_text(strip=True)
        href = str(a.get("href") or "").strip()
        if text and href and not href.startswith(("javascript:", "#")):
            a.replace_with(f"[[{text}]]")
        else:
            a.replace_with(text)

    # html2text 转纯文本
    converter = html2text.HTML2Text()
    converter.ignore_links = True
    converter.ignore_images = True
    converter.body_width = 0
    return converter.handle(str(soup))
```

先用 BeautifulSoup 把 `<a>` 标签替换为 `[[文本]]`，再用 html2text 转 Markdown。为什么不让 html2text 保留链接？因为 URL 太长会浪费大量 token，而模型只需要知道"这里有链接"就够了。

### 反爬对策

```python
async with AsyncSession(
    impersonate="chrome131",  # 模拟 Chrome 浏览器指纹
    verify=verify,
) as session:
    resp = await session.get(url, allow_redirects=True)
```

用 `curl_cffi` 代替 `aiohttp`/`httpx`——它能模拟浏览器的 TLS 指纹，绕过 Cloudflare 等反爬。先尝试验证 SSL 证书，失败后 `verify=False` 重试，覆盖自签名证书的情况。

## 小结

| 工具 | 核心机制 | 特殊之处 |
|---|---|---|
| `think` | 原样返回 | 压缩时会被彻底删除 |
| `task` | 子 Agent 独立上下文 | 流式工具、排除自身防递归、依赖注入 |
| `skill` | 读文件注入对话 | context_injection 注入可用技能列表 |
| `web_search` | Tavily API 封装 | API Key 可选、同步 SDK 走线程池 |
| `web_fetch` | HTML → Markdown | 双模式（阅读/链接提取）、curl_cffi 反爬 |

至此 14 个工具全部实现完毕。下一章进入上下文管理——当对话越来越长，怎么在 token 限制内保留关键信息。
