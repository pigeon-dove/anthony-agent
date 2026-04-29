"""上下文压缩 — 两层策略

Layer 1 (micro_compact): 每次 LLM 调用前，将 3 轮之前的工具输出替换为占位符。
Layer 2 (auto_compact): token 超阈值时，用 LLM 将旧对话压缩为更短的多轮对话。
"""

from __future__ import annotations

import copy
import json
import logging
from functools import cache
from typing import TYPE_CHECKING

import tiktoken
from pydantic import BaseModel

from anthony_agent.config import app_config
from anthony_agent.prompts import SUMMARY_USER_PROMPT

if TYPE_CHECKING:
    from anthony_agent.client import OpenAIClient
    from anthony_agent.memory.session import SessionManager

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


# 每张图片的 token 估算（OpenAI Vision：low detail 固定 85，high detail 随尺寸增长，这里取保守折中值）
_IMAGE_TOKEN_COST = 1000


def _estimate_message_tokens(msg: dict, enc: "tiktoken.Encoding") -> int:
    """估算单条消息的 token 数，对多模态 content 做特殊处理避免 base64 参与计算。"""
    content = msg.get("content")
    if isinstance(content, list):
        # 多模态 content parts：逐 part 计算，图片用固定估值
        total = 4  # 消息框架开销
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                total += len(enc.encode(part.get("text", "")))
            elif part.get("type") == "image_url":
                total += _IMAGE_TOKEN_COST
        # 其余字段（role 等）
        rest = {k: v for k, v in msg.items() if k != "content"}
        total += len(enc.encode(json.dumps(rest, ensure_ascii=False)))
        return total
    # 普通消息：直接整条 JSON 序列化后编码
    return 4 + len(enc.encode(json.dumps(msg, ensure_ascii=False)))


def estimate_tokens(messages: list[dict]) -> int:
    enc = _get_encoder()
    return sum(_estimate_message_tokens(m, enc) for m in messages)


def _calc_total_tokens(messages: list[dict], system_prompt: str) -> int:
    return len(_get_encoder().encode(system_prompt)) + 4 + estimate_tokens(messages)


# ── Layer 1: micro_compact ────────────────────────────────────


def micro_compact(messages: list[dict]) -> None:
    """原地压缩 3 轮之前的工具返回值（包括带图片的 user message）。

    注意：_strip_discardable_tools 必须只作用于边界之前的消息，
    最近 _KEEP_TURNS 轮内的 think 等调用必须原样保留，
    否则模型在当前轮内看不到自己刚 think 过的记录，会反复重复调用。
    """
    if not messages:
        return
    boundary = _find_keep_boundary(messages, _KEEP_TURNS)
    if boundary > 0:
        older = messages[:boundary]
        _strip_discardable_tools(older)
        _replace_tool_outputs(older)
        messages[:boundary] = older


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

    # 分离最近几轮（保证 to_compress 至少 2 轮，避免压缩摘要被单独拆出来再压）
    total_turns = _count_turns(messages)
    keep = max(min(total_turns - 2, _KEEP_TURNS), 0)
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

    # LLM 压缩
    summary_text = await _compress_to_dialogue(to_compress, client)

    archive_note = ""
    if transcript_path:
        archive_note = f"，完整历史已归档到：{transcript_path}"

    compact_user = {
        "role": "user",
        "content": "上下文即将超限，请将早期对话压缩为摘要，归档旧数据。",
        "_compact_marker": True,
    }
    compact_assistant = {
        "role": "assistant",
        "content": f"[已将早期对话压缩为摘要{archive_note}]\n\n{summary_text}",
        "_compacted": True,
    }
    compressed = [compact_user, compact_assistant]

    # 重建 messages
    messages.clear()
    messages.extend(compressed)
    if recent:
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


async def _compress_to_dialogue(messages: list[dict], client: "OpenAIClient") -> str:
    """预处理 + LLM 压缩，直接返回 LLM 原始输出文本。"""
    prepared = copy.deepcopy(messages)
    _strip_discardable_tools(prepared)
    _replace_tool_outputs(prepared)
    _truncate_long_arguments(prepared)
    _flatten_image_content(prepared)
    _ensure_assistant_content(prepared)

    resp = await client.chat([
        *prepared,
        {"role": "user", "content": SUMMARY_USER_PROMPT},
    ])

    return resp.content or ""


# ── 内部工具函数 ──────────────────────────────────────────────


def _strip_discardable_tools(messages: list[dict]) -> None:
    """从消息列表中移除 _ALWAYS_DISCARD_TOOLS 的 tool_call 和对应的 tool 消息（原地修改）。

    用于摘要生成前的预处理，避免 think 等无信息量的工具调用浪费摘要 token。
    """
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

    同时处理两类消息（都通过 tool_call_id 关联到工具调用）：
    - role == "tool"：普通的工具返回消息
    - role == "user" 且带 _tool_call_id：工具注入的图片附件

    - think 等 _ALWAYS_DISCARD_TOOLS：内容直接丢弃（通常已被 _strip_discardable_tools 删除）
    - _SKIP_COMPACT_TOOLS（write_file 等）：不压缩，保留原文
    - 其他工具：替换为占位符，保留工具名
    """
    tc_map = _build_tc_map(messages)
    for msg in messages:
        call_id = _msg_tool_call_id(msg)
        if not call_id:
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and content.startswith(_COMPACT_PREFIX):
            continue
        name = tc_map.get(call_id, "unknown")
        if name in _SKIP_COMPACT_TOOLS:
            continue
        msg["content"] = f"{_COMPACT_PREFIX} 此前调用了工具 {name}（call_id: {call_id}），原始输出已省略"

def _msg_tool_call_id(msg: dict) -> str | None:
    """返回这条消息关联的 tool_call_id（两种形式），若非工具输出则返回 None。"""
    if msg.get("role") == "tool":
        return msg.get("tool_call_id") or None
    if msg.get("role") == "user" and msg.get("_tool_call_id"):
        return msg["_tool_call_id"]
    return None


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


def _flatten_image_content(messages: list[dict]) -> None:
    """将多模态 content 扁平化为纯文本，避免 base64 图片被发送到摘要模型。

    摘要阶段不需要真正分析图片，只需保留"曾读过某张图"这个事实。
    """
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        text_parts: list[str] = []
        image_count = 0
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                text_parts.append(part.get("text", ""))
            elif part.get("type") == "image_url":
                image_count += 1
        if image_count:
            text_parts.append(f"[{image_count} 张图片]")
        msg["content"] = "\n".join(text_parts) if text_parts else ""

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


def _is_real_user(msg: dict) -> bool:
    """判断是否为真实用户轮次（排除工具注入的图片 user message）。"""
    return msg.get("role") == "user" and not msg.get("_tool_call_id")


def _count_turns(messages: list[dict]) -> int:
    return sum(1 for m in messages if _is_real_user(m))


def _find_keep_boundary(messages: list[dict], keep: int) -> int:
    """从末尾往前找第 keep 个 user 消息的索引。"""
    n = 0
    for i in range(len(messages) - 1, -1, -1):
        if _is_real_user(messages[i]):
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

