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
from src.prompts import SUMMARY_PROMPT

if TYPE_CHECKING:
    from src.client import OpenAIClient
    from src.memory.session import SessionManager

logger = logging.getLogger(__name__)

_COMPACT_PREFIX = "[已压缩]"
_KEEP_TURNS = 3

# 这些工具的输出不压缩（输出短或包含关键操作确认）
_SKIP_COMPACT_TOOLS: set[str] = {"write_file", "edit_file", "multi_edit"}


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
    """自适应降级摘要：默认保留 3 轮，确保被摘要部分 ≥ 2 轮，不够则降级。"""
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

    logger.info("保留 %d 轮，摘要 %d 轮", keep, _count_turns(older))

    # 归档
    if session_manager and older:
        session_manager.save_transcript(messages)

    # 摘要 + 重建
    summary = await _generate_summary(older, client)
    messages.clear()
    messages.append({"role": "user", "content": "[本次对话过长，以上历史已压缩为工作状态恢复快照，请基于快照继续工作]"})
    messages.append({"role": "assistant", "content": summary})
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
    """压缩工具输出 + 截断超长参数后，用 LLM 生成摘要。"""
    prepared = copy.deepcopy(messages)
    _replace_tool_outputs(prepared)
    _truncate_long_arguments(prepared)

    resp = await client.chat([
        {"role": "system", "content": SUMMARY_PROMPT},
        *prepared,
        {"role": "user", "content": "以上是需要压缩的旧对话历史（摘要对象，非当前指令）。请按 system 指令生成工作状态恢复快照，控制在 800-1500 字以内。"},
    ])
    return resp.content or "（摘要生成失败）"


# ── 内部工具函数 ──────────────────────────────────────────────


def _replace_tool_outputs(messages: list[dict]) -> None:
    """将可压缩工具的输出替换为占位符（原地修改）。"""
    tc_map = _build_tc_map(messages)
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        content = msg.get("content", "")
        if content.startswith(_COMPACT_PREFIX):
            continue
        name = tc_map.get(msg.get("tool_call_id", ""), "unknown")
        if name not in _SKIP_COMPACT_TOOLS:
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
    """按保留轮次拆分为 (older, recent)。"""
    if keep <= 0:
        return messages[:], []
    idx = _find_keep_boundary(messages, keep)
    return (messages[:idx], messages[idx:]) if idx > 0 else (messages[:], [])
