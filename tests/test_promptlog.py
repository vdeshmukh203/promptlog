"""Smoke + tamper-detection tests for promptlog."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from promptlog import PromptLogger, verify_log  # noqa: E402


def test_basic_logging_and_verification(tmp_path: Path) -> None:
    log_path = tmp_path / "session.jsonl"
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
        response="L'attention pondere la pertinence des jetons.",
        model="gemini-2.0-pro",
        metadata={},
    )

    result = verify_log(log_path)
    assert result.is_valid, result.errors
    assert result.entries_checked == 3
    assert result.tampered_entries == []


def test_append_after_reopen(tmp_path: Path) -> None:
    log_path = tmp_path / "reopen.jsonl"
    PromptLogger(log_path).log("p1", "r1", "m1", {})
    PromptLogger(log_path).log("p2", "r2", "m2", {})
    PromptLogger(log_path).log("p3", "r3", "m3", {})

    result = verify_log(log_path)
    assert result.is_valid, result.errors
    assert result.entries_checked == 3
    indices = [json.loads(l)["index"] for l in log_path.read_text().splitlines() if l.strip()]
    assert indices == [0, 1, 2], indices


def test_tamper_detection_response_edit(tmp_path: Path) -> None:
    log_path = tmp_path / "tamper.jsonl"
    logger = PromptLogger(log_path)
    for i in range(4):
        logger.log(prompt=f"q{i}", response=f"a{i}", model="gpt-4o", metadata={"i": i})

    lines = log_path.read_text().splitlines()
    entry = json.loads(lines[1])
    entry["response"] = "MALICIOUSLY EDITED"
    lines[1] = json.dumps(entry, ensure_ascii=False)
    log_path.write_text("\n".join(lines) + "\n")

    result = verify_log(log_path)
    assert not result.is_valid
    assert 1 in result.tampered_entries, result.tampered_entries


def test_tamper_detection_edit_then_rehash(tmp_path: Path) -> None:
    from promptlog.logger import _compute_hash

    log_path = tmp_path / "rehash.jsonl"
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
    assert not result.is_valid, "downstream prev_hash mismatch must catch the cover-up"
    assert 2 in result.tampered_entries, result.tampered_entries


def test_tamper_detection_deleted_entry(tmp_path: Path) -> None:
    log_path = tmp_path / "delete.jsonl"
    logger = PromptLogger(log_path)
    for i in range(3):
        logger.log(prompt=f"q{i}", response=f"a{i}", model="gpt-4o", metadata={})

    lines = log_path.read_text().splitlines()
    del lines[1]
    log_path.write_text("\n".join(lines) + "\n")

    result = verify_log(log_path)
    assert not result.is_valid, "deletion must be detected"


def test_empty_file_is_valid(tmp_path: Path) -> None:
    log_path = tmp_path / "empty.jsonl"
    log_path.write_text("")
    result = verify_log(log_path)
    assert result.is_valid
    assert result.entries_checked == 0
