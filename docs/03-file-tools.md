# 第三章：文件工具 — read / write / edit / multi_edit

编码助手最高频的操作就是读写文件。这一章实现四个文件工具，每个职责单一，模型不容易用错。

## 概览

文件操作是编码助手的最高频场景。我们需要四个工具：

| 工具 | 职责 | 类比 |
|---|---|---|
| `read_file` | 读取文件内容 | `cat -n` |
| `write_file` | 创建或覆写文件 | 重定向 `>` |
| `edit_file` | 搜索替换单处 | `sed` |
| `multi_edit` | 搜索替换多处（原子） | 带事务的 `sed` |

为什么不只用一个"文件操作"工具？因为模型调用工具时需要填参数，职责越单一，参数越简单，模型越不容易犯错。`write_file` 覆写整个文件和 `edit_file` 局部替换是完全不同的意图，分开后模型更容易选对。

## read_file — 带行号的文件读取

### 核心逻辑

```python
async def execute(self, path: str, offset: int | None = None, limit: int | None = None) -> ToolResult:
    p = Path(path).resolve()
    if not p.exists():
        return ToolResult(content=f"文件不存在: {path}", is_error=True)

    # 图片走特殊路径
    if is_image_file(p):
        return ToolResult(
            content=f"已读取图片: {p}",
            images=[str(p)],  # ToolResult.to_messages() 会自动注入图片
        )

    start = (offset - 1) if offset and offset > 0 else 0
    count = limit if limit and limit > 0 else 2000

    lines, total = await asyncio.to_thread(_read_lines, p, start, count)
    return ToolResult(content=_format_output(lines, start, total))
```

### 设计要点

**1. 带行号输出**

输出格式是 `行号\t内容`，类似 `cat -n`：

```
     1	import asyncio
     2	from pathlib import Path
     3
     4	def main():
     5	    print("hello")
```

行号的作用：模型在后续调用 `edit_file` 时，能准确定位要修改的位置。行号前缀不属于文件内容——这一点在工具描述里明确告诉模型，避免它把行号也写进 `old_string`。

**2. 流式逐行读取**

```python
def _read_lines(p: Path, start: int, count: int) -> tuple[list[str], int]:
    selected: list[str] = []
    total = 0
    with p.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            if total >= start and len(selected) < count:
                selected.append(line.rstrip("\n"))
            total += 1
    return selected, total
```

不用 `f.readlines()` 一次性加载整个文件，而是逐行读取只保留需要的行。对于 GB 级日志文件，不会撑爆内存。

**3. 三层防护**

大文件输出给模型会浪费 token，所以有三层限制：

| 限制 | 值 | 作用 |
|---|---|---|
| `_MAX_LINES` | 2000 | 默认最多读取行数 |
| `_MAX_LINE_CHARS` | 2000 | 单行超长截断（minified JS 等） |
| `_MAX_OUTPUT` | 60,000 | 总输出字符上限 |

超出时在末尾附上提示 `(显示第 1-1500 行，共 8000 行，剩余 6500 行未显示)`，模型看到后知道该用 `offset/limit` 分段读。

**4. 图片文件处理**

读取图片时不尝试按文本读取，而是返回 `images=[path]`。回顾上一章 `ToolResult.to_messages()` 的设计——它会额外生成一条带图片的 `user` 消息注入对话，模型下一轮就能"看到"图片。

**5. IO 走线程池**

```python
lines, total = await asyncio.to_thread(_read_lines, p, start, count)
```

文件 IO 是阻塞操作，`asyncio.to_thread` 把它扔到线程池，不阻塞事件循环。所有文件工具都遵循这个模式。

## write_file — 创建或覆写

最简单的工具，核心就几行：

```python
async def execute(self, path: str, content: str) -> ToolResult:
    p = Path(path).resolve()
    existed = p.is_file()
    await asyncio.to_thread(lambda: p.parent.mkdir(parents=True, exist_ok=True))
    await asyncio.to_thread(p.write_text, content, encoding="utf-8")
    action = "已覆写" if existed else "已创建"
    return ToolResult(content=f"{action} {path}（{len(content)} 字符）")
```

两个细节：
- **自动创建父目录**：`mkdir(parents=True)` 保证 `write_file("/a/b/c/new.py", ...)` 不会因为目录不存在而失败
- **返回字符数**：模型能确认写入量是否符合预期

## edit_file — 精确搜索替换

### 核心逻辑

```python
async def execute(self, path: str, old_string: str, new_string: str,
                  expected_replacements: int = 1) -> ToolResult:
    content = await asyncio.to_thread(p.read_text, encoding="utf-8")

    # 校验匹配次数
    count = content.count(old_string)
    if count == 0:
        return ToolResult(content="old_string 在文件中未找到匹配", is_error=True)
    if count != expected_replacements:
        return ToolResult(
            content=f"预期替换 {expected_replacements} 处，但找到 {count} 处匹配",
            is_error=True,
        )

    new_content = content.replace(old_string, new_string)
    await asyncio.to_thread(p.write_text, new_content, encoding="utf-8")
    return ToolResult(content=f"已替换 {count} 处（{path}）")
```

### expected_replacements 的作用

这是一个安全机制。模型可能写出一个过于宽泛的 `old_string`（比如 `"    return"`），在文件中匹配到多处。不加校验的话 `str.replace` 会把所有匹配都替换掉，造成意外修改。

`expected_replacements` 默认为 1，强制模型提供足够具体的 `old_string` 来唯一匹配。如果模型确实想批量替换，可以显式传入预期数量。

### 为什么用字符串匹配而不是正则或行号？

- **行号不可靠**：模型的行号认知可能因为上下文压缩、多次编辑后偏移
- **正则太危险**：模型生成的正则可能有转义问题，匹配到意料之外的内容
- **精确字符串最安全**：只要 `old_string` 写对了，匹配就一定是对的

代价是模型需要精确复制原文（包括空白和缩进），这对现代 LLM 来说不是问题。

## multi_edit — 原子性多处编辑

### 为什么需要 multi_edit

模型经常需要在同一文件中改多处。如果用多次 `edit_file`：
- 第一次修改可能影响后续匹配的位置
- 中间一次失败，文件处于半修改状态

`multi_edit` 解决这两个问题：
1. 编辑按顺序应用，每次基于前一次的结果——不会因为行号偏移而出错
2. 任一编辑失败整体回滚——文件要么全改，要么不动

### 核心逻辑

```python
async def execute(self, path: str, edits: list[dict]) -> ToolResult:
    # 读取原文
    content = await asyncio.to_thread(p.read_text, encoding="utf-8")

    # 在内存中依次应用
    for i, edit in enumerate(edits, start=1):
        old, new = edit["old_string"], edit["new_string"]
        expected = edit.get("expected_replacements", 1)

        if old == "":
            content += new  # 追加模式
            continue

        count = content.count(old)
        if count != expected:
            return ToolResult(content=f"编辑 #{i}: ...", is_error=True)
            # ↑ 失败直接返回，content 没有被写回文件

        content = content.replace(old, new)

    # 全部通过才写回
    await asyncio.to_thread(p.write_text, content, encoding="utf-8")
```

原子性的实现非常简单：所有编辑都在内存中的 `content` 字符串上操作，只有全部成功后才写回文件。任何一步失败，直接 return error，文件不受影响。

### 创建新文件的技巧

`multi_edit` 还能创建新文件——第一个编辑的 `old_string` 设为空字符串：

```python
if edits[0].get("old_string", "") == "":
    content = ""  # 从空字符串开始
```

然后 `old_string == ""` 时走追加模式（`content += new`），相当于从无到有写入内容。这个设计让模型不需要在 `write_file` 和 `multi_edit` 之间纠结选择。

## 小结

| 工具 | 关键设计 |
|---|---|
| `read_file` | 带行号输出 + 三层截断 + 图片自动注入 + 流式逐行读取 |
| `write_file` | 自动建目录 + 返回字符数确认 |
| `edit_file` | 精确字符串匹配 + `expected_replacements` 安全校验 |
| `multi_edit` | 内存中顺序应用 + 失败整体回滚 + 空字符串追加/创建 |

共同模式：
- 所有 IO 走 `asyncio.to_thread`
- 错误返回 `ToolResult(is_error=True)`，不抛异常
- 返回信息简洁但够用（让模型确认操作结果）

