"""PromptLogger: append-only JSONL logger with SHA-256 hash-chained entries."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

# Sentinel "previous hash" for the first entry in any log file.
GENESIS_HASH = "0" * 64


def _canonical_json(payload: Mapping[str, Any]) -> str:
    """Return a deterministic JSON serialisation of *payload* suitable for hashing.

    Keys are sorted and separators are compact so the output is stable across
    Python versions and platforms.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _compute_hash(prev_hash: str, payload: Mapping[str, Any]) -> str:
    """Compute SHA-256 of ``prev_hash || '\\n' || canonical_json(payload)``.

    Chaining the previous hash into each entry makes any insertion, deletion,
    or modification detectable during verification.
    """
    h = hashlib.sha256()
    h.update(prev_hash.encode("utf-8"))
    h.update(b"\n")
    h.update(_canonical_json(payload).encode("utf-8"))
    return h.hexdigest()


class PromptLogger:
    """Append-only, thread-safe JSONL logger with a SHA-256 hash chain.

    Each call to :meth:`log` writes one JSON line and links it to the previous
    entry via its SHA-256 hash, forming a tamper-evident chain.  Use
    :func:`~promptlog.verify_log` to validate the chain.

    Parameters
    ----------
    path:
        Destination file.  Parent directories are created automatically.
        If the file already exists its tail is scanned to continue the chain.

    Example
    -------
    >>> logger = PromptLogger("session.jsonl")
    >>> logger.log("What is 2+2?", "4", model="gpt-4o")
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        parent = self.path.parent
        if str(parent) and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        self._last_hash, self._next_index = self._scan_tail()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scan_tail(self) -> tuple[str, int]:
        """Read the file tail to recover the last hash and next entry index.

        Truncates any trailing incomplete (non-JSON) line so subsequent writes
        start from a clean state.
        """
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
                    warnings.warn(
                        f"promptlog: truncating corrupt trailing data in {self.path}",
                        RuntimeWarning,
                        stacklevel=3,
                    )
                    f.truncate(valid_end)
                    break
                last_hash = entry.get("hash", last_hash)
                count += 1
                valid_end = f.tell()
        return last_hash, count

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log(
        self,
        prompt: str,
        response: str,
        model: str,
        metadata: Mapping[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        """Append a log entry and return it.

        Parameters
        ----------
        prompt:
            The input text sent to the model.
        response:
            The model's output text.
        model:
            Model identifier string (e.g. ``"gpt-4o"``).
        metadata:
            Arbitrary key/value pairs stored alongside the entry (provider,
            token counts, latency, etc.).
        timestamp:
            ISO-8601 timestamp string.  Defaults to the current UTC time.

        Returns
        -------
        dict
            The complete entry as written to disk (includes ``hash`` and
            ``prev_hash`` fields).
        """
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

    def __repr__(self) -> str:
        return (
            f"PromptLogger(path={str(self.path)!r}, "
            f"entries={self._next_index}, "
            f"last_hash={self._last_hash[:12]!r}...)"
        )
