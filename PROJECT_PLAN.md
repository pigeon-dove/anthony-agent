# 类Claude Code Agent项目开发规划

## 项目概述

开发一个功能完整的类Claude Code Agent，具备自主决策、工具调用、子代理管理等核心能力，作为教学类项目上传到GitHub。

## 核心功能需求

### 1. 基础Agent Loop
- 消息处理循环
- 状态管理
- 决策流程
- 响应生成

### 2. 基础Tool Use能力
- 工具注册与发现
- 工具调用执行
- 工具结果处理
- 工具参数验证

### 3. 基础Sub Agent能力
- 子代理创建与管理
- 任务分发与协调
- 结果聚合
- 错误处理

### 4. 基础Skill Loading能力
- 技能模块化设计
- 动态加载机制
- 技能依赖管理
- 技能版本控制

### 5. 基础Context Compact能力
- 上下文压缩算法
- 记忆管理
- 会话状态保持
- 历史记录优化

### 6. 基础Task System能力
- 任务定义与解析
- 任务执行流程
- 任务状态跟踪
- 任务结果处理

## 工具系统实现

### 📁 文件操作类
- **Read**: 读取文件内容（支持指定行范围）
- **Write**: 创建/覆盖写入文件
- **Edit**: 精准编辑文件的特定部分（搜索替换模式）
- **MultiEdit**: 对同一文件进行多处编辑

### 💻 命令执行类
- **Bash**: 执行 shell 命令（ls, grep, git, npm 等）
- **Background Bash**: 后台运行长时间命令（如 dev server）

### 🔍 搜索类
- **Glob**: 按文件名模式查找文件
- **Grep**: 按内容搜索文件（基于 ripgrep）

### 🌐 其他
- **WebFetch**: 获取网页/URL 内容

## 高级功能需求

### 1. MCP接入
- MCP服务器连接
- 工具发现与注册
- 协议兼容性

### 2. OpenAI封装
- 流式响应支持
- 错误处理机制
- 配置管理

### 3. 历史记忆系统
- JSONL格式存储
- 会话上下文备份
- 摘要上下文压缩
- 记忆恢复机制

## 技术栈选择

### 核心语言
- **Python 3.8+**: 主要开发语言

### 核心依赖
- **OpenAI SDK**: LLM接口封装
- **Pydantic**: 数据验证和序列化
- **FastAPI**: Web接口（可选）
- **SQLAlchemy**: 数据库操作（可选）

### 工具依赖
- **requests**: HTTP请求
- **aiofiles**: 异步文件操作
- **subprocess**: 命令执行
- **glob/re**: 文件搜索

## 项目目录结构设计

```
anthony-agent/
├── docs/                    # 文档目录
│   ├── design/              # 设计文档
│   ├── api/                 # API文档
│   └── tutorials/           # 教程文档
├── src/                     # 源代码目录
│   ├── core/                # 核心模块
│   │   ├── agent.py         # Agent主类
│   │   ├── loop.py          # Agent循环
│   │   └── state.py         # 状态管理
│   ├── tools/               # 工具系统
│   │   ├── base.py          # 工具基类
│   │   ├── file_ops.py      # 文件操作工具
│   │   ├── command.py       # 命令执行工具
│   │   └── search.py        # 搜索工具
│   ├── agents/              # 子代理系统
│   │   ├── manager.py       # 代理管理器
│   │   ├── base.py          # 代理基类
│   │   └── specialized/     # 专用代理
│   ├── skills/              # 技能系统
│   │   ├── loader.py        # 技能加载器
│   │   ├── registry.py      # 技能注册表
│   │   └── builtin/         # 内置技能
│   ├── context/             # 上下文管理
│   │   ├── compact.py       # 上下文压缩
│   │   ├── memory.py        # 记忆管理
│   │   └── storage.py       # 存储系统
│   ├── tasks/               # 任务系统
│   │   ├── system.py        # 任务管理器
│   │   ├── parser.py        # 任务解析器
│   │   └── executor.py      # 任务执行器
│   ├── mcp/                 # MCP集成
│   │   ├── client.py        # MCP客户端
│   │   ├── server.py        # MCP服务器（可选）
│   │   └── tools.py         # MCP工具集成
│   └── utils/               # 工具函数
│       ├── openai_wrapper.py # OpenAI封装
│       ├── config.py        # 配置管理
│       └── logger.py        # 日志系统
├── tests/                   # 测试目录
│   ├── unit/                # 单元测试
│   ├── integration/         # 集成测试
│   └── fixtures/            # 测试数据
├── data/                    # 数据目录
│   ├── memory/              # 记忆存储
│   │   ├── sessions/        # 会话上下文
│   │   └── summaries/       # 摘要上下文
│   └── skills/              # 技能数据
├── config/                  # 配置文件
│   ├── default.yaml         # 默认配置
│   └── development.yaml     # 开发配置
├── scripts/                 # 脚本目录
│   ├── setup.py             # 安装脚本
│   ├── deploy.py            # 部署脚本
│   └── examples/            # 示例脚本
└── requirements/            # 依赖管理
    ├── base.txt             # 基础依赖
    ├── dev.txt              # 开发依赖
    └── prod.txt             # 生产依赖
```

## 开发阶段规划

### 第一阶段：基础框架（1-2周）
- 项目结构搭建
- 核心Agent类实现
- 基础工具系统
- 配置管理系统

### 第二阶段：核心功能（2-3周）
- Agent Loop实现
- 工具调用机制
- 子代理系统
- 技能加载机制

### 第三阶段：高级功能（2-3周）
- 上下文压缩
- 任务系统
- MCP集成
- 记忆管理系统

### 第四阶段：优化完善（1-2周）
- 性能优化
- 错误处理
- 文档编写
- 测试覆盖

## 教学价值点

1. **架构设计**: 展示如何设计可扩展的AI Agent系统
2. **模块化**: 演示功能模块的解耦和组合
3. **工具集成**: 展示外部工具的无缝集成
4. **状态管理**: 复杂的会话状态处理
5. **错误恢复**: 健壮的错误处理机制

## 下一步行动

1. 创建项目目录结构
2. 设置开发环境
3. 实现基础Agent框架
4. 逐步添加各个功能模块

---

*最后更新: 2026-03-16*