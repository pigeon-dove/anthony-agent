<p align="center">
  <img src="resource/icon.png" width="120" alt="Anthony Agent">
</p>

<h1 align="center">Anthony Agent</h1>

<p align="center">
  <b>一个从零手写的终端 AI 编码助手</b><br>
  用 ~2000 行 Python 实现 ReAct Agent + TUI + 工具系统 + 上下文管理
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT License">
</p>

---

## ✨ 特性

- **ReAct 工具循环** — 流式 LLM 调用 + 工具并行执行
- **Textual TUI** — 流式 Markdown 渲染、工具调用折叠卡片、token 进度条
- **14 个内置工具** — bash、文件读写编辑、代码搜索、子 Agent 委派、联网搜索、网页抓取等
- **智能上下文管理** — 两层压缩（micro_compact + LLM 摘要）+ Markdown 归档
- **会话持久化** — JSONL 逐条追加，支持恢复/列出历史会话
- **Thinking 模型支持** — 流式展示 reasoning 过程（DeepSeek/Qwen 等）
- **Bash 转后台** — 运行中一键 Ctrl+B 转入后台，进程无缝移交
- **技能系统** — 可扩展的技能指令集，按需加载

## 🏗️ 架构

```
CLI (cli.py)
 └─ AgentApp (Textual TUI)
     ├─ Agent (ReAct Loop)
     │   ├─ OpenAIClient (异步流式 LLM)
     │   ├─ ToolRegistry → 14 个内置工具
     │   ├─ SessionManager (JSONL 持久化)
     │   └─ Compactor (两层上下文压缩)
     └─ EventRenderer (事件 → UI 渲染)
```

## 🚀 快速开始

### 1. 安装

```bash
git clone https://github.com/your-username/anthony-agent.git
cd anthony-agent
pip install -e .
```

### 2. 配置环境变量

配置文件路径：`~/.anthony/.env`

```bash
mkdir -p ~/.anthony
cp .env.example ~/.anthony/.env
```

编辑 `~/.anthony/.env`，填入你的配置：

```bash
# 必填：你的 API Key
OPENAI_API_KEY=sk-your-api-key-here

# API 地址（支持任何 OpenAI 兼容的 API）
OPENAI_BASE_URL=https://api.openai.com/v1

# 模型名称
MODEL_NAME=gpt-4o

# 是否支持图片输入（纯文本模型如 DeepSeek-R1 设为 false）
SUPPORTS_VISION=true

# Token 上限
MAX_COMPLETION_TOKENS=12800
MAX_INPUT_TOKENS=200000

# 可选：Tavily 搜索 API Key（不填则 web_search 工具不可用）
TAVILY_API_KEY=your-tavily-api-key-here
```

#### 使用其他大模型

本项目兼容所有 OpenAI 格式 API。只需修改三个变量即可切换模型：

<details>
<summary><b>DeepSeek</b></summary>

```bash
OPENAI_API_KEY=sk-your-deepseek-key
OPENAI_BASE_URL=https://api.deepseek.com/v1
MODEL_NAME=deepseek-chat
SUPPORTS_VISION=false
```
</details>

<details>
<summary><b>Qwen (通义千问)</b></summary>

```bash
OPENAI_API_KEY=sk-your-qwen-key
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen-max
SUPPORTS_VISION=true
```
</details>

<details>
<summary><b>本地模型 (Ollama)</b></summary>

```bash
OPENAI_API_KEY=ollama
OPENAI_BASE_URL=http://localhost:11434/v1
MODEL_NAME=qwen2.5:32b
SUPPORTS_VISION=false
MAX_INPUT_TOKENS=32000
```
</details>

<details>
<summary><b>其他 OpenAI 兼容 API</b></summary>

任何提供 OpenAI 兼容接口的服务都可以使用（如 Azure OpenAI、Groq、Together AI、vLLM、LM Studio 等），只需按上述格式配置对应的 `BASE_URL`、`API_KEY` 和 `MODEL_NAME`。

</details>

### 3. 运行

```bash
anthony              # 进入会话（自动恢复最近会话或新建）
anthony --new        # 新建会话
anthony --resume     # 恢复最近会话
anthony --resume ID  # 恢复指定会话
anthony list         # 列出历史会话
anthony skills       # 列出可用技能
```

## 🔧 内置工具

Agent 配备 14 个工具，覆盖编码助手的核心能力：

### 文件操作

| 工具 | 说明 |
|---|---|
| `read_file` | 读取文件内容（带行号），支持按行范围读取，支持读取图片 |
| `write_file` | 创建新文件或完全覆写已有文件 |
| `edit_file` | 通过精确字符串匹配进行搜索替换编辑 |
| `multi_edit` | 同一文件多处修改，原子性执行（全部成功或全部回滚） |

### 搜索

| 工具 | 说明 |
|---|---|
| `grep` | 按正则表达式递归搜索文件内容，支持文件名过滤 |
| `glob` | 按 glob 模式查找文件路径，支持 `**` 递归和 `{}` 花括号展开 |
| `ls` | 列出目录内容，显示文件名、类型和大小 |

### 命令执行

| 工具 | 说明 |
|---|---|
| `bash` | 在独立 shell 中执行命令，支持超时控制和流式输出 |
| `background_bash` | 后台执行长时间运行的命令（dev server、watch 等），支持查看输出和终止 |

### 联网

| 工具 | 说明 |
|---|---|
| `web_search` | 联网搜索（基于 Tavily API），需配置 `TAVILY_API_KEY` |
| `web_fetch` | 抓取网页内容并转为 Markdown，支持阅读模式和链接提取模式 |

### 高级

| 工具 | 说明 |
|---|---|
| `think` | 无副作用的深度思考工具，用于复杂推理和方案梳理 |
| `task` | 委派子任务给独立子 Agent，不污染当前对话上下文 |
| `skill` | 按需加载预定义的技能指令集 |

## ⌨️ 快捷键

| 快捷键 | 功能 |
|---|---|
| `Enter` | 发送消息 |
| `Shift+Enter` | 换行 |
| `Esc` | 中断当前输出 |
| `Ctrl+B` | 将正在执行的 bash 命令转入后台 |
| `Ctrl+K` | 手动压缩上下文 |
| `Ctrl+Y` | 复制最后一条回复 |
| `Ctrl+S` | 切换选择模式（可复制文本） |
| `Ctrl+D` | 退出 |

## 🧩 技能系统

技能（Skill）是可扩展的指令集，Agent 在需要时通过 `skill` 工具按需加载。

### 技能目录

技能存放在 `~/.anthony/skills/` 下，支持两种格式：

**目录形式**（推荐，可包含额外资源文件）：

```
~/.anthony/skills/
├── my-skill-v1/
│   ├── SKILL.md          # 技能指令（必需）
│   ├── _meta.json        # 元信息（可选）
│   └── template.py       # 额外资源文件（可选）
└── another-skill/
    └── SKILL.md
```

**单文件形式**（简单场景）：

```
~/.anthony/skills/
└── quick-fix.md          # 文件名即技能名
```

### SKILL.md 格式

```markdown
---
name: my-skill
description: 这个技能做什么的一句话描述
---

# 技能指令

这里写详细的指令内容，Agent 加载技能后会严格按这些指令行事。

可以包含：
- 工作流程步骤
- 代码模板
- 注意事项
- 引用技能目录下的其他资源文件
```

### 使用

```bash
# 查看可用技能
anthony skills

# 在对话中，Agent 会自动判断是否需要加载技能
# 你也可以直接告诉它："用 xxx 技能来做"
```

## 📂 项目结构

```
anthony_agent/
├── cli.py                 # CLI 入口
├── prompts.py             # System Prompt + 压缩 Prompt
├── agent/                 # Agent 核心
│   ├── agent.py           # ReAct 循环
│   ├── events.py          # 事件流定义
│   └── stream_parser.py   # 流式 JSON 参数解析
├── client/                # LLM 客户端
│   ├── models.py          # 数据模型（Message, StreamDelta 等）
│   └── openai_client.py   # 异步 OpenAI 客户端封装
├── config/                # 配置管理
│   └── settings.py        # 从 ~/.anthony/.env 加载配置
├── memory/                # 记忆 & 持久化
│   ├── compactor.py       # 两层上下文压缩
│   ├── session.py         # 会话创建/恢复/归档
│   └── storage.py         # JSONL 读写
├── tools/                 # 工具系统
│   ├── base.py            # 工具基类（BaseTool, ToolResult）
│   ├── registry.py        # 工具注册中心
│   └── builtins/          # 14 个内置工具
└── ui/                    # TUI 界面
    ├── app.py             # Textual 主应用
    ├── renderer.py        # 事件流 → UI 渲染
    ├── chat_input.py      # 输入框组件
    ├── context_bar.py     # Token 进度条组件
    └── styles.py          # TCSS 样式
```

## 📖 教程：手把手实现

本项目配套了分章节教程，带你从零理解每个模块的设计与实现：

1. [**CLI 与 TUI**](docs/01-cli-and-tui.md) — Textual 终端界面、启动流程
2. [**LLM 客户端**](docs/02-llm-client.md) — 异步流式调用、自动重试、reasoning 支持
3. [**Agent 循环**](docs/03-agent-loop.md) — ReAct 模式、事件驱动架构
4. [**工具系统**](docs/04-tool-system.md) — 工具基类、注册中心、并行执行
5. [**内置工具详解**](docs/05-builtin-tools.md) — 14 个工具的设计与实现
6. [**上下文管理**](docs/06-context-management.md) — 两层压缩、token 计算、归档
7. [**会话持久化**](docs/07-session.md) — JSONL 存储、会话恢复、历史列表
8. [**UI 渲染**](docs/08-ui-rendering.md) — 事件流渲染、流式 Markdown、工具卡片

## 📄 License

MIT
