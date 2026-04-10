"""上下文压缩 — 两层策略

Layer 1 (micro_compact): 每次 LLM 调用前，将 3 轮之前的工具输出替换为占位符。
Layer 2 (auto_compact): token 超阈值时，自适应降级保留轮次，用 LLM 摘要旧对话。
"""

from __future__ import annotations

import copy
import json
import logging
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
    """渐进式压缩：只摘要前半段对话，后半段保留原文。

    拆分策略：
    1. 先分离最近 _KEEP_TURNS 轮为 recent（完整保留）
    2. 剩余的 older 部分按轮次对半拆为 to_summarize + to_keep
    3. 只对 to_summarize 生成摘要，to_keep 保留原始消息
    4. 重建为：[摘要] + to_keep + recent + 当前用户消息

    如果多次压缩仍超阈值，agent._try_compact 会循环调用，每次再压掉一半，渐进衰减。
    """
    logger.info("auto_compact: %d / %d tokens", check.current_tokens, check.threshold_tokens)

    # 分离最新 user 消息
    last_user = messages.pop() if messages and messages[-1].get("role") == "user" else None

    # 自适应选择保留轮次：确保 older ≥ 2 轮，不够就降级
    total_turns = _count_turns(messages)
    keep = max(min(total_turns - 1, _KEEP_TURNS), 0)
    older, recent = _split(messages, keep)
    while _count_turns(older) < 2 and keep > 0:
        keep -= 1
        older, recent = _split(messages, keep)

    # 将 older 对半拆分：前半摘要，后半保留
    older_turns = _count_turns(older)
    half = max(older_turns // 2, 1)  # 至少摘要 1 轮
    to_summarize, to_keep = _split_front(older, half)

    logger.info(
        "摘要前 %d 轮，保留中间 %d 轮，保留最近 %d 轮",
        _count_turns(to_summarize), _count_turns(to_keep), _count_turns(recent),
    )

    # 归档（压缩前保存完整历史）
    transcript_path = None
    if session_manager and to_summarize:
        transcript_path = session_manager.save_transcript(messages)

    # 摘要 + 重建
    summary = await _generate_summary(to_summarize, client)
    prefix = "[以下是之前对话的压缩摘要]"
    if transcript_path:
        prefix += f"\n[完整历史已归档到：{transcript_path}]"
    messages.clear()
    messages.append({"role": "assistant", "content": f"{prefix}\n\n{summary}", "_compacted": True})
    messages.extend(to_keep)
    messages.extend(recent)
    if last_user:
        messages.append(last_user)

    # 持久化
    if session_manager:
        session_manager.overwrite_messages(messages)

    after = _calc_total_tokens(messages, system_prompt)
    logger.info("auto_compact: %d → %d tokens", check.current_tokens, after)
    return CompactResult(before_tokens=check.current_tokens, after_tokens=after, threshold_tokens=check.threshold_tokens)


# ── 摘要生成 ──────────────────────────────────────────────────


async def _generate_summary(messages: list[dict], client: "OpenAIClient") -> str:
    """压缩工具输出 + 截断超长参数 + 移除 think 工具后，用 LLM 生成摘要。

    结构：直接把待压缩的历史消息放前面，最后追加一条 user message 描述压缩任务。
    不使用 system prompt，避免 LLM 被历史中的指令性内容干扰。
    """
    prepared = copy.deepcopy(messages)
    _strip_discardable_tools(prepared)
    _replace_tool_outputs(prepared)
    _truncate_long_arguments(prepared)
    # 确保 assistant 消息的 content 不为缺失（API 要求必须存在）
    _ensure_assistant_content(prepared)

    resp = await client.chat([
        *prepared,
        {"role": "user", "content": SUMMARY_USER_PROMPT},
    ])
    return resp.content or "（摘要生成失败）"


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


def _split_front(messages: list[dict], front_turns: int) -> tuple[list[dict], list[dict]]:
    """从前面取 front_turns 轮，返回 (front, rest)。

    按 user 消息计数轮次，在第 front_turns 个 user 消息所属轮次结束后切分。
    """
    if front_turns <= 0:
        return [], messages[:]
    n = 0
    cut = len(messages)  # 默认全部归 front
    for i, msg in enumerate(messages):
        if msg.get("role") == "user":
            n += 1
            if n > front_turns:
                cut = i
                break
    return messages[:cut], messages[cut:]
