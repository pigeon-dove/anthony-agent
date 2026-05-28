"""JSONL 读写工具（基于 jsonlines 库）"""

import logging
import os
import tempfile
import threading
from pathlib import Path

import jsonlines

logger = logging.getLogger(__name__)


class JSONLStorage:

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: dict) -> None:
        self._ensure_dir()
        with self._lock:
            with jsonlines.open(self._path, mode="a") as writer:
                writer.write(record)

    def append_many(self, records: list[dict]) -> None:
        if not records:
            return
        self._ensure_dir()
        with self._lock:
            with jsonlines.open(self._path, mode="a") as writer:
                writer.write_all(records)

    def read_all(self) -> list[dict]:
        if not self._path.exists():
            return []
        results: list[dict] = []
        bad = 0
        with self._lock:
            with jsonlines.open(self._path, mode="r") as reader:
                while True:
                    try:
                        results.append(reader.read(type=dict))
                    except EOFError:
                        break
                    except jsonlines.InvalidLineError:
                        bad += 1
        if bad:
            logger.warning("%s 跳过 %d 行无法解析的数据", self._path.name, bad)
        return results

    def overwrite(self, records: list[dict]) -> None:
        """原子性重写：先写临时文件，再 rename 替换，避免写到一半被中断导致数据丢失。"""
        self._ensure_dir()
        with self._lock:
            fd, tmp_path = tempfile.mkstemp(
                dir=self._path.parent, prefix=".tmp_", suffix=".jsonl"
            )
            try:
                os.close(fd)
                with jsonlines.open(tmp_path, mode="w") as writer:
                    writer.write_all(records)
                os.replace(tmp_path, self._path)
            except BaseException:
                # 写入失败时清理临时文件
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

    def exists(self) -> bool:
        return self._path.exists()

    def count(self) -> int:
        if not self._path.exists():
            return 0
        with self._lock:
            with jsonlines.open(self._path, mode="r") as reader:
                return sum(1 for _ in reader.iter(type=dict, skip_invalid=True))

    def _ensure_dir(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
