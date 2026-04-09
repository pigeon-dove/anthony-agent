"""临时测试脚本 — 验证压缩优化"""
import sys, copy
sys.path.insert(0, '/Users/anthonyxue/Desktop/anthony-agent')
from src.memory.compactor import (
    micro_compact, _replace_tool_outputs,
    _compact_for_summary, _rebuild_messages,
)

# 1. micro_compact 截断行为
msgs = [
    {"role": "user", "content": "q1"},
    {"role": "assistant", "tool_calls": [
        {"id": "c1", "function": {"name": "read_file", "arguments": "{}"}}
    ]},
    {"role": "tool", "tool_call_id": "c1", "content": "X" * 800},
    {"role": "assistant", "content": "a1"},
    {"role": "user", "content": "q2"},
    {"role": "assistant", "content": "a2"},
    {"role": "user", "content": "q3"},
    {"role": "assistant", "content": "a3"},
    {"role": "user", "content": "q4"},
    {"role": "assistant", "content": "a4"},
]
micro_compact(msgs)
tc = msgs[2]["content"]
assert tc.startswith("X" * 100), "Should keep head"
assert "[已压缩]" in tc, "Should have truncation marker"
print("1. micro_compact truncation: OK")

# 2. _rebuild_messages 对 recent 的压缩
recent = [
    {"role": "user", "content": "rq"},
    {"role": "assistant", "tool_calls": [
        {"id": "c2", "function": {"name": "grep", "arguments": "{}"}}
    ]},
    {"role": "tool", "tool_call_id": "c2", "content": "Y" * 1000},
]
out = []
_rebuild_messages(out, "summary", recent, {"role": "user", "content": "latest"})
assert out[0]["content"].startswith("[本次对话过长")
assert out[1]["content"] == "summary"
# out: [compact_marker, summary, user:rq, assistant:tool_calls, tool:Y..., user:latest]
tool_msg = out[4]  # tool 消息在第 5 个位置
assert "Y" * 50 in tool_msg["content"]
assert "[已压缩]" in tool_msg["content"]
print("2. _rebuild_messages recent compression: OK")

# 3. _compact_for_summary 参数截断
msgs3 = [
    {"role": "assistant", "tool_calls": [
        {"id": "c3", "function": {"name": "write_file",
         "arguments": '{"path": "/a.py", "content": "' + "Z" * 3000 + '"}'}}
    ]},
    {"role": "tool", "tool_call_id": "c3", "content": "ok"},
]
compacted = _compact_for_summary(msgs3)
args = compacted[0]["tool_calls"][0]["function"]["arguments"]
assert len(args) < 2500, f"Args should be truncated, got {len(args)}"
print("3. _compact_for_summary args truncation: OK")

# 4. full=True vs full=False
m_full = [
    {"role": "assistant", "tool_calls": [
        {"id": "c4", "function": {"name": "bash", "arguments": "{}"}}
    ]},
    {"role": "tool", "tool_call_id": "c4", "content": "W" * 600},
]
m_micro = copy.deepcopy(m_full)
_replace_tool_outputs(m_micro)
assert m_micro[1]["content"].startswith("W"), "micro should keep head"

m_f = copy.deepcopy(m_full)
_replace_tool_outputs(m_f, full=True)
assert m_f[1]["content"].startswith("[已压缩]"), "full should replace"
print("4. full vs micro mode: OK")

print("\nAll tests passed!")
