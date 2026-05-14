# 第四章：搜索工具 — grep / glob / ls

Agent 在编辑代码之前需要先找到目标。这一章实现三个不同粒度的搜索工具，覆盖"按内容搜"、"按文件名搜"和"看目录结构"三种场景。

## Agent 怎么找代码

编码助手最常见的操作流程是：

```
1. 搜索 → 找到相关文件/位置
2. 读取 → 确认具体内容
3. 编辑 → 修改代码
```

第一步"搜索"需要三个不同粒度的工具：

| 工具 | 输入 | 输出 | 典型用途 |
|---|---|---|---|
| `grep` | 正则表达式 | `文件:行号:内容` | "找到所有调用 `execute` 的地方" |
| `glob` | 文件名模式 | 文件路径列表 | "项目里有哪些 `.py` 文件" |
| `ls` | 目录路径 | 子项列表 | "这个目录下有什么" |

三者互补，工具描述里明确写了"不适用场景"和应该用哪个替代，帮模型选对工具。

## grep — 按内容搜索

### 核心逻辑

```python
def _sync_search(root, regex, include):
    matches = []
    truncated = False

    for file in root.rglob("*"):
        # 跳过 .git / node_modules 等
        if any(p in _SKIP_DIRS for p in file.relative_to(root).parts):
            continue
        if not file.is_file():
            continue
        # 文件名过滤
        if include and not fnmatch(file.name, include):
            continue

        # 跳过二进制
        text = _read_text_if_not_binary(file)
        if text is None:
            continue

        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append(f"{abs_path}:{lineno}:{line}")
                if len(matches) >= 200:
                    truncated = True
                    break
        if truncated:
            break

    return matches, truncated
```

### 设计要点

**1. 纯 Python 实现，不依赖 ripgrep**

用 `Path.rglob` + `re.search` 实现，不需要系统安装 `rg`。代价是对万级文件的大项目比 ripgrep 慢一个数量级，但 `_MAX_RESULTS = 200` 的上限保证了找够就停，实际体验可接受。

**2. 二进制文件检测**

```python
def _read_text_if_not_binary(file: Path) -> str | None:
    raw = file.read_bytes()
    if b"\x00" in raw[:512]:
        return None
    return raw.decode(errors="ignore")
```

检查文件前 512 字节是否包含空字节（`\x00`）。二进制文件（图片、编译产物等）几乎必然包含空字节，文本文件则不会。这是一个经典的启发式判断，和 Git 的做法一样。

**3. 跳过非项目目录**

```python
_SKIP_DIRS = frozenset({
    ".git", "node_modules", ".venv", "__pycache__",
    ".tox", ".mypy_cache", "dist", "build"
})
```

这些目录搜进去只会产生噪音。用 `frozenset` 实现 O(1) 查找。

**4. include 文件名过滤**

```python
if include and not fnmatch(file.name, include, flags=BRACE):
    continue
```

用 `wcmatch` 库支持花括号展开：`*.{js,ts}` 匹配 `.js` 和 `.ts`。标准库的 `fnmatch` 不支持花括号，`wcmatch` 是一个轻量替代。

**5. 输出格式**

```
/abs/path/to/file.py:42:def execute(self, **kwargs):
```

`文件绝对路径:行号:内容`——模型拿到后可以直接用路径传给 `read_file`，用行号定位上下文。绝对路径避免了模型还要猜相对路径的问题。

## glob — 按文件名搜索

```python
def _sync_search(root, pattern):
    full_pattern = str(root / pattern)
    files = []
    for m in wcglob.iglob(full_pattern, flags=BRACE | GLOBSTAR):
        p = Path(m)
        if p.is_file():
            files.append(p)
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return files
```

### 和 grep 的区别

- `grep` 搜的是**文件内容**（"哪些文件里包含 `TODO`"）
- `glob` 搜的是**文件路径**（"哪些文件叫 `test_*.py`"）

### 按修改时间排序

结果按 `st_mtime` 降序——最近修改的文件排最前。这很有用：模型搜 `**/*.py` 时，刚改过的文件往往是最相关的。

### wcmatch 库

标准库的 `glob` 不支持 `**`（Python 3.10 之前）和 `{}`。`wcmatch` 两个都支持，让模型可以写 `src/**/*.{js,ts,tsx}` 这样的模式。

## ls — 列目录

最简单的工具，核心就是 `Path.iterdir()` + 格式化：

```python
def _sync_list(p, ignore_patterns):
    entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
    return [
        _format_entry(e)
        for e in entries
        if not any(fnmatch(e.name, pat) for pat in ignore_patterns)
    ]
```

输出格式：

```
[目录] src/
[目录] tests/
[文件] main.py  (2.3 KB)
[文件] README.md  (1.1 KB)
```

### 排序策略

```python
key=lambda e: (e.is_file(), e.name.lower())
```

`(e.is_file(), name)` 作为排序 key——`is_file()` 返回 `False`（目录）排在 `True`（文件）前面，同类内按名称字母序。**目录优先**是因为模型通常先关心目录结构。

### ignore 参数

```python
ignore: list[str] | None  # 如 ["*.pyc", "__pycache__", ".git"]
```

让模型可以排除不想看的内容。和 grep 的 `_SKIP_DIRS` 不同，ls 的 ignore 是由模型主动传入的——因为 ls 只看一层，噪音没那么多，不需要硬编码过滤。

## 三个工具的协作

模型在实际使用中经常组合这三个工具：

```
用户：帮我找到项目里所有处理用户认证的代码

Agent 思考后：
  1. ls /project → 了解项目结构
  2. glob **/*.py /project → 找到所有 Python 文件
  3. grep "auth|login|session" /project --include "*.py" → 搜索相关代码
  4. read_file /project/src/auth.py → 读取具体文件
```

这就是"先搜后读"工作流。system prompt 里也写了这个顺序：
> 用 `grep` / `glob` / `ls` 定位相关文件和上下文 → 用 `read_file` 阅读目标文件 → 确认方案后编辑

## 共同模式

三个搜索工具共享的设计原则：

| 模式 | 说明 |
|---|---|
| 只读无副作用 | 搜索不修改任何东西，模型可以放心多次调用 |
| `asyncio.to_thread` | 文件遍历是阻塞 IO，扔到线程池 |
| 结果上限 | grep 200 条、glob 200 条，防止输出爆 token |
| 绝对路径 | 输出全用绝对路径，模型直接传给下一个工具 |
| 错误不抛异常 | 路径不存在、正则无效等都返回 `ToolResult(is_error=True)` |

## 小结

| 工具 | 搜什么 | 关键技术 |
|---|---|---|
| `grep` | 文件内容 | `rglob` + `re` + 二进制检测 + 目录跳过 |
| `glob` | 文件路径 | `wcmatch` 花括号/`**` + 按修改时间排序 |
| `ls` | 目录子项 | `iterdir` + 目录优先排序 + ignore 过滤 |

