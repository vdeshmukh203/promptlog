"""verify_log: validate the SHA-256 hash chain of a promptlog JSONL file."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .logger import GENESIS_HASH, _compute_hash

REQUIRED_FIELDS = (
    "index", "timestamp", "prompt", "response",
    "model", "metadata", "prev_hash", "hash",
)


@dataclass
class VerifyResult:
    """Result of verifying a promptlog JSONL file.

    Attributes
    ----------
    is_valid:
        ``True`` if every entry's hash chain is intact and no tampering was
        detected.
    entries_checked:
        Number of successfully parsed and verified entries.
    tampered_entries:
        Zero-based indices of entries that failed verification.
    errors:
        Human-readable descriptions of each detected problem.

    Notes
    -----
    The object evaluates as a boolean: ``bool(result)`` returns
    :attr:`is_valid`.
    """

    is_valid: bool
    entries_checked: int = 0
    tampered_entries: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.is_valid

    def __repr__(self) -> str:
        status = "VALID" if self.is_valid else f"INVALID ({len(self.tampered_entries)} tampered)"
        return f"VerifyResult({status}, entries_checked={self.entries_checked})"


def verify_log(path: str | os.PathLike[str]) -> VerifyResult:
    """Verify the SHA-256 hash chain of a JSONL log file.

    Reads every line, recomputes the hash from the stored payload fields, and
    checks that each entry's ``prev_hash`` matches the previous entry's
    ``hash``.  Any insertion, deletion, or field modification will break the
    chain and be reported.

    Parameters
    ----------
    path:
        Path to the JSONL log file produced by :class:`~promptlog.PromptLogger`.

    Returns
    -------
    VerifyResult
        A result object whose :attr:`~VerifyResult.is_valid` attribute is
        ``True`` only when the entire chain is intact.

    Example
    -------
    >>> result = verify_log("session.jsonl")
    >>> if not result:
    ...     print("Tampering detected:", result.errors)
    """
    p = Path(path)
    result = VerifyResult(is_valid=True)
    if not p.exists():
        result.is_valid = False
        result.errors.append(f"file not found: {p}")
        return result
    prev_hash = GENESIS_HASH
    expected_index = 0
    with p.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                result.is_valid = False
                result.errors.append(f"line {line_no}: invalid JSON ({exc.msg})")
                result.tampered_entries.append(expected_index)
                expected_index += 1
                continue
            result.entries_checked += 1
            missing = [f for f in REQUIRED_FIELDS if f not in entry]
            if missing:
                result.is_valid = False
                result.errors.append(f"line {line_no}: missing fields {missing}")
                result.tampered_entries.append(entry.get("index", expected_index))
                prev_hash = entry.get("hash", prev_hash)
                expected_index += 1
                continue
            entry_failed = False
            if entry["index"] != expected_index:
                result.is_valid = False
                result.errors.append(
                    f"line {line_no}: index {entry['index']} does not match "
                    f"expected {expected_index}"
                )
                entry_failed = True
            if entry["prev_hash"] != prev_hash:
                result.is_valid = False
                result.errors.append(
                    f"line {line_no}: prev_hash mismatch "
                    f"(expected {prev_hash[:12]}…, got {entry['prev_hash'][:12]}…)"
                )
                entry_failed = True
            payload = {
                "index": entry["index"], "timestamp": entry["timestamp"],
                "prompt": entry["prompt"], "response": entry["response"],
                "model": entry["model"], "metadata": entry["metadata"],
            }
            recomputed = _compute_hash(entry["prev_hash"], payload)
            if recomputed != entry["hash"]:
                result.is_valid = False
                result.errors.append(
                    f"line {line_no}: hash mismatch "
                    f"(expected {recomputed[:12]}…, got {entry['hash'][:12]}…)"
                )
                entry_failed = True
            if entry_failed:
                result.tampered_entries.append(entry["index"])
            prev_hash = entry["hash"]
            expected_index += 1
    return result
