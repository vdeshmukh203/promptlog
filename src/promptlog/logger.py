"""PromptLogger: append-only JSONL logger with SHA-256 hash-chained entries."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

GENESIS_HASH = "0" * 64


def _canonical_json(payload: Mapping[str, Any]) -> str:
    """Serialize a payload deterministically for hashing."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _compute_hash(prev_hash: str, payload: Mapping[str, Any]) -> str:
    """Compute SHA-256 of (prev_hash || canonical(payload))."""
    h = hashlib.sha256()
    h.update(prev_hash.encode("utf-8"))
    h.update(b"\n")
    h.update(_canonical_json(payload).encode("utf-8"))
    return h.hexdigest()


class PromptLogger:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        parent = self.path.parent
        if str(parent) and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        self._last_hash, self._next_index = self._scan_tail()

    def _scan_tail(self) -> tuple[str, int]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return GENESIS_HASH, 0
        last_hash = GENESIS_HASH
        count = 0
        valid_end = 0
        with self.path.open("r+b") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    valid_end = f.tell()
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    f.truncate(valid_end)
                    break
                last_hash = entry.get("hash", last_hash)
                count += 1
                valid_end = f.tell()
        return last_hash, count

    def log(self, prompt: str, response: str, model: str,
            metadata: Mapping[str, Any] | None = None,
            timestamp: str | None = None) -> dict[str, Any]:
        if metadata is None:
            metadata = {}
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()
        with self._lock:
            payload = {
                "index": self._next_index, "timestamp": timestamp,
                "prompt": prompt, "response": response,
                "model": model, "metadata": dict(metadata),
            }
            entry_hash = _compute_hash(self._last_hash, payload)
            entry = {**payload, "prev_hash": self._last_hash, "hash": entry_hash}
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            self._last_hash = entry_hash
            self._next_index += 1
            return entry
