# Anthony Agent - 架构设计文档

> 一个教学类 Claude Code Agent 项目，旨在从零实现一个具备完整能力的 AI 编码助手。

## 📌 项目概述

Anthony Agent 是一个类 Claude Code 的 Agent 系统，核心目标是作为 **教学项目** 上传到 GitHub，帮助开发者理解 AI Agent 的完整架构与实现。

### 核心能力

| 能力 | 说明 |
|------|------|
| Agent Loop | 基础的 Agent 循环：接收输入 → 调用 LLM → 解析工具调用 → 执行工具 → 返回结果 |
| Tool Use | 完整的工具系统：文件操作、命令执行、搜索、网络获取 |
| Sub Agent | 子 Agent 的创建与管理，支持上下文隔离 |
| Skill Loading | 从外部文件加载 Skill（提示词模板/指令集） |
| Context Compact | 上下文压缩与摘要，管理 token 预算 |
| Task System | 任务的创建、跟踪与状态管理 |
| MCP 集成 | 接入 Model Context Protocol，动态发现和调用外部工具 |
| 流式输出 | 基于 OpenAI SDK 封装，支持流式返回 |
| 历史记忆 | JSONL 持久化：会话上下文备份 + 摘要上下文 |

---

## 📁 项目目录结构

```
anthony-agent/
├── README.md                        # 项目总览、教学指南
├── requirements.txt                 # Python 依赖
├── .env.example                     # 环境变量模板（API Key 等）
├── .gitignore                       # Git 忽略规则
├── main.py                          # 🚀 入口文件
│
├── docs/                            # 📝 文档 & 工作记录
│   ├── architecture.md              # 架构设计文档（本文件）
│   ├── roadmap.md                   # 开发路线图 / TODO
│   └── work-logs/                   # 每次工作的开发记录
│       ├── 2026-03-16_项目初始化与架构设计.md
│       └── ...
│
├── config/                          # ⚙️ 配置
│   ├── settings.py                  # 全局配置（模型名、token 阈值等）
│   └── prompts/                     # 系统提示词模板
│       └── system_prompt.md
│
├── src/                             # 🧠 核心源代码
│   ├── __init__.py
│   │
│   ├── client/                      # OpenAI 客户端封装
│   │   ├── __init__.py
│   │   └── openai_client.py         # 流式调用封装
│   │
│   ├── agent/                       # Agent 核心
│   │   ├── __init__.py
│   │   ├── agent.py                 # 主 Agent Loop（事件驱动）
│   │   ├── events.py                # 事件流模型（5 种事件）
│   │   └── sub_agent.py             # Sub Agent
│   │
│   ├── tools/                       # 工具系统（统一协议 + 注册中心）
│   │   ├── __init__.py              # 导出 BaseTool, ToolDefinition, ToolResult, ToolRegistry
│   │   ├── base.py                  # 工具基类 BaseTool & 数据模型
│   │   ├── registry.py              # 工具注册中心 ToolRegistry
│   │   ├── read.py                  # 读取文件内容
│   │   ├── write.py                 # 创建/覆盖写入文件
│   │   ├── edit.py                  # 精准编辑文件（搜索替换）
│   │   ├── multi_edit.py            # 同一文件多处编辑
│   │   ├── bash.py                  # 执行 shell 命令
│   │   ├── background_bash.py       # 后台运行长时间命令
│   │   ├── glob_search.py           # 按文件名模式查找
│   │   ├── grep_search.py           # 按内容搜索文件（ripgrep）
│   │   └── web_fetch.py             # 获取网页/URL 内容
│   │
│   ├── mcp/                         # MCP 集成
│   │   ├── __init__.py
│   │   ├── client.py                # MCP 客户端
│   │   └── registry.py              # MCP 工具注册
│   │
│   ├── skills/                      # Skill Loading 系统（加载逻辑）
│   │   ├── __init__.py
│   │   └── loader.py                # Skill 加载器
│   │
│   ├── context/                     # 上下文管理 & Compact
│   │   ├── __init__.py
│   │   ├── manager.py               # 上下文管理器（消息列表维护）
│   │   └── compactor.py             # 上下文压缩（摘要策略）
│   │
│   ├── memory/                      # 记忆 & 持久化
│   │   ├── __init__.py
│   │   ├── session.py               # 会话上下文备份
│   │   └── storage.py               # JSONL 读写工具
│   │
│   └── task/                        # Task System
│       ├── __init__.py
│       └── task_manager.py          # 任务管理
│
├── skills/                          # 📦 外部 Skill 文件（用户可扩展）
│   └── example_skill.md             # 示例 Skill
│
└── data/                            # 💾 运行时数据（已 gitignore）
    ├── sessions/                    # 会话上下文备份 (.jsonl)
    └── summaries/                   # 摘要上下文 (.jsonl)
```

---

## 🏗️ 模块设计说明

### 1. Client 层 (`src/client/`)

基于 OpenAI Python SDK 的封装层，负责与 LLM API 的所有交互。

**核心职责：**
- 封装 `openai.ChatCompletion` 调用
- 支持流式（streaming）返回
- 统一处理 API 错误与重试
- 管理 API Key 和模型配置

**关键类：**
- `OpenAIClient`：封装流式/非流式调用，返回统一格式的响应

---

### 2. Agent 核心 (`src/agent/`)

Agent 的主循环逻辑，是整个系统的中枢。采用 **事件驱动** 架构，Agent 通过 `AsyncGenerator` yield 事件流，外部自行决定如何消费。

**Agent Loop 流程：**

```
用户输入
    ↓
构建 messages（system prompt + 历史上下文 + 用户消息）
    ↓
调用 LLM（流式返回）
    ↓
解析 LLM 响应
    ├── 纯文本回复 → yield TextDelta 事件流 → yield ResponseComplete
    └── 工具调用请求 → yield ToolCallStart → 执行工具 → yield ToolCallResult → 回到"调用 LLM"
    ↓
yield UsageReport（每轮末尾）
    ↓
循环直到 LLM 不再调用工具
```

**事件流模型（`events.py`）：**

| 事件 | 含义 | 字段 |
|------|------|------|
| `TextDelta` | LLM 流式输出的文本片段 | `content: str` |
| `ToolCallStart` | LLM 决定调用工具（执行前触发） | `tool_name: str`, `arguments: dict` |
| `ToolCallResult` | 工具执行完成的结果 | `tool_name: str`, `result: str` |
| `ResponseComplete` | LLM 最终回复结束 | — |
| `UsageReport` | 单次 LLM 调用的 token 用量 | `prompt_tokens`, `completion_tokens`, `total_tokens` |

**关键类：**
- `Agent`：主 Agent，管理完整的对话循环，`run()` 返回事件流
- `SubAgent`：子 Agent，拥有独立的上下文，用于执行子任务（待实现）

---

### 3. 工具系统 (`src/tools/`)

采用 **统一协议 + 注册中心** 的架构，支持三种工具来源：固定工具、动态 Skill 工具、MCP 远程工具。

**核心抽象：**

| 类 | 文件 | 职责 |
|------|------|------|
| `ToolDefinition` | `base.py` | 工具定义（name + description + parameters JSON Schema） |
| `ToolResult` | `base.py` | 工具执行结果（content + is_error） |
| `BaseTool` | `base.py` | 工具基类 — `definition()` + `execute()` |
| `ToolRegistry` | `registry.py` | 注册中心 — 聚合、查询、分发执行 |

**三种工具来源：**

| 来源 | 特点 | 实现方式 |
|------|------|------|
| 固定工具 | 描述不变，生命周期=整个应用 | 每个工具一个类，继承 `BaseTool` |
| 动态 Skill 工具 | 描述随时变化，按需加载/卸载 | `SkillTool` 通用类，构造时传入配置数据 |
| MCP 工具 | 第三方远程提供，运行时发现 | `McpTool` 适配器，代理调用远端 |

**关键设计点：**
- `definition()` 是**方法**而非属性 → 每次调用时动态生成，天然支持 Skill 描述变更
- `execute()` 是 `async` 方法 → 适配项目的 async 架构，IO 不阻塞
- `ToolRegistry` 通过 `get_definitions()` 生成 OpenAI function calling 的 `tools` 参数
- MCP 工具名加 `mcp_{server}_` 前缀避免与内置工具冲突

**工具清单（计划）：**

| 类别 | 工具 | 文件 | 功能 |
|------|------|------|------|
| 📁 文件操作 | Read | `read.py` | 读取文件内容（支持指定行范围） |
| | Write | `write.py` | 创建/覆盖写入文件 |
| | Edit | `edit.py` | 精准编辑文件的特定部分（搜索替换） |
| | MultiEdit | `multi_edit.py` | 对同一文件进行多处编辑 |
| 💻 命令执行 | Bash | `bash.py` | 执行 shell 命令 |
| | BackgroundBash | `background_bash.py` | 后台运行长时间命令 |
| 🔍 搜索 | Glob | `glob_search.py` | 按文件名模式查找文件 |
| | Grep | `grep_search.py` | 按内容搜索文件（基于 ripgrep） |
| 🌐 网络 | WebFetch | `web_fetch.py` | 获取网页/URL 内容 |

---

### 4. MCP 集成 (`src/mcp/`)

接入 Model Context Protocol，支持动态发现和调用外部 MCP Server 提供的工具。

**核心职责：**
- 连接 MCP Server（支持 stdio / SSE 传输）
- 获取 MCP Server 暴露的工具列表
- 将 MCP 工具统一注册到 Agent 的工具注册表中
- 转发工具调用请求到对应的 MCP Server

**关键类：**
- `MCPClient`：MCP 客户端，管理与 MCP Server 的连接
- `MCPRegistry`：MCP 工具注册，将外部工具整合到内部工具系统

---

### 5. Skill Loading (`src/skills/`)

从外部文件加载 Skill（指令集/提示词模板），增强 Agent 的领域能力。

**设计思路：**
- 外部 Skill 文件存放在根目录 `skills/` 下（Markdown 格式）
- `src/skills/loader.py` 负责扫描、解析、加载 Skill
- 加载后的 Skill 注入到 system prompt 或作为上下文的一部分

---

### 6. 上下文管理 (`src/context/`)

管理对话的 messages 列表，以及在 token 超出预算时进行压缩。

**核心职责：**
- `ContextManager`：维护当前对话的 messages 列表，提供增删查接口
- `ContextCompactor`：当 token 数接近阈值时，对历史消息进行摘要压缩
  - 压缩前：将完整上下文备份到 JSONL（通过 memory 层）
  - 压缩后：用摘要替换旧消息，释放 token 空间

---

### 7. 记忆 & 持久化 (`src/memory/`)

负责将会话数据持久化到 JSONL 文件。

**存储内容：**

| 类型 | 存储位置 | 说明 |
|------|----------|------|
| 会话上下文备份 | `data/sessions/*.jsonl` | 当前会话内存中 messages 的完整备份 |
| 摘要上下文 | `data/summaries/*.jsonl` | 上下文压缩前保存的摘要 |

**关键类：**
- `SessionMemory`：管理会话级别的上下文备份
- `JSONLStorage`：通用的 JSONL 读写工具类

---

### 8. Task System (`src/task/`)

管理 Agent 执行过程中的任务。

**核心职责：**
- 任务的创建、更新、完成、失败
- 任务状态追踪
- 支持任务嵌套（主任务 → 子任务）

---

## 🔑 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 代码组织方式 | `src/` 目录结构 | 源码与配置/文档分离，层次清晰，适合教学 |
| 工具文件组织 | 统一协议 + 注册中心 | `BaseTool` 统一三种来源（固定/Skill/MCP），`ToolRegistry` 聚合管理 |
| 文档组织 | `docs/work-logs/` + 架构文档 | work-logs 记录每次开发，文件名带日期时间 |
| Skill 文件位置 | 根目录 `skills/`（外部） | 与加载逻辑 `src/skills/` 分离，用户扩展更方便 |
| 持久化格式 | JSONL | 追加写入友好，每行一条记录，便于流式处理 |
| LLM 客户端 | 基于 OpenAI SDK 封装 | 业界标准，兼容性好，支持流式 |
| 测试 | 暂时跳过 | 后续按需补充 |

---

## 🔄 数据流概览

```
┌─────────────┐
│   用户输入    │
└──────┬──────┘
       ↓
┌──────────────┐     ┌─────────────┐
│  Agent Loop  │────→│ Skill Loader│（注入 Skills 到 prompt）
│  (src/agent) │     └─────────────┘
└──────┬───────┘
       ↓
┌──────────────┐
│ Context Mgr  │←───→ Memory（JSONL 备份）
│ (src/context)│
└──────┬───────┘
       ↓
┌──────────────┐
│ OpenAI Client│（流式调用 LLM）
│ (src/client) │
└──────┬───────┘
       ↓
  ┌────┴────┐
  │ LLM 响应 │
  └────┬────┘
       ↓
  ┌─────────┐     ┌──────────────┐
  │ 文本回复  │     │  工具调用请求  │
  └────┬────┘     └──────┬───────┘
       ↓                 ↓
  输出给用户        ┌──────────────┐
                   │  工具注册表    │
                   │ (内置 + MCP)  │
                   └──────┬───────┘
                          ↓
                   ┌──────────────┐
                   │  执行工具      │
                   └──────┬───────┘
                          ↓
                   结果追加到 messages
                          ↓
                   回到 Agent Loop
```

---

## 📋 后续参考

- 开发路线图：[docs/roadmap.md](./roadmap.md)
- 工作记录：[docs/work-logs/](./work-logs/)
