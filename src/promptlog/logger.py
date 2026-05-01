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
    """Append-only, thread-safe JSONL logger with a SHA-256 hash chain.

    Each entry records *prev_hash* and its own *hash*, so any post-hoc edit,
    insertion, or deletion is detectable by :func:`promptlog.verify_log`.

    Parameters
    ----------
    path:
        Filesystem path for the JSONL log file (created if absent).
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        parent = self.path.parent
        if str(parent) and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        self._last_hash, self._next_index = self._scan_tail()

    def _scan_tail(self) -> tuple[str, int]:
        """Return (last_hash, entry_count) by reading the existing log.

        Uses ``readline()`` rather than ``for line in f`` so that
        ``f.tell()`` reliably tracks byte positions for safe truncation of
        partially-written trailing content.
        """
        if not self.path.exists() or self.path.stat().st_size == 0:
            return GENESIS_HASH, 0
        last_hash = GENESIS_HASH
        count = 0
        valid_end = 0
        with self.path.open("r+b") as f:
            while True:
                raw = f.readline()
                if not raw:
                    break
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

    def log(
        self,
        prompt: str,
        response: str,
        model: str,
        metadata: Mapping[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        """Append one prompt/response record and return the written entry dict.

        Parameters
        ----------
        prompt:
            The user prompt or input text.
        response:
            The model response text.
        model:
            Model identifier string (e.g. ``"gpt-4o"``).
        metadata:
            Optional mapping of extra fields (temperature, token counts, …).
        timestamp:
            ISO-8601 timestamp string; defaults to ``datetime.now(UTC)``.

        Returns
        -------
        dict
            The full entry as written to disk, including ``prev_hash`` and
            ``hash`` fields.
        """
        if metadata is None:
            metadata = {}
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()
        with self._lock:
            payload = {
                "index": self._next_index,
                "timestamp": timestamp,
                "prompt": prompt,
                "response": response,
                "model": model,
                "metadata": dict(metadata),
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
