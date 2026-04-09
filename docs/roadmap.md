# Anthony Agent — Roadmap

## 已完成 ✅

### 基础架构
- [x] 项目初始化、配置系统（Pydantic BaseModel）
- [x] OpenAI 兼容客户端（流式 + 非流式）
- [x] 事件驱动的 Agent Loop（ReAct 循环）
- [x] 流式输出解析（StreamParser）
- [x] TUI 界面（Textual）

### 内置工具
- [x] `read_file` / `write_file` — 文件读写
- [x] `edit_file` / `multi_edit` — 文件编辑
- [x] `bash` / `bash_background` — 命令执行
- [x] `ls` / `glob` / `grep` — 文件系统查询

### 上下文管理
- [x] 会话持久化（SessionManager）
- [x] Layer 1: micro_compact — 零 LLM 开销的工具输出压缩
- [x] Layer 2: auto_compact — LLM 摘要压缩
- [x] 豁免名单机制（写入类工具不压缩，新工具默认压缩）
- [x] 压缩后保留最近 3 轮完整对话
- [x] 轮次不足时降级策略

---

## 进行中 🚧

### 工具体系增强
- [ ] 工具参数校验与错误提示优化
- [ ] 工具执行超时控制

### UI 体验
- [ ] 工具调用过程的实时展示优化
- [ ] 错误信息的友好展示

---

## 计划中 📋

### MCP 支持
- [ ] MCP 协议客户端接入
- [ ] MCP 工具动态注册与发现
- [ ] MCP 工具与内置工具统一调度

### 多模型支持
- [ ] 模型切换能力
- [ ] 不同模型的参数适配

### 高级上下文管理
- [ ] 对话分支 / 回溯
- [ ] 跨会话记忆

### 安全与权限
- [ ] 危险命令确认机制
- [ ] 文件操作沙箱
