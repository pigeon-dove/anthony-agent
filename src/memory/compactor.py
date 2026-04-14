"""上下文压缩 — 两层策略

Layer 1 (micro_compact): 每次 LLM 调用前，将 3 轮之前的工具输出替换为占位符。
Layer 2 (auto_compact): token 超阈值时，用 LLM 将旧对话压缩为更短的多轮对话。
"""

from __future__ import annotations

import copy
import json
import logging
import re
from functools import cache
from typing import TYPE_CHECKING

import tiktoken
from pydantic import BaseModel

from config import app_config
from src.prompts import SUMMARY_USER_PROMPT

if TYPE_CHECKING:
    from src.client import OpenAIClient
    from src.memory.session import SessionManager

logger = logging.getLogger(__name__)

_COMPACT_PREFIX = "[已压缩]"
_KEEP_TURNS = 3

# 这些工具的输出不压缩（输出短或包含关键操作确认）
_SKIP_COMPACT_TOOLS: set[str] = {"write_file", "edit_file", "multi_edit"}

# 这些工具的调用和输出在压缩时直接丢弃（不含外部信息，保留无意义）
_ALWAYS_DISCARD_TOOLS: set[str] = {"think"}

# 分隔符，用于解析 LLM 输出的压缩对话
_SEP_USER = "---USER---"
_SEP_ASSISTANT = "---ASSISTANT---"


# ── Token 计算 ────────────────────────────────────────────────


@cache
def _get_encoder() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")


def estimate_tokens(messages: list[dict]) -> int:
    enc = _get_encoder()
    return sum(4 + len(enc.encode(json.dumps(m, ensure_ascii=False))) for m in messages)


def _calc_total_tokens(messages: list[dict], system_prompt: str) -> int:
    return len(_get_encoder().encode(system_prompt)) + 4 + estimate_tokens(messages)


# ── Layer 1: micro_compact ────────────────────────────────────


def micro_compact(messages: list[dict]) -> None:
    """原地压缩 3 轮之前的工具返回值。"""
    if not messages:
        return
    boundary = _find_keep_boundary(messages, _KEEP_TURNS)
    if boundary > 0:
        _replace_tool_outputs(messages[:boundary])


# ── Layer 2: auto_compact ─────────────────────────────────────


class CompactCheck(BaseModel):
    current_tokens: int
    threshold_tokens: int


class CompactResult(BaseModel):
    before_tokens: int
    after_tokens: int
    threshold_tokens: int


def check_compact(messages: list[dict], system_prompt: str) -> CompactCheck | None:
    """超阈值则返回 CompactCheck，否则 None。"""
    if not messages:
        return None
    threshold = int(app_config.llm.max_input_tokens * app_config.compact.compact_threshold)
    total = _calc_total_tokens(messages, system_prompt)
    if total <= threshold:
        return None
    return CompactCheck(current_tokens=total, threshold_tokens=threshold)


async def do_compact(
    messages: list[dict],
    system_prompt: str,
    client: "OpenAIClient",
    session_manager: "SessionManager | None",
    check: CompactCheck,
) -> CompactResult:
    """将旧对话压缩为更短的多轮对话，保留 user/assistant 交替结构。

    拆分策略：
    1. 分离最近 _KEEP_TURNS 轮为 recent（完整保留）
    2. 剩余部分交给 LLM 压缩为更短的多轮对话
    3. 重建为：[压缩后的对话] + recent + 当前用户消息

    如果压缩后仍超阈值，agent._try_compact 会循环调用。
    """
    logger.info("auto_compact: %d / %d tokens", check.current_tokens, check.threshold_tokens)

    # 分离最新 user 消息
    last_user = messages.pop() if messages and messages[-1].get("role") == "user" else None

    # 分离最近几轮
    total_turns = _count_turns(messages)
    keep = max(min(total_turns - 1, _KEEP_TURNS), 0)
    to_compress, recent = _split(messages, keep)

    if _count_turns(to_compress) < 1:
        # 不够压，恢复原样
        if last_user:
            messages.append(last_user)
        return CompactResult(
            before_tokens=check.current_tokens,
            after_tokens=check.current_tokens,
            threshold_tokens=check.threshold_tokens,
        )

    logger.info(
        "压缩前 %d 轮，保留最近 %d 轮",
        _count_turns(to_compress), _count_turns(recent),
    )

    # 归档完整历史
    transcript_path = None
    if session_manager:
        transcript_path = session_manager.save_transcript(messages)

    # LLM 压缩为多轮对话
    compressed = await _compress_to_dialogue(to_compress, client)

    # 在压缩对话的第一条 user 消息前面加上标记
    marker_text = "[以下是早期对话的压缩版本]"
    if transcript_path:
        marker_text += f"\n[完整历史已归档到：{transcript_path}]"
    if compressed and compressed[0]["role"] == "user":
        compressed[0]["content"] = marker_text + "\n\n" + compressed[0]["content"]
        compressed[0]["_compact_marker"] = True
    else:
        compressed.insert(0, {"role": "user", "content": marker_text, "_compact_marker": True})

    # 重建 messages
    messages.clear()
    messages.extend(compressed)
    messages.extend(recent)
    if last_user:
        messages.append(last_user)

    # 持久化
    if session_manager:
        session_manager.overwrite_messages(messages)

    after = _calc_total_tokens(messages, system_prompt)
    logger.info("auto_compact: %d → %d tokens", check.current_tokens, after)
    return CompactResult(before_tokens=check.current_tokens, after_tokens=after, threshold_tokens=check.threshold_tokens)


# ── 压缩对话生成 ─────────────────────────────────────────────


async def _compress_to_dialogue(messages: list[dict], client: "OpenAIClient") -> list[dict]:
    """预处理 + LLM 压缩 + 解析，返回压缩后的 messages 列表。"""
    prepared = copy.deepcopy(messages)
    _strip_discardable_tools(prepared)
    _replace_tool_outputs(prepared)
    _truncate_long_arguments(prepared)
    _ensure_assistant_content(prepared)

    resp = await client.chat([
        *prepared,
        {"role": "user", "content": SUMMARY_USER_PROMPT},
    ])

    raw = resp.content or ""
    compressed = _parse_dialogue(raw)
    if not compressed:
        # 解析失败时回退：把 LLM 原始输出当作单条 assistant 摘要
        logger.warning("压缩对话解析失败，回退为单条摘要")
        return [{"role": "assistant", "content": raw, "_compacted": True}]
    return compressed


def _parse_dialogue(text: str) -> list[dict]:
    """解析 LLM 输出的 ---USER--- / ---ASSISTANT--- 格式为 messages 列表。"""
    # 按分隔符切分
    parts = re.split(r"---USER---|---ASSISTANT---", text)
    # 找出每个分隔符的顺序
    seps = re.findall(r"---USER---|---ASSISTANT---", text)

    if not seps:
        return []

    result: list[dict] = []
    for i, sep in enumerate(seps):
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if not content:
            continue
        role = "user" if sep == _SEP_USER else "assistant"
        # 确保 user/assistant 交替
        if result and result[-1]["role"] == role:
            # 同角色连续，合并到上一条
            result[-1]["content"] += "\n" + content
        else:
            result.append({"role": role, "content": content})

    # 验证：必须以 user 开头
    if result and result[0]["role"] != "user":
        result.insert(0, {"role": "user", "content": "[对话起始]"})

    # 验证：必须以 assistant 结尾（否则后续接 recent 时角色可能冲突）
    if result and result[-1]["role"] == "user":
        result.append({"role": "assistant", "content": "[继续]"})

    # 标记为已压缩
    for msg in result:
        msg["_compacted"] = True

    return result


# ── 内部工具函数 ──────────────────────────────────────────────


def _strip_discardable_tools(messages: list[dict]) -> None:
    """从消息列表中移除 _ALWAYS_DISCARD_TOOLS 的 tool_call 和对应的 tool 消息（原地修改）。

    用于摘要生成前的预处理，避免 think 等无信息量的工具调用浪费摘要 token。
    """
    tc_map = _build_tc_map(messages)
    discard_ids: set[str] = set()

    # 收集需要丢弃的 tool_call_id
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls", []):
            name = tc.get("function", {}).get("name", "")
            if name in _ALWAYS_DISCARD_TOOLS and tc.get("id"):
                discard_ids.add(tc["id"])

    if not discard_ids:
        return

    # 从 assistant 消息中移除对应的 tool_call 条目
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            msg["tool_calls"] = [
                tc for tc in msg["tool_calls"]
                if tc.get("id") not in discard_ids
            ]
            # 如果 tool_calls 清空了，移除该键
            if not msg["tool_calls"]:
                del msg["tool_calls"]

    # 移除对应的 tool 消息
    messages[:] = [
        msg for msg in messages
        if not (msg.get("role") == "tool" and msg.get("tool_call_id") in discard_ids)
    ]


def _replace_tool_outputs(messages: list[dict]) -> None:
    """将可压缩工具的输出替换为占位符（原地修改）。

    - think 等 _ALWAYS_DISCARD_TOOLS：内容直接丢弃（通常已被 _strip_discardable_tools 删除）
    - _SKIP_COMPACT_TOOLS（write_file 等）：不压缩，保留原文
    - 其他工具：替换为占位符，保留工具名
    """
    tc_map = _build_tc_map(messages)
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        content = msg.get("content", "")
        if content.startswith(_COMPACT_PREFIX):
            continue
        name = tc_map.get(msg.get("tool_call_id", ""), "unknown")
        if name in _ALWAYS_DISCARD_TOOLS:
            msg["content"] = f"{_COMPACT_PREFIX} 此前调用了 {name}，内容已丢弃"
        elif name not in _SKIP_COMPACT_TOOLS:
            msg["content"] = f"{_COMPACT_PREFIX} 此前调用了工具 {name}，原始输出已省略"


def _truncate_long_arguments(messages: list[dict]) -> None:
    """截断超长的工具调用参数，避免摘要 token 爆炸。"""
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls", []):
            raw = tc.get("function", {}).get("arguments", "")
            if len(raw) <= 2000:
                continue
            try:
                args = json.loads(raw)
                for k, v in args.items():
                    if isinstance(v, str) and len(v) > 500:
                        args[k] = v[:500] + f"\n... [截断，原始 {len(v)} 字符]"
                tc["function"]["arguments"] = json.dumps(args, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                tc["function"]["arguments"] = raw[:2000] + "... [截断]"


def _ensure_assistant_content(messages: list[dict]) -> None:
    """确保 assistant 消息始终有 content 字段（API 要求不能缺失）。"""
    for msg in messages:
        if msg.get("role") == "assistant" and "content" not in msg:
            msg["content"] = ""


def _build_tc_map(messages: list[dict]) -> dict[str, str]:
    """tool_call_id → tool_name 映射。"""
    m: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls", []):
            if tc.get("id"):
                m[tc["id"]] = tc.get("function", {}).get("name", "unknown")
    return m


def _count_turns(messages: list[dict]) -> int:
    return sum(1 for m in messages if m.get("role") == "user")


def _find_keep_boundary(messages: list[dict], keep: int) -> int:
    """从末尾往前找第 keep 个 user 消息的索引。"""
    n = 0
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            n += 1
            if n >= keep:
                return i
    return 0


def _split(messages: list[dict], keep: int) -> tuple[list[dict], list[dict]]:
    """按保留轮次拆分为 (older, recent)。从末尾往前数 keep 轮。"""
    if keep <= 0:
        return messages[:], []
    idx = _find_keep_boundary(messages, keep)
    return (messages[:idx], messages[idx:]) if idx > 0 else (messages[:], [])

