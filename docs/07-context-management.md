# 第七章：上下文管理 — 让长对话不崩溃

LLM 的上下文窗口是有限的，而编码助手的对话膨胀速度极快。这一章实现两层压缩策略，在 token 限制内尽可能保留关键信息。

## 问题

LLM 有上下文窗口限制（如 128K token）。每次 LLM 调用都要把完整对话历史发过去。编码助手的对话特别容易膨胀——一次 `grep` 可能返回几百行、一次 `read_file` 可能几千行、一次 `bash` 的编译输出可能上万字符。

不加控制的话，几轮工具调用就会塞满上下文。

## 两层策略

我们用两层压缩解决这个问题，各自针对不同的膨胀源：

```
Layer 1: micro_compact（每次 LLM 调用前）
  → 3 轮之前的工具输出替换为占位符
  → 立即生效，无 LLM 调用开销

Layer 2: auto_compact（token 超阈值时）
  → 用 LLM 将旧对话压缩为更短的摘要
  → 有损但大幅缩减，需要一次额外 LLM 调用
```

为什么不只用 Layer 2？因为 LLM 压缩有延迟和成本。Layer 1 是零成本的——只是替换字符串，每次调用都跑，把工具输出这个最大的膨胀源控制住，让 Layer 2 不需要频繁触发。

## Layer 1: micro_compact

### 核心逻辑

```python
_KEEP_TURNS = 3

def micro_compact(messages: list[dict]) -> None:
    boundary = _find_keep_boundary(messages, _KEEP_TURNS)
    if boundary > 0:
        older = messages[:boundary]
        _strip_discardable_tools(older)   # 删除 think 等无用调用
        _replace_tool_outputs(older)       # 工具输出替换为占位符
        messages[:boundary] = older
```

找到最近 3 轮之前的边界，对更早的消息做两件事：

### 1. 删除 think 调用

```python
_ALWAYS_DISCARD_TOOLS = {"think"}

def _strip_discardable_tools(messages):
    # 收集 think 的 tool_call_id
    discard_ids = {tc["id"] for msg in messages for tc in msg.get("tool_calls", [])
                   if tc["function"]["name"] in _ALWAYS_DISCARD_TOOLS}
    # 从 assistant 消息中移除对应 tool_call
    # 从消息列表中移除对应 tool message
```

think 工具的内容对后续无价值（结论已在 content 里），3 轮后彻底删除——不是替换为占位符，而是连 tool_call 条目和 tool message 一起丢弃，就像从没调用过一样。

### 2. 替换工具输出

```python
_SKIP_COMPACT_TOOLS = {"write_file", "edit_file", "multi_edit"}

def _replace_tool_outputs(messages):
    for msg in messages:
        call_id = _msg_tool_call_id(msg)
        if not call_id:
            continue
        name = tc_map.get(call_id, "unknown")
        if name in _SKIP_COMPACT_TOOLS:
            continue  # 编辑确认信息保留原文
        msg["content"] = f"[已压缩] 此前调用了工具 {name}（call_id: {call_id}），原始输出已省略"
```

大部分工具输出被替换为一行占位符。但 `write_file`、`edit_file`、`multi_edit` 的输出**不压缩**——它们的返回值很短（如 "已替换 2 处"），且包含关键的操作确认信息，模型需要知道"上次改了什么"。

替换后的消息仍然保留了三个关键信息：
- 调用了什么工具（`name`）
- 工具调用的参数（在 assistant 消息的 `tool_calls` 里，不受影响）
- call_id（可用于从归档中溯源）

### 为什么保留最近 3 轮

最近 3 轮的工具输出不压缩，因为：
- 模型可能正在基于这些输出做决策（"刚才 grep 搜到了什么"）
- think 如果在最近 3 轮内被删，模型看不到自己刚想过什么，会反复重复调用

### 图片消息的处理

`read_file` 读图片时注入的 `user` 消息带有 `_tool_call_id` 标记。`_replace_tool_outputs` 同样处理这类消息：

```python
def _msg_tool_call_id(msg):
    if msg.get("role") == "tool":
        return msg.get("tool_call_id")
    if msg.get("role") == "user" and msg.get("_tool_call_id"):
        return msg["_tool_call_id"]  # 工具注入的图片 user message
    return None
```

3 轮后，base64 编码的图片消息也被替换为占位符，节省大量 token。

## Layer 2: auto_compact

### 触发条件

```python
def check_compact(messages, system_prompt) -> CompactCheck | None:
    threshold = max_input_tokens * 0.8  # 80% 阈值
    total = calc_total_tokens(messages, system_prompt)
    if total <= threshold:
        return None
    return CompactCheck(current_tokens=total, threshold_tokens=threshold)
```

当前 token 数超过上下文窗口的 80% 时触发。留 20% 余量是因为还需要给模型的回复留空间。

### 压缩流程

```
原始 messages:
  [user, assistant, tool, user, assistant, ..., user(最新)]

1. 分离最新 user 消息（pop）
2. 分离最近 3 轮为 recent
3. 剩余部分 → 归档到 Markdown 文件 → 交给 LLM 压缩
4. 重建：[compact_user, compact_assistant(摘要)] + recent + last_user
```

代码：

```python
async def do_compact(messages, system_prompt, client, session_manager, check):
    # 1. 分离
    last_user = messages.pop()
    to_compress, recent = _split(messages, keep=3)

    # 2. 归档
    transcript_path = session_manager.save_transcript(messages)

    # 3. LLM 压缩
    summary_text = await _compress_to_dialogue(to_compress, client)

    # 4. 重建
    messages.clear()
    messages.extend([
        {"role": "user", "content": "上下文即将超限，请压缩摘要..."},
        {"role": "assistant", "content": f"[已将早期对话压缩为摘要]\n\n{summary_text}",
         "_compacted": True},
    ])
    messages.extend(recent)
    messages.append(last_user)
```

### LLM 压缩的预处理

直接把原始消息发给 LLM 压缩，token 可能就超了。所以压缩前做六步预处理：

```python
async def _compress_to_dialogue(messages, client):
    prepared = copy.deepcopy(messages)      # 深拷贝，不影响原始数据
    _strip_discardable_tools(prepared)       # 1. 删除 think 调用
    _replace_tool_outputs(prepared)          # 2. 工具输出替换为占位符
    _truncate_long_arguments(prepared)       # 3. 截断超长工具参数
    _flatten_image_content(prepared)         # 4. 图片 base64 → "[N 张图片]"
    _strip_reasoning_content(prepared)       # 5. 移除 thinking 推理内容
    _ensure_assistant_content(prepared)      # 6. 确保 assistant 有 content

    resp = await client.chat([*prepared, {"role": "user", "content": SUMMARY_PROMPT}])
    return resp.content
```

每一步都在减少发给压缩模型的 token：

| 步骤 | 减少量 | 说明 |
|---|---|---|
| 删除 think | 数百~数千 | think 内容可能很长 |
| 替换工具输出 | 大量 | 一次 grep 结果可能上千 token |
| 截断工具参数 | 可观 | write_file 的 content 参数可能很长 |
| 扁平化图片 | 可观 | 避免 base64 字符串参与 token 编码 |
| 移除 reasoning | 数百~数千 | thinking 模型的推理过程 |
| 确保 content | 0 | 只是修复格式 |

### 压缩摘要的格式

压缩 prompt（`SUMMARY_USER_PROMPT`）要求 LLM 输出 `---user---` / `---assistant---` 交替的多轮对话格式，而不是一段纯文本摘要。这样压缩后的消息仍然保持 user/assistant 交替结构，模型理解起来更自然。

### 归档

压缩前，完整的对话历史会被写入 Markdown 文件：

```
.anthony/sessions/{id}/transcripts/2026-05-12_15-30-00.md
```

压缩摘要的开头标注了归档路径。如果模型后续需要早期细节，可以用 `read_file` / `grep` 在归档文件中查找。

### 循环压缩

```python
async def _try_compact(self):
    for _ in range(3):  # 最多压 3 次
        check = check_compact(self._messages, self._system_prompt)
        if not check:
            return
        await do_compact(...)
```

一次压缩可能不够（如果 recent 部分本身就很大），所以最多循环 3 次。每次压缩后重新检查，直到低于阈值。

## Token 估算

```python
def _estimate_message_tokens(msg, enc):
    content = msg.get("content")
    if isinstance(content, list):
        # 多模态：文本部分正常编码，图片用固定估值 1000
        total = 4
        for part in content:
            if part.get("type") == "text":
                total += len(enc.encode(part["text"]))
            elif part.get("type") == "image_url":
                total += 1000
        return total
    # 普通消息：排除 reasoning_content 后整条 JSON 序列化编码
    stripped = {k: v for k, v in msg.items() if k != "reasoning_content"}
    return 4 + len(enc.encode(json.dumps(stripped, ensure_ascii=False)))
```

三个要点：
- **图片用固定值 1000**：OpenAI 按图片分辨率计算 token（low detail 固定 85，high detail 随尺寸增长），不能对 base64 字符串做 `enc.encode()`（那不是 API 的计费方式），1000 是保守折中估值
- **排除 reasoning_content**：thinking 内容不回传 API（loop 结束后清除），不计入 token
- **+4 是消息框架开销**：每条消息有 `<|im_start|>role\n...content...<|im_end|>` 的固定开销

## 压缩后的上下文结构

```
[compact_user]       "上下文即将超限，请压缩..."
[compact_assistant]  "[已将早期对话压缩为摘要，归档到：/path]\n\n(摘要内容)"
[recent user]        (最近第 3 轮用户消息)
[recent assistant]   (最近第 3 轮助手消息)
[recent tool]        (工具结果)
...                  (最近 2-3 轮完整对话)
[current user]       (当前用户输入)
```

模型看到这个结构后：
- 知道早期对话被压缩了
- 从摘要中了解之前做了什么
- 最近几轮完整保留，可以无缝继续工作
- 需要早期细节时可以查归档文件

## 小结

| 层 | 触发时机 | 做什么 | 成本 |
|---|---|---|---|
| **micro_compact** | 每次 LLM 调用前 | 3 轮前的工具输出 → 占位符，think → 删除 | 零（纯字符串操作） |
| **auto_compact** | token 超 80% 阈值 | 预处理 + LLM 压缩为摘要 + 归档 | 一次 LLM 调用 |

关键设计决策：

| 决策 | 原因 |
|---|---|
| 保留最近 3 轮 | 模型需要最近的工具输出来继续工作 |
| 编辑工具输出不压缩 | 操作确认信息短且关键 |
| think 彻底删除 | 结论在 content 里，think 本身无后续价值 |
| 图片固定估值 | 不能对 base64 做 token 编码 |
| 归档到 Markdown | 有损压缩的安全网，可溯源 |
| reasoning_content 不计入 | loop 结束后清除，不占 API 传输 |

