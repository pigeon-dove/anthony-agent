# 类Claude Code Agent项目

## 项目简介

这是一个教学性质的类Claude Code Agent开发项目，旨在构建一个功能完整的AI代码助手系统。项目展示了如何从零开始构建具备自主决策、工具调用、子代理管理等核心能力的智能Agent。

## 项目目标

- 🎯 **教学价值**: 作为AI Agent开发的完整案例
- 🛠️ **实用功能**: 提供真实的代码助手能力
- 📚 **学习资源**: 包含详细的文档和注释
- 🔧 **可扩展**: 模块化设计，易于功能扩展

## 核心特性

### 基础能力
- ✅ Agent Loop（消息处理循环）
- ✅ Tool Use（工具调用系统）
- ✅ Sub Agent（子代理管理）
- ✅ Skill Loading（技能动态加载）
- ✅ Context Compact（上下文压缩）
- ✅ Task System（任务管理系统）

### 工具系统
- 📁 文件操作类工具
- 💻 命令执行类工具
- 🔍 搜索类工具
- 🌐 网络工具

### 高级功能
- 🔌 MCP协议集成
- 📊 流式响应支持
- 💾 历史记忆管理
- ⚙️ 配置管理系统

## 快速开始

### 环境要求
- Python 3.8+
- OpenAI API密钥
- 基础开发环境

### 安装步骤
```bash
# 克隆项目
git clone <repository-url>
cd anthony-agent

# 安装依赖
pip install -r requirements/base.txt

# 配置环境变量
cp config/default.yaml config/local.yaml
# 编辑local.yaml配置API密钥等

# 运行示例
python scripts/examples/basic_agent.py
```

## 项目结构

```
anthony-agent/
├── docs/           # 项目文档
├── src/            # 源代码
├── tests/          # 测试代码
├── data/           # 数据文件
├── config/         # 配置文件
├── scripts/        # 实用脚本
└── requirements/  # 依赖管理
```

## 文档目录

- [设计文档](design/) - 架构设计和实现原理
- [API文档](api/) - 接口说明和使用示例
- [教程文档](tutorials/) - 逐步学习指南
- [开发指南](development/) - 贡献和扩展指南

## 贡献指南

欢迎贡献代码和文档！请参考：
- [贡献规范](CONTRIBUTING.md)
- [代码风格](STYLE_GUIDE.md)
- [测试指南](TESTING.md)

## 许可证

本项目采用MIT许可证，详见[LICENSE](../LICENSE)文件。

---

*开始你的AI Agent开发之旅！*