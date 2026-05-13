<p align="center">
  <img src="resource/icon.png" width="120" alt="Anthony Agent">
</p>

<h1 align="center">Anthony Agent</h1>

<p align="center">
  轻量、透明、可定制的终端 AI 编码助手<br>
  <sub>~2000 行 Python · 会话明文存储 · 兼容任意 OpenAI API · 兼容 Claude Code Skill</sub>
</p>

<p align="center">
  <a href="#-快速开始"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT License"></a>
</p>

<p align="center">
  <img src="resource/demo.gif" width="720" alt="Demo">
</p>

## 特性

- **轻量** — 全部代码约 2000 行 Python，无复杂框架，依赖少
- **透明** — 会话以 JSONL 明文存储在项目目录下（`.anthony/`），随时可查、可改、可删
- **模型自由** — 兼容任何 OpenAI 格式 API（OpenAI / DeepSeek / Qwen / Ollama 等），一个 `.env` 切换
- **Skill 生态** — 兼容 [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/skills) / [OpenClaw](https://github.com/nicepkg/openclaw) 的 Skill 格式，可从 [ClawHub](https://clawhub.com) 下载社区技能
- **14 个内置工具** — 文件读写编辑、正则搜索、Shell 命令（前台/后台）、联网搜索与网页抓取、子 Agent 委派
- **上下文管理** — 旧工具输出自动裁剪 + LLM 摘要压缩 + Markdown 归档，长会话不丢关键信息
- **Thinking 模型** — 流式展示 DeepSeek / Qwen 等模型的推理过程
- **可学可改** — 配套 [8 章教程](#-教程)，适合学习 Agent 架构或二次开发

## 快速开始

### 安装

**方式一：pip install（推荐）**

```bash
git clone https://github.com/your-username/anthony-agent.git
cd anthony-agent
pip install -e .
anthony   # 启动
```

**方式二：直接运行源码**

```bash
git clone https://github.com/your-username/anthony-agent.git
cd anthony-agent
pip install -r requirements.txt
python -m anthony_agent   # 启动
```

### 配置

```bash
mkdir -p ~/.anthony
cp .env.example ~/.anthony/.env
# 编辑 ~/.anthony/.env，填入你的 API Key
```

`.env` 必填项：

```bash
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
MODEL_NAME=gpt-4o
```

可选项：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `SUPPORTS_VISION` | 是否支持图片输入（纯文本模型设为 `false`） | `true` |
| `MAX_COMPLETION_TOKENS` | 单次最大输出 token | `12800` |
| `MAX_INPUT_TOKENS` | 上下文窗口大小 | `200000` |
| `TAVILY_API_KEY` | 联网搜索（`web_search` 工具需要） | — |

<details>
<summary><b>使用其他模型</b>（DeepSeek / Qwen / Ollama / Azure 等）</summary>

兼容所有 OpenAI 格式 API，只需修改三个变量：

**DeepSeek**
```bash
OPENAI_API_KEY=sk-your-deepseek-key
OPENAI_BASE_URL=https://api.deepseek.com/v1
MODEL_NAME=deepseek-chat
SUPPORTS_VISION=false
```

**Qwen**
```bash
OPENAI_API_KEY=sk-your-qwen-key
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen-max
```

**Ollama 本地模型**
```bash
OPENAI_API_KEY=ollama
OPENAI_BASE_URL=http://localhost:11434/v1
MODEL_NAME=qwen2.5:32b
SUPPORTS_VISION=false
MAX_INPUT_TOKENS=32000
```

其他兼容 API（Azure OpenAI / Groq / Together AI / vLLM / LM Studio 等）同理。
</details>

### 使用

```bash
anthony              # 进入会话（自动恢复最近会话或新建）
anthony --new        # 新建会话
anthony --resume     # 恢复最近会话
anthony --resume ID  # 恢复指定会话
anthony list         # 列出历史会话
anthony skills       # 列出可用技能
```

进入后用自然语言对话即可。Agent 会自主调用工具完成任务。

## 会话存储

会话数据存储在**当前工作目录**下，每个项目独立，互不干扰：

```
your-project/
└── .anthony/
    └── sessions/
        └── 20260512_143022_a1b2/
            ├── messages.jsonl          # 完整对话记录（JSONL 明文）
            └── transcripts/            # 上下文压缩时的归档快照
                └── 2026-05-12_15-30-00.md
```

> 建议将 `.anthony/` 加入项目的 `.gitignore`。

## 工具

共 14 个内置工具，覆盖编码助手的核心场景：

| 类别 | 工具 | 说明 |
|---|---|---|
| **文件** | `read_file` | 读取文件（带行号），支持行范围和图片读取 |
| | `write_file` | 创建或覆写文件 |
| | `edit_file` | 精确字符串搜索替换 |
| | `multi_edit` | 同一文件多处原子修改 |
| **搜索** | `grep` | 正则递归搜索文件内容 |
| | `glob` | 按模式查找文件路径 |
| | `ls` | 列出目录内容 |
| **Shell** | `bash` | 前台执行命令（流式输出，可 Ctrl+B 转后台） |
| | `background_bash` | 后台运行长时间命令 |
| **联网** | `web_search` | Tavily 搜索（需配置 API Key） |
| | `web_fetch` | 抓取网页转 Markdown |
| **高级** | `think` | 深度思考，用于复杂推理 |
| | `task` | 委派子任务给独立子 Agent |
| | `skill` | 加载技能指令集 |

## 快捷键

| 快捷键 | 功能 |
|---|---|
| `Enter` / `Shift+Enter` | 发送 / 换行 |
| `Esc` | 中断输出 |
| `Ctrl+C` | 复制选中文本（Mac 终端下 Cmd+C 不可用） |
| `Ctrl+Y` | 复制最后一条回复到剪贴板 |
| `Ctrl+B` | 将运行中的 bash 命令转入后台 |
| `Ctrl+K` | 手动压缩上下文 |
| `Ctrl+D` | 退出 |

## 技能系统

Skill 格式兼容 [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/skills) 和 [OpenClaw](https://github.com/nicepkg/openclaw)，可直接从 [ClawHub](https://clawhub.com) 下载社区技能。

技能存放在 `~/.anthony/skills/`：

```
~/.anthony/skills/
├── my-skill-v1/          # 目录形式（推荐）
│   ├── SKILL.md          # 技能指令（必需）
│   ├── _meta.json        # 元信息（可选）
│   └── template.py       # 资源文件（可选，Agent 可读取）
└── quick-fix.md          # 单文件形式（文件名即技能名）
```

`SKILL.md` 格式：

```markdown
---
name: my-skill
description: 一句话描述
---

技能指令正文。Agent 加载后会严格按此执行。
```

```bash
anthony skills            # 查看可用技能
# 对话中直接说"用 xxx 技能"，或 Agent 自动判断加载
```

## 架构

```
CLI (cli.py)
 └─ AgentApp (Textual TUI)
     ├─ Agent (ReAct Loop)
     │   ├─ OpenAIClient ─── 异步流式调用，自动重试
     │   ├─ ToolRegistry ─── 14 个内置工具，并行执行
     │   ├─ SessionManager ─ JSONL 持久化，会话恢复
     │   └─ Compactor ────── 工具输出裁剪 + LLM 摘要压缩
     └─ EventRenderer ────── 流式 Markdown / 工具卡片 / Token 进度条
```

<details>
<summary><b>项目结构</b></summary>

```
anthony_agent/
├── cli.py                 # CLI 入口
├── prompts.py             # System Prompt + 压缩 Prompt
├── agent/
│   ├── agent.py           # ReAct 循环
│   ├── events.py          # 事件类型
│   └── stream_parser.py   # 流式 JSON 解析
├── client/
│   ├── models.py          # Message / StreamDelta
│   └── openai_client.py   # 异步 OpenAI 客户端
├── config/
│   └── settings.py        # 配置加载
├── memory/
│   ├── compactor.py       # 上下文压缩
│   ├── session.py         # 会话管理
│   └── storage.py         # JSONL 读写
├── tools/
│   ├── base.py            # 工具基类
│   ├── registry.py        # 注册中心
│   └── builtins/          # 14 个内置工具
└── ui/
    ├── app.py             # Textual 主应用
    ├── renderer.py        # 事件流渲染
    ├── chat_input.py      # 输入框
    ├── context_bar.py     # Token 进度条
    └── styles.py          # 样式
```
</details>

## 教程

配套 8 章教程，从零理解每个模块：

| 章节 | 主题 |
|---|---|
| [01 Agent Loop](docs/01-agent-loop.md) | ReAct 循环核心，最简 Agent 实现 |
| [02 工具系统](docs/02-tool-system.md) | 工具基类、注册中心、设计决策 |
| [03 文件工具](docs/03-file-tools.md) | read_file / write_file / edit_file / multi_edit |
| [04 搜索工具](docs/04-search-tools.md) | grep / glob / ls |
| [05 命令执行](docs/05-shell-tools.md) | bash / background_bash / 转后台机制 |
| [06 高级工具](docs/06-advanced-tools.md) | think / task / skill / web_search / web_fetch |
| [07 上下文管理](docs/07-context-management.md) | 两层压缩、token 计算、归档 |
| [08 会话与提示词](docs/08-session-and-prompt.md) | JSONL 持久化、会话恢复、System Prompt 设计 |
| [09 LLM 客户端](docs/09-llm-client.md) | 异步流式调用、重试、reasoning 支持 |
| [10 TUI](docs/10-tui.md) | Textual 界面、事件渲染、流式 Markdown |

## License

[MIT](LICENSE)
