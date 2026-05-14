# 第八章：会话持久化与 System Prompt

两个看似不相关的话题放在一起，是因为它们共同决定了 Agent "记住什么"和"怎么行动"。

## 会话持久化

### 存储位置

会话数据存储在**当前工作目录**下，不是用户 home 目录：

```
your-project/
└── .anthony/
    └── sessions/
        ├── 20260512_143022_a1b2/
        │   ├── messages.jsonl
        │   └── transcripts/
        │       └── 2026-05-12_15-30-00.md
        └── 20260513_091500_c3d4/
            └── messages.jsonl
```

这个设计让每个项目有独立的会话历史——在项目 A 的目录下启动 Agent 看到的是项目 A 的会话，切到项目 B 看到的是项目 B 的。不会串。

### JSONL 格式

每条消息独占一行 JSON：

```jsonl
{"role": "user", "content": "帮我看看 main.py"}
{"role": "assistant", "content": null, "tool_calls": [{"id": "call_1", ...}]}
{"role": "tool", "tool_call_id": "call_1", "content": "     1\timport os\n     2\t..."}
{"role": "assistant", "content": "main.py 有 50 行代码，主要做..."}
```

为什么用 JSONL 而不是 JSON 数组或数据库？

| 格式 | 追加写 | 断电安全 | 可读性 | 部分读取 |
|---|---|---|---|---|
| JSON 数组 | ❌ 每次要重写整个文件 | ❌ 写一半断电会损坏 | ✅ | ❌ |
| SQLite | ✅ | ✅ | ❌ 二进制 | ✅ |
| **JSONL** | **✅ 直接 append** | **✅ 最多丢最后一行** | **✅ 文本可读** | **✅ 逐行** |

JSONL 最适合对话日志的写入模式——每产生一条消息就 append 一行，中途崩溃最多丢最后一条，前面的全都完好。

### JSONLStorage

底层存储用 `jsonlines` 库封装：

```python
class JSONLStorage:
    def __init__(self, path: Path):
        self._path = path

    def append(self, record: dict) -> None:
        with jsonlines.open(self._path, mode="a") as writer:
            writer.write(record)

    def read_all(self) -> list[dict]:
        results = []
        bad = 0
        with jsonlines.open(self._path, mode="r") as reader:
            while True:
                try:
                    results.append(reader.read(type=dict))
                except EOFError:
                    break
                except jsonlines.InvalidLineError:
                    bad += 1
        if bad:
            logger.warning("跳过 %d 行无法解析的数据", bad)
        return results

    def overwrite(self, records: list[dict]) -> None:
        with jsonlines.open(self._path, mode="w") as writer:
            writer.write_all(records)
```

`read_all` 的容错设计：遇到损坏行（`InvalidLineError`）跳过继续读，不会因为一行坏数据导致整个会话丢失。

`overwrite` 只在上下文压缩时使用——压缩后需要用新的消息列表替换整个文件。

### SessionManager

在 JSONLStorage 之上封装会话生命周期管理：

```python
class SessionManager:
    def __init__(self, workdir=None):
        self._workdir = workdir or Path.cwd()
        self._anthony_dir = self._workdir / ".anthony"

    def init(self, session_id=None) -> str:
        """初始化会话：指定 ID → 恢复；无 ID → 找最近的或新建。"""
        if session_id:
            return self._activate(session_id)
        latest = self._find_latest()
        if latest:
            return self._activate(latest)
        return self.create_session()

    def create_session(self) -> str:
        """创建新会话，ID 格式：20260512_143022_a1b2。"""
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_id = f"{now}_{secrets.token_hex(2)}"
        ...
```

Session ID 是 `时间戳_随机4字符`——时间戳保证按时间排序，随机后缀避免同秒创建的冲突。

### 会话恢复

启动时的逻辑：

```
anthony              → init() → 找最近会话恢复，没有就新建
anthony --new        → create_session() → 强制新建
anthony --resume     → init() → 恢复最近
anthony --resume ID  → init(ID) → 恢复指定
```

恢复时 Agent 调用 `load_history()`：

```python
def load_history(self):
    raw = self._session.load_messages()
    repaired = self._repair_messages(raw)
    if len(repaired) != len(raw):
        self._session.overwrite_messages(repaired)
    self._messages = repaired
```

`_repair_messages` 修复中途退出导致的不完整序列——如果 assistant 消息有 tool_calls 但缺少对应的 tool message，补一条 `"[上次会话中途退出，此工具未执行]"`。

### 归档

上下文压缩时，完整消息历史会归档为 Markdown 文件：

```python
def save_transcript(self, messages: list[dict]) -> Path:
    transcripts_dir = self.session_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    path = transcripts_dir / f"{timestamp}.md"
    path.write_text(_messages_to_markdown(messages))
    return path
```

归档格式是人类可读的 Markdown——用户可以直接打开看，Agent 也可以用 `read_file` / `grep` 检索。

## System Prompt

### 整体结构

```
# 环境信息
# 1 核心原则（5 条）
# 2 工作流程
  ## 2.1 默认决策顺序
  ## 2.2 任务分流
  ## 2.3 何时需要先确认用户
# 3 工具使用指南（按类别）
# 4 上下文管理（让模型理解压缩行为）
# 5 回复规范
```

### 环境注入

```python
SYSTEM_PROMPT_TEMPLATE = """\
你是 Anthony Agent，一个自主编码助手...

# 环境
- 工作目录：{cwd}
- 系统：{os}，Shell：{shell}
- 会话 ID：{session_id}
- 会话目录：{session_dir}
"""
```

环境信息在启动时注入，包括工作目录、操作系统、会话路径。模型知道自己在哪个目录工作、归档文件在哪。

### 核心原则

五条原则中最重要的是**先理解再动手**和**最小变更**：

```
1. 先理解，再动手：修改代码前，先用工具充分了解相关文件和上下文。不要凭猜测编辑。
3. 最小变更：只改需要改的部分，不要重写或重构用户未要求修改的代码。
```

这两条直接影响 Agent 的行为质量。没有第一条，模型会在没读文件的情况下瞎改；没有第三条，模型会把整个文件重写。

### 工作流程

告诉模型按什么顺序行动：

```
1. grep / glob / ls 定位
2. read_file 阅读
3. 确认方案后编辑
4. 简洁汇报
```

这不是建议，是**默认行为**。大多数编码请求都应该走这个流程。

### 上下文管理说明

这是 prompt 中最长但最重要的部分——告诉模型"你的记忆会被压缩"，以及如何应对：

```
应对策略：每次回复时主动在正文里记下后续可能需要的关键事实：
读过/改过的文件绝对路径、关键函数名、核心报错、用户偏好等。
这些信息写进 assistant 消息正文后不会被压缩丢弃。
```

这一段让模型学会"自救"——在 content 里留下关键信息，即使工具输出被压缩了，结论还在。

### 回复规范

```
- 默认简短：3-5 句话说清楚
- 禁止：开头寒暄、结尾复述
- 代码修改后只说明：改了什么、为什么改、是否验证过
```

不写这些，模型会每次都 "好的！我来帮你..." 开头，然后把改动逐行解释一遍。显式约束后简洁很多。

### 压缩 Prompt

`SUMMARY_USER_PROMPT` 是发给 LLM 做上下文压缩的指令。关键设计：

```
# 必须保留
- 用户的需求、指令、偏好
- 已完成的操作：改了哪些文件、关键决策
- 未完成/待确认事项
- 关键标识符：文件名、函数名、报错信息

# 最后一轮衔接（极重要）
被压缩部分的最后一轮 assistant 回复若包含提议、提问，必须完整保留。
因为紧接着的未压缩轮次中，用户可能正在回应它。
```

"最后一轮衔接"是经过多次调试才加的——不加的话，压缩后模型回复了一个提问，下一轮用户的回答变成"无头指代"（不知道在回答什么）。

### 动态上下文

System prompt 在构建时还会拼接工具的 `context_injection`：

```python
def _build_messages(self):
    prompt = self._system_prompt
    tool_context = self._registry.collect_context()
    if tool_context:
        prompt += "\n\n" + tool_context
    return [{"role": "system", "content": prompt}] + cleaned
```

目前两个工具会注入动态上下文：
- `skill` — 可用技能列表
- `background_bash` — 活跃后台任务列表

## 小结

| 组件 | 职责 |
|---|---|
| `JSONLStorage` | JSONL 追加写/读取/覆写，容错跳过损坏行 |
| `SessionManager` | 会话创建/恢复/列出/归档，修复中途退出的不完整消息 |
| `SYSTEM_PROMPT_TEMPLATE` | 告诉模型身份、环境、工作流程、工具用法、压缩行为、回复规范 |
| `SUMMARY_USER_PROMPT` | 指导 LLM 压缩：保留什么、丢弃什么、最后一轮必须完整 |

