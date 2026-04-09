"""JSONL 读写工具"""

import json
from pathlib import Path


class JSONLStorage:

    def __init__(self, path: Path):
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: dict) -> None:
        self._ensure_dir()
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def append_many(self, records: list[dict]) -> None:
        if not records:
            return
        self._ensure_dir()
        with open(self._path, "a", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def read_all(self) -> list[dict]:
        if not self._path.exists():
            return []
        with open(self._path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def overwrite(self, records: list[dict]) -> None:
        self._ensure_dir()
        with open(self._path, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def exists(self) -> bool:
        return self._path.exists()

    def count(self) -> int:
        if not self._path.exists():
            return 0
        with open(self._path, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())

    def _ensure_dir(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
