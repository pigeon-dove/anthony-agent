# Anthony Agent - 开发路线图

> 按模块拆分的开发计划，从基础到高级逐步实现。

---

## 🎯 总体目标

从零构建一个类 Claude Code 的 AI Agent，涵盖：Agent Loop、Tool Use、Sub Agent、Skill Loading、Context Compact、Task System、MCP 集成。

---

## Phase 1：项目基础搭建 🏗️

- [x] 项目初始化 & 目录结构创建
- [x] 架构设计文档编写
- [x] 基础配置文件（`config/settings.py`、`.env.example`）
- [x] `requirements.txt` 依赖管理
- [ ] JSONL 存储工具类（`src/memory/storage.py`）

**产出：** 项目骨架就绪，基础工具类可用。

---

## Phase 2：OpenAI 客户端封装 🔌

- [x] `src/client/openai_client.py` 实现
  - [x] 基础的 Chat Completion 调用
  - [x] 流式（streaming）返回支持
  - [x] 工具调用（function calling / tool_use）支持
  - [x] 错误处理与重试机制
- [x] API Key 管理（从 `.env` 读取）

**产出：** 可独立运行的 LLM 调用层，支持流式输出和工具调用。

---

## Phase 3：工具系统 🔧

- [x] 工具基类设计（`src/tools/base.py`）
  - [x] `BaseTool` 抽象类：definition()、execute()
  - [x] `ToolDefinition` / `ToolResult` 数据模型（Pydantic BaseModel）
- [x] 工具注册中心（`src/tools/registry.py`）
  - [x] `ToolRegistry`：register / unregister / get / execute
  - [x] `get_definitions()` 导出 OpenAI function calling 格式的 tools 参数
  - [x] 异常捕获与错误返回
- [x] 文件操作工具
  - [x] Read：读取文件内容（支持行范围）
  - [x] Write：创建/覆盖写入文件
  - [x] Edit：搜索替换模式编辑（精确匹配 + 出现次数验证）
  - [x] MultiEdit：同一文件多处编辑（原子性，支持创建新文件）
- [ ] 命令执行工具
  - [x] Bash：执行 shell 命令
  - [ ] BackgroundBash：后台运行长时间命令
- [ ] 搜索工具
  - [ ] Glob：按文件名模式查找
  - [ ] Grep：按内容搜索（基于 ripgrep）
- [ ] 网络工具
  - [ ] WebFetch：获取网页/URL 内容

**产出：** 完整的 9 个工具可用，Agent 可以操作文件、执行命令、搜索、获取网页。

> **进展：** 文件操作工具已全部完成 ✅（Read / Write / Edit / MultiEdit），命令执行、搜索、网络工具待实现。

---

## Phase 4：Agent Loop 核心 🔄

- [x] `src/agent/agent.py` 实现
  - [x] 主循环：用户输入 → LLM 调用 → 工具执行 → 结果返回 → 循环
  - [x] 消息列表（messages）管理
  - [x] 系统提示词加载
  - [x] 流式输出展示（终端渲染）
  - [x] 工具调用的解析与分发
- [x] `src/agent/events.py` 事件流模型
  - [x] 5 种事件：TextDelta / ToolCallStart / ToolCallResult / ResponseComplete / UsageReport
- [x] `main.py` 入口整合
  - [x] CLI 交互界面
  - [x] 对话循环
  - [x] 事件驱动消费 + 彩色终端输出

**产出：** 可在终端中运行的完整 Agent，支持多轮对话和工具调用。✅

---

## Phase 5：上下文管理 & Context Compact 📦

- [ ] `src/context/manager.py` 实现
  - [ ] Messages 列表的增删查管理
  - [ ] Token 计数（tiktoken）
  - [ ] Token 预算阈值管理
- [ ] `src/context/compactor.py` 实现
  - [ ] 上下文压缩策略（调用 LLM 生成摘要）
  - [ ] 压缩触发条件
  - [ ] 压缩前完整上下文的备份（调用 memory 层）

**产出：** Agent 能自动管理上下文长度，在 token 超限时智能压缩。

---

## Phase 6：记忆 & 持久化 💾

- [ ] `src/memory/session.py` 实现
  - [ ] 会话上下文的 JSONL 备份
  - [ ] 会话恢复（从 JSONL 加载）
- [ ] `src/memory/storage.py` 完善
  - [ ] 通用 JSONL 追加写入
  - [ ] JSONL 读取（支持流式）
  - [ ] 摘要上下文的保存
- [ ] `data/` 目录的自动创建

**产出：** 对话历史可持久化，支持上下文备份与恢复。

---

## Phase 7：Task System 📋

- [ ] `src/task/task_manager.py` 实现
  - [ ] 任务数据模型（Task：id、description、status、subtasks）
  - [ ] 任务状态机（pending → running → completed / failed）
  - [ ] 任务的创建、更新、查询
  - [ ] 子任务支持

**产出：** Agent 具备任务管理能力，可以追踪复杂任务的执行进度。

---

## Phase 8：Sub Agent 🤖

- [ ] `src/agent/sub_agent.py` 实现
  - [ ] 子 Agent 创建（独立上下文）
  - [ ] 父子 Agent 通信机制
  - [ ] 子 Agent 的生命周期管理
  - [ ] 子 Agent 结果回传
- [ ] 在主 Agent 中集成 Sub Agent 调用

**产出：** Agent 可以派生子 Agent 处理独立子任务。

---

## Phase 9：Skill Loading 📚

- [ ] `src/skills/loader.py` 实现
  - [ ] 扫描 `skills/` 目录下的 Skill 文件
  - [ ] 解析 Skill 文件（Markdown 格式）
  - [ ] Skill 注册与匹配
- [ ] Skill 注入到 Agent 上下文
- [ ] 示例 Skill 文件（`skills/example_skill.md`）

**产出：** Agent 支持从外部文件加载领域知识/指令集。

---

## Phase 10：MCP 集成 🔗

- [ ] `src/mcp/client.py` 实现
  - [ ] MCP Server 连接（stdio / SSE）
  - [ ] 工具列表获取
  - [ ] 工具调用转发
- [ ] `src/mcp/registry.py` 实现
  - [ ] MCP 工具到内部工具注册表的桥接
  - [ ] 动态工具注册/注销
- [ ] MCP 配置文件支持

**产出：** Agent 可以连接外部 MCP Server，动态扩展工具能力。

---

## Phase 11：打磨 & 教学文档 ✨

- [ ] 错误处理完善
- [ ] 日志系统
- [ ] README.md 编写（项目介绍、快速开始、架构图）
- [ ] 教学文档补充
- [ ] 代码注释完善
- [ ] 示例演示录制（可选）

**产出：** 项目可作为教学材料发布到 GitHub。

---

## 📊 开发优先级

```
Phase 1 → Phase 2 → Phase 3 → Phase 4（核心可运行）
    → Phase 5 → Phase 6（上下文与记忆）
    → Phase 7 → Phase 8（任务与子 Agent）
    → Phase 9 → Phase 10（扩展能力）
    → Phase 11（收尾）
```

> **里程碑**：Phase 4 已完成 ✅ — 现在拥有一个可在终端运行的基础 Agent，支持流式对话和工具调用。
