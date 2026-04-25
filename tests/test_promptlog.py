"""Smoke + tamper-detection tests for promptlog.

Run directly: ``python tests/test_promptlog.py``
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from promptlog import PromptLogger, verify_log  # noqa: E402


def _section(title: str) -> None:
    print(f"\n--- {title} ---")


def test_basic_logging_and_verification(tmpdir: Path) -> None:
    _section("basic logging + verification")
    log_path = tmpdir / "session.jsonl"
    logger = PromptLogger(log_path)

    logger.log(
        prompt="Explain transformer attention",
        response="Attention mechanisms allow the model to weigh token relationships.",
        model="gpt-4o",
        metadata={"temperature": 0.7},
    )
    logger.log(
        prompt="Summarize in one sentence",
        response="Attention scores token relevance.",
        model="claude-sonnet-4",
        metadata={"temperature": 0.2},
    )
    logger.log(
        prompt="Translate to French",
        response="L'attention pondère la pertinence des jetons.",
        model="gemini-2.0-pro",
        metadata={},
    )

    result = verify_log(log_path)
    print(f"entries_checked={result.entries_checked} is_valid={result.is_valid}")
    assert result.is_valid, result.errors
    assert result.entries_checked == 3
    assert result.tampered_entries == []
    print("OK: 3 entries written, hash chain verified.")


def test_append_after_reopen(tmpdir: Path) -> None:
    _section("append after reopen continues hash chain")
    log_path = tmpdir / "reopen.jsonl"
    PromptLogger(log_path).log("p1", "r1", "m1", {})
    PromptLogger(log_path).log("p2", "r2", "m2", {})
    PromptLogger(log_path).log("p3", "r3", "m3", {})

    result = verify_log(log_path)
    assert result.is_valid, result.errors
    assert result.entries_checked == 3
    indices = [json.loads(l)["index"] for l in log_path.read_text().splitlines() if l.strip()]
    assert indices == [0, 1, 2], indices
    print("OK: chain continues correctly across logger reopens.")


def test_tamper_detection_response_edit(tmpdir: Path) -> None:
    _section("tamper detection: edit a response (hash left untouched)")
    log_path = tmpdir / "tamper.jsonl"
    logger = PromptLogger(log_path)
    for i in range(4):
        logger.log(prompt=f"q{i}", response=f"a{i}", model="gpt-4o", metadata={"i": i})

    lines = log_path.read_text().splitlines()
    entry = json.loads(lines[1])
    entry["response"] = "MALICIOUSLY EDITED"
    lines[1] = json.dumps(entry, ensure_ascii=False)
    log_path.write_text("\n".join(lines) + "\n")

    result = verify_log(log_path)
    print(f"is_valid={result.is_valid} tampered={result.tampered_entries}")
    assert not result.is_valid
    assert 1 in result.tampered_entries, result.tampered_entries
    print("OK: tampered entry flagged (its stored hash no longer matches payload).")


def test_tamper_detection_edit_then_rehash(tmpdir: Path) -> None:
    _section("tamper detection: edit a response and recompute its hash")
    from promptlog.logger import _compute_hash

    log_path = tmpdir / "rehash.jsonl"
    logger = PromptLogger(log_path)
    for i in range(4):
        logger.log(prompt=f"q{i}", response=f"a{i}", model="gpt-4o", metadata={"i": i})

    lines = log_path.read_text().splitlines()
    entry = json.loads(lines[1])
    entry["response"] = "MALICIOUSLY EDITED"
    payload = {k: entry[k] for k in ("index", "timestamp", "prompt", "response", "model", "metadata")}
    entry["hash"] = _compute_hash(entry["prev_hash"], payload)
    lines[1] = json.dumps(entry, ensure_ascii=False)
    log_path.write_text("\n".join(lines) + "\n")

    result = verify_log(log_path)
    print(f"is_valid={result.is_valid} tampered={result.tampered_entries}")
    assert not result.is_valid, "downstream prev_hash mismatch must catch the cover-up"
    assert 2 in result.tampered_entries, result.tampered_entries
    print("OK: even after recomputing the entry's own hash, the downstream chain breaks.")


def test_tamper_detection_deleted_entry(tmpdir: Path) -> None:
    _section("tamper detection: delete an entry")
    log_path = tmpdir / "delete.jsonl"
    logger = PromptLogger(log_path)
    for i in range(3):
        logger.log(prompt=f"q{i}", response=f"a{i}", model="gpt-4o", metadata={})

    lines = log_path.read_text().splitlines()
    del lines[1]
    log_path.write_text("\n".join(lines) + "\n")

    result = verify_log(log_path)
    print(f"is_valid={result.is_valid} tampered={result.tampered_entries}")
    assert not result.is_valid, "deletion must be detected"
    print("OK: deletion detected.")


def test_empty_file_is_valid(tmpdir: Path) -> None:
    _section("empty file is valid")
    log_path = tmpdir / "empty.jsonl"
    log_path.write_text("")
    result = verify_log(log_path)
    assert result.is_valid
    assert result.entries_checked == 0
    print("OK: empty file is a valid (zero-length) chain.")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        test_basic_logging_and_verification(tmpdir)
        test_append_after_reopen(tmpdir)
        test_tamper_detection_response_edit(tmpdir)
        test_tamper_detection_edit_then_rehash(tmpdir)
        test_tamper_detection_deleted_entry(tmpdir)
        test_empty_file_is_valid(tmpdir)
    print("\nAll promptlog tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
