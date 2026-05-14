# 第十章：TUI 界面

前面九章构建了 Agent 的全部"内功"。这一章把它们串起来，用 Textual 框架做成终端应用——消息流渲染、工具卡片折叠、自动滚动、快捷键交互。

## 技术选型：Textual

[Textual](https://textual.textualize.io/) 是一个 Python TUI 框架，提供了类似 Web 前端的开发体验：组件树、CSS 样式、事件冒泡、异步 worker。选它的原因：

- **纯 Python** — 不需要编译、不依赖 ncurses
- **声明式布局** — CSS 控制样式，`compose()` 声明组件树
- **异步原生** — 和 Agent 的 `async for` 事件流天然契合
- **Markdown 流式渲染** — 内置 `MarkdownStream`，逐 token 追加就能实时渲染

## 整体架构

```
┌──────────────────────────────────────────────────┐
│  AgentApp (App)                                  │
│  ├── _MessageArea (VerticalScroll)  ← 消息区域    │
│  │     ├── BannerWidget             ← 启动 Logo  │
│  │     ├── Static (user-msg)        ← 用户消息    │
│  │     ├── Markdown (llm-markdown)  ← LLM 回复    │
│  │     ├── Collapsible (tool-card)  ← 工具卡片    │
│  │     └── Static (status-info)     ← 状态信息    │
│  ├── Vertical (bottom-bar)                       │
│  │     ├── ContextBar               ← token 进度条│
│  │     └── ChatInput                ← 输入框      │
│  └── Footer                         ← 快捷键提示  │
└──────────────────────────────────────────────────┘
```

三个核心文件：

| 文件 | 职责 |
|---|---|
| `app.py` | 应用主类，组件组装、快捷键、worker 调度 |
| `renderer.py` | 事件流渲染器，消费 `AgentEvent` 产出 Widget |
| `chat_input.py` | 多行输入框，Enter 发送 / Shift+Enter 换行 |

辅助文件：

| 文件 | 职责 |
|---|---|
| `styles.py` | 全部 CSS 样式，集中管理 |
| `banner.py` | 启动时的金色渐变 ASCII 艺术字 |
| `context_bar.py` | 单行 token 使用进度条 |

## 事件驱动：从 Agent 到 UI

Agent 的输出是 `AsyncGenerator[AgentEvent, None]`，TUI 的核心工作就是消费这个流。

### 事件类型

```python
# agent/events.py
class AgentEvent(BaseModel): pass

class ReasoningDelta(AgentEvent):     # thinking 模型推理片段
    content: str

class TextDelta(AgentEvent):          # LLM 文本片段
    content: str

class ToolCallStart(AgentEvent):      # 工具开始执行
    tool_name: str
    arguments: dict

class ToolArgsDelta(AgentEvent):      # 工具参数流式到达（如 write_file 的内容）
    tool_name: str
    field_name: str
    content: str

class ToolCallResult(AgentEvent):     # 工具执行结果
    tool_name: str
    result: str

class ToolResultDelta(AgentEvent):    # 工具流式结果（bash 输出、子 Agent 进度）
    tool_name: str
    content: str

class ResponseComplete(AgentEvent): pass    # 一轮 LLM 响应结束
class UsageReport(AgentEvent): ...          # token 用量报告
class CompactStart(AgentEvent): ...         # 压缩开始
class CompactComplete(AgentEvent): ...      # 压缩完成
class BashBackgroundable(AgentEvent): pass  # bash 可转后台提示
```

### 事件分发

EventRenderer 用一个类型→方法名映射表做分发，避免冗长的 if-elif：

```python
class EventRenderer:
    _HANDLERS: dict[type, str] = {
        ReasoningDelta:    "_on_reasoning_delta",
        TextDelta:         "_on_text_delta",
        ToolCallStart:     "_on_tool_call_start",
        ToolCallResult:    "_on_tool_call_result",
        ToolResultDelta:   "_on_tool_result_delta",
        ResponseComplete:  "_on_response_complete",
        UsageReport:       "_on_usage_report",
        # ...
    }

    async def _dispatch(self, event: AgentEvent) -> None:
        handler_name = self._HANDLERS.get(type(event))
        if handler_name:
            await getattr(self, handler_name)(event)
```

消费入口只有一行：

```python
async def render_event_stream(self, events: AsyncIterable[AgentEvent]) -> None:
    self._reset()
    async for event in events:
        await self._dispatch(event)
```

这种设计让 EventRenderer **完全不依赖 Agent 类型**——只要你给它一个 `AsyncIterable[AgentEvent]`，它就能渲染。测试时可以用 mock 的事件流。

## 流式 Markdown 渲染

LLM 的文本回复逐 token 到达。如果攒完再渲染，用户要等几秒才能看到内容；逐 token 用 `Static.update()` 又无法渲染 Markdown 格式。

Textual 提供了 `MarkdownStream`，专门解决这个问题：

```python
async def _on_text_delta(self, event: TextDelta) -> None:
    if not self._streaming_text:
        # 首个 token：创建 Markdown widget + 流
        self._md_widget = Markdown("", classes="llm-markdown")
        await self._area.mount(self._md_widget)
        self._md_stream = Markdown.get_stream(self._md_widget)
        self._streaming_text = True

    # 追加文本片段
    await self._md_stream.write(event.content)
    self._auto_scroll()
```

MarkdownStream 内部会缓冲未完成的 Markdown 结构（如半个代码块），等结构闭合后再渲染。所以中间状态不会出现乱码。

一轮结束时必须调用 `stop()` 关闭流：

```python
async def _on_response_complete(self, _event: ResponseComplete) -> None:
    await self._md_stream.stop()
    self._streaming_text = False
```

## 工具卡片

工具调用渲染为可折叠的卡片（Textual 的 `Collapsible` widget）：

```
▼ [Tool] bash
   参数:
     command = ls -la
   ⏳ 执行中…          ← 执行前
   ✔ 结果:              ← 执行后
     total 48
     drwxr-xr-x ...
```

执行完成后自动折叠，不占空间：

```
▶ [Tool] bash           ← 折叠状态，点击可展开查看详情
```

### 流式参数卡片

写文件等工具的参数（文件内容）很长，等参数完整再创建卡片会导致 UI 卡顿。`ToolArgsDelta` 事件让卡片在参数到达时就创建，内容逐 chunk 填充：

```python
async def _on_tool_args_delta(self, event: ToolArgsDelta) -> None:
    if not self._streaming_tool:
        # 首个 chunk：创建卡片
        self._tool_card = Collapsible(...)
        await self._area.mount(self._tool_card)
        self._streaming_tool = True

    # 追加内容
    self._tool_stream_content += event.content
    self._tool_stream_static.update(...)
```

### 流式结果窗口

bash 和 task 工具的执行过程也是流式的（`ToolResultDelta`）。结果在卡片内的固定高度窗口中滚动显示，只保留最近 10 行：

```python
async def _on_tool_result_delta(self, event: ToolResultDelta) -> None:
    self._task_progress_lines.append(event.content)
    if len(self._task_progress_lines) > self._TASK_WINDOW_LINES:
        self._task_progress_lines = self._task_progress_lines[-self._TASK_WINDOW_LINES:]

    display = "\n".join(self._task_progress_lines)
    # task 工具显示 [Sub Agent] 前缀，其他工具直接显示
    if event.tool_name == "task":
        content = f"[Sub Agent]\n{display}"
    else:
        content = display
    self._task_progress_widget.update(content)
```

## 自动滚动与用户滚动

一个微妙的交互问题：LLM 输出时应该自动滚到底部，但如果**用户正在往上翻看历史**，自动滚动就很烦——刚拉上去就被弹回来。

解决方案是 `_MessageArea` 监听 `scroll_y` 变化：

```python
class _MessageArea(VerticalScroll):
    def watch_scroll_y(self, old, new) -> None:
        is_at_bottom = new >= self.max_scroll_y - _NEAR_BOTTOM_THRESHOLD
        app._renderer.notify_user_scroll(is_at_bottom)
```

EventRenderer 据此决定是否自动滚动：

```python
def _auto_scroll(self) -> None:
    if not self._user_scrolled_away:
        self._area.scroll_end(animate=False)
```

- 用户往上滚 → `_user_scrolled_away = True` → 停止跟随
- 用户滚回底部 → `_user_scrolled_away = False` → 恢复跟随

## Worker 模式

Textual 的 `@work` 装饰器把 Agent 调用放到后台协程，不阻塞 UI 事件循环：

```python
@work(exclusive=True, exit_on_error=False)
async def _run_agent(self, user_input: str) -> None:
    input_box.disabled = True          # 禁用输入
    await renderer.render_user_message(user_input)
    await renderer.render_event_stream(agent.run(user_input))
    input_box.disabled = False         # 恢复输入
    input_box.focus()
```

`exclusive=True` 确保同一时刻只有一个 Agent 调用在运行——用户快速连发消息不会导致并发执行。

## ChatInput：输入框

继承 Textual 的 `TextArea`，自定义了两个行为：

```python
class ChatInput(TextArea):
    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            # Enter → 发送消息
            self.post_message(self.Submitted(self.text.strip()))
        elif event.key == "shift+enter":
            # Shift+Enter → 换行
            self.replace("\n", start, end)
```

还有一个细节：ChatInput 重写了 `_merge_bindings()`，确保 Footer 里的快捷键按声明顺序显示（TextArea 父类合并 binding 时会打乱顺序）。

## ContextBar：token 进度条

单行显示当前上下文使用量：

```
Context ████████░░░░░░░░┃░░░ 42% (53K / 128K)
```

- 绿色：< 60%
- 黄色：60% ~ 压缩阈值（80%）
- 红色：> 压缩阈值
- `┃` 标记压缩阈值位置

每次 `UsageReport` 事件到达或历史恢复后更新。

## 快捷键

| 快捷键 | 功能 | 实现 |
|---|---|---|
| Esc | 中断输出 | `agent.cancel()` 设置取消标志 |
| Ctrl+D | 退出 | 取消 Agent → 清理工具 → 退出 |
| Ctrl+C | 复制选中文本 | Textual 内置 `screen.copy_text` |
| Ctrl+Y | 复制最后回复 | 从 renderer 取 `_last_reply`，写入系统剪贴板 |
| Ctrl+K | 压缩上下文 | 触发 `agent.force_compact()` |
| Ctrl+B | 转后台 | `bash_tool.request_background()` |

### 剪贴板兼容

Textual 默认用 OSC 52 转义序列写剪贴板，但很多终端不支持。`copy_to_clipboard` 覆写了默认行为，按平台选择系统命令：

```python
def copy_to_clipboard(self, text: str) -> None:
    clip_cmd = self._get_clip_command()
    # macOS: pbcopy, Linux: xclip/xsel, Windows: clip
    subprocess.run(clip_cmd, input=text.encode(), check=True)
```

## 历史恢复

启动时如果有历史消息，不能直接一条条 mount（会导致几百次布局刷新，界面卡死）。解决方案：

1. 显示"正在恢复"提示
2. 等首帧渲染完后（`call_after_refresh`）再加载
3. **隐藏消息区域**（`area.display = False`），批量挂载所有 widget
4. 滚到底部后再显示（`area.display = True`）

```python
async def _load_history(self) -> None:
    area.display = False               # 隐藏
    await renderer.render_history(messages)
    area.scroll_end(animate=False)
    # call_after_refresh → _reveal_history
    #   area.display = True            # 显示
```

这样用户看不到从顶部快速滚到底部的过程，体验更流畅。

`render_history` 内部也做了优化：先构建所有 widget 列表，最后一次性 `mount_all`，只触发一次布局刷新。

## CSS 样式

所有样式集中在 `styles.py` 的一个 CSS 字符串中：

```python
APP_CSS = """\
#message-area { height: 1fr; }       /* 消息区占满剩余空间 */
#bottom-bar { dock: bottom; }         /* 输入区固定底部 */
#input-box { max-height: 8; }         /* 输入框最多 8 行 */
.tool-card { background: $surface; }  /* 工具卡片背景色 */
.reasoning-block { max-height: 8; }   /* thinking 最多显示 8 行 */
...
"""
```

用 Textual 的 CSS 变量（`$surface`、`$accent` 等），自动适配亮色/暗色主题。

## 启动流程

`cli.py` 的 `main()` 串起所有模块：

```python
def main():
    # 1. 解析参数（--resume / --new / list / skills）
    # 2. 会话管理
    session_mgr = SessionManager()
    session_id = session_mgr.init()

    # 3. 创建 LLM 客户端
    client = OpenAIClient()

    # 4. 注册工具
    registry = ToolRegistry()
    registry.register_many([tool() for tool in BUILTIN_TOOLS])
    registry.register(TaskTool(client=client, registry=registry))

    # 5. 创建 Agent
    agent = Agent(client=client, registry=registry, ...)
    agent.load_history()

    # 6. 启动 TUI
    AgentApp(agent=agent, session_id=session_id, tool_registry=registry).run()
```

注意 `TaskTool` 单独注册——它需要 `client` 和 `registry` 的引用来创建子 Agent（第六章讲过的依赖注入）。

## 小结

| 组件 | 职责 |
|---|---|
| `AgentApp` | 组件组装、快捷键绑定、worker 调度 |
| `EventRenderer` | 消费事件流，产出 Widget，处理流式状态机 |
| `ChatInput` | 多行输入，Enter 发送 / Shift+Enter 换行 |
| `_MessageArea` | 滚动监听，控制自动滚动行为 |
| `ContextBar` | token 用量可视化 |
| `BannerWidget` | 启动 Logo |
