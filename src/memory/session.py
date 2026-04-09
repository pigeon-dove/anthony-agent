"""会话管理 — 创建 / 恢复 / 持久化"""

import json
import secrets
from datetime import datetime
from pathlib import Path

from src.memory.storage import JSONLStorage

ANTHONY_DIR = ".anthony"
SESSIONS_DIR = "sessions"
MESSAGES_FILE = "messages.jsonl"
TRANSCRIPTS_DIR = "transcripts"


class SessionManager:
    """管理 .anthony/sessions/{session_id}/ 下的会话数据。"""

    def __init__(self, workdir: Path | None = None):
        self._workdir = workdir or Path.cwd()
        self._anthony_dir = self._workdir / ANTHONY_DIR
        self._session_id: str | None = None
        self._storage: JSONLStorage | None = None

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def session_dir(self) -> Path | None:
        if not self._session_id:
            return None
        return self._anthony_dir / SESSIONS_DIR / self._session_id

    @property
    def messages_storage(self) -> JSONLStorage | None:
        return self._storage

    # ── 初始化 ────────────────────────────────────────────

    def init(self, session_id: str | None = None) -> str:
        if session_id:
            session_dir = self._anthony_dir / SESSIONS_DIR / session_id
            if not session_dir.exists():
                raise ValueError(f"会话不存在: {session_id}")
            return self._activate(session_id)

        latest = self._find_latest()
        if latest:
            return self._activate(latest)

        return self.create_session()

    def create_session(self) -> str:
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_id = f"{now}_{secrets.token_hex(2)}"
        (self._anthony_dir / SESSIONS_DIR / session_id).mkdir(parents=True, exist_ok=True)
        return self._activate(session_id)

    # ── 消息持久化 ────────────────────────────────────────

    def append_message(self, message: dict) -> None:
        self._require_init()
        self._storage.append(message)  # type: ignore[union-attr]

    def load_messages(self) -> list[dict]:
        self._require_init()
        return self._storage.read_all()  # type: ignore[union-attr]

    def overwrite_messages(self, messages: list[dict]) -> None:
        self._require_init()
        self._storage.overwrite(messages)  # type: ignore[union-attr]

    # ── 压缩归档 ─────────────────────────────────────────

    def save_transcript(self, messages: list[dict]) -> Path:
        self._require_init()
        assert self.session_dir is not None
        transcripts_dir = self.session_dir / TRANSCRIPTS_DIR
        transcripts_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = transcripts_dir / f"{timestamp}.md"
        path.write_text(_messages_to_markdown(messages), encoding="utf-8")
        return path

    # ── 内部方法 ──────────────────────────────────────────

    def _activate(self, session_id: str) -> str:
        self._session_id = session_id
        session_dir = self._anthony_dir / SESSIONS_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        self._storage = JSONLStorage(session_dir / MESSAGES_FILE)
        return session_id

    def _find_latest(self) -> str | None:
        sessions_dir = self._anthony_dir / SESSIONS_DIR
        if not sessions_dir.exists():
            return None
        dirs = sorted(
            [d.name for d in sessions_dir.iterdir() if d.is_dir()],
            reverse=True,
        )
        return dirs[0] if dirs else None

    def _require_init(self) -> None:
        if not self._storage:
            raise RuntimeError("会话未初始化，请先调用 init()")


# ── Markdown 归档格式 ────────────────────────────────────────

def _messages_to_markdown(messages: list[dict]) -> str:
    """将消息列表转换为人类可读的 Markdown 格式。"""
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if role == "user":
            parts.append(f"## 用户\n\n{content}")

        elif role == "assistant":
            # 先输出文本内容
            if content:
                parts.append(f"## 助手\n\n{content}")
            # 再输出工具调用
            for tc in msg.get("tool_calls", []):
                func = tc.get("function", {})
                name = func.get("name", "unknown")
                args = func.get("arguments", "")
                # 尝试格式化 JSON 参数
                try:
                    args_formatted = json.dumps(
                        json.loads(args), indent=2, ensure_ascii=False,
                    )
                except (json.JSONDecodeError, TypeError):
                    args_formatted = args
                parts.append(
                    f"### 工具调用: {name}\n\n"
                    f"```json\n{args_formatted}\n```"
                )

        elif role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            # content 可能很长，用代码块包裹
            parts.append(
                f"### 工具结果 (call_id: {tool_call_id})\n\n"
                f"```\n{content}\n```"
            )

    return "\n\n---\n\n".join(parts) + "\n"
