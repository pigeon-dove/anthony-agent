"""Textual TUI 样式定义"""

APP_CSS = """\
/* 整体布局：消息区占满，输入框固定在底部 */
#message-area {
    height: 1fr;
    scrollbar-size: 1 1;
}

#bottom-bar {
    dock: bottom;
    height: auto;
    max-height: 10;
}

#input-box {
    height: auto;
    min-height: 1;
    max-height: 8;
    margin: 0 0;
}

/* 用户消息 */
.user-msg {
    color: $accent;
    margin: 0 0;
    padding: 0 1;
}

/* 工具调用信息（兜底独立渲染） */
.tool-info {
    color: $success;
    margin: 0 0;
    padding: 0 1;
}

/* 工具调用卡片（覆盖 Collapsible 默认样式） */
.tool-card {
    margin: 1 0 0 0;
    padding: 0 0 0 1;
    border-top: none;
    padding-bottom: 0;
    background: $surface;
}

.tool-card-args {
    margin: 0 0 0 1;
    padding: 0 1;
    color: $text-muted;
}

.tool-card-result {
    margin: 0 0 0 1;
    padding: 0 1;
}

/* 工具参数流式输出（卡片内部） */
.tool-stream-inner {
    color: $secondary;
    margin: 0 0 0 1;
    padding: 0 1;
}

/* task 子 Agent 进度窗口（卡片内部，固定高度滚动） */
.task-progress-window {
    color: $text-muted;
    margin: 0 0 0 1;
    padding: 0 1;
    height: auto;
    max-height: 13;
    background: $surface-darken-1;
    border: round $primary-darken-2;
}

/* 状态信息（usage / compact） */
.status-info {
    color: $text-muted;
    margin: 0 0;
    padding: 0 1;
}

/* LLM Markdown 回复 */
.llm-markdown {
    margin: 1 0 0 0;
    padding: 0 1;
}

/* 历史消息恢复提示 */
.history-hint {
    color: $text-muted;
    margin: 0 0;
    padding: 0 1;
    text-style: italic;
}

/* 历史消息分隔线 */
.history-separator {
    color: $text-muted;
    margin: 1 0;
    padding: 0 1;
    text-align: center;
}
"""
