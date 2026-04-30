"""Headless tests for the promptlog GUI (no display required).

The GUI module is tested at the model/logic level: file loading, entry parsing,
search filtering, and verify-result mapping. Tkinter widget construction is
guarded behind a display check so these tests pass in CI without a display.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest


# ---------------------------------------------------------------------------
# Helpers to write fixture JSONL files
# ---------------------------------------------------------------------------

def _write_log(path: Path, entries: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")


def _make_entry(index: int, model: str = "gpt-4o", **extra) -> dict:
    from promptlog.logger import GENESIS_HASH, _compute_hash

    prev_hash = extra.pop("prev_hash", GENESIS_HASH)
    payload = {
        "index": index,
        "timestamp": f"2026-04-30T12:00:{index:02d}+00:00",
        "prompt": f"Question {index}",
        "response": f"Answer {index}",
        "model": model,
        "metadata": extra.get("metadata", {}),
    }
    h = _compute_hash(prev_hash, payload)
    return {**payload, "prev_hash": prev_hash, "hash": h}


# ---------------------------------------------------------------------------
# GUI import guard: skip widget tests if no display is available
# ---------------------------------------------------------------------------

def _has_display() -> bool:
    try:
        import tkinter as tk
        root = tk.Tk()
        root.destroy()
        return True
    except Exception:
        return False


HAS_DISPLAY = _has_display()
skip_no_display = pytest.mark.skipif(not HAS_DISPLAY, reason="No display available")


# ---------------------------------------------------------------------------
# Logic tests (no display needed)
# ---------------------------------------------------------------------------

def test_gui_module_imports() -> None:
    """The gui module must be importable even without a display."""
    import importlib
    import types
    # We can import the module; Tk() construction is deferred until main().
    spec = importlib.util.find_spec("promptlog.gui")
    assert spec is not None, "promptlog.gui module not found"


def test_entry_json_roundtrip(tmp_path: Path) -> None:
    """Entries written by PromptLogger are parseable by the GUI's _load_entries logic."""
    from promptlog import PromptLogger

    log = tmp_path / "gui_test.jsonl"
    logger = PromptLogger(log)
    logger.log("hello", "world", "gpt-4o", {"t": 0.5})
    logger.log("foo", "bar", "claude-sonnet-4", {})

    # Replicate what PromptLogViewer._load_entries does
    entries = []
    with log.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    assert len(entries) == 2
    assert entries[0]["prompt"] == "hello"
    assert entries[1]["model"] == "claude-sonnet-4"


def test_search_filter_logic(tmp_path: Path) -> None:
    """The search filter (case-insensitive substring match) works on all visible fields."""
    from promptlog import PromptLogger

    log = tmp_path / "filter.jsonl"
    logger = PromptLogger(log)
    logger.log("Tell me about Transformers", "Transformers are...", "gpt-4o", {})
    logger.log("What is RLHF?", "RLHF stands for...", "claude-sonnet-4", {})
    logger.log("Summarise", "Sure.", "gemini-pro", {})

    entries = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]

    def matches(entry: dict, query: str) -> bool:
        q = query.lower()
        idx = entry.get("index", "?")
        ts = str(entry.get("timestamp", ""))
        model = entry.get("model", "")
        prompt = entry.get("prompt", "")
        response = entry.get("response", "")
        return any(q in str(v).lower() for v in (idx, ts, model, prompt, response))

    assert sum(matches(e, "transformers") for e in entries) == 1
    assert sum(matches(e, "claude") for e in entries) == 1
    assert sum(matches(e, "rlhf") for e in entries) == 1
    assert sum(matches(e, "") for e in entries) == 3  # empty query matches all


def test_verify_result_tagging(tmp_path: Path) -> None:
    """Tampered entries are correctly tagged after verify_log."""
    from promptlog import PromptLogger, verify_log

    log = tmp_path / "tamper.jsonl"
    logger = PromptLogger(log)
    for i in range(3):
        logger.log(f"q{i}", f"a{i}", "gpt-4o", {})

    # Tamper entry 1
    lines = log.read_text().splitlines()
    e1 = json.loads(lines[1])
    e1["response"] = "HACKED"
    lines[1] = json.dumps(e1)
    log.write_text("\n".join(lines) + "\n")

    result = verify_log(log)
    tampered_set = set(result.tampered_entries)
    assert not result.is_valid
    assert 1 in tampered_set

    # Entry 0 must not be flagged
    assert 0 not in tampered_set


def test_empty_log_loads_cleanly(tmp_path: Path) -> None:
    """A newly created empty log file should yield zero entries."""
    log = tmp_path / "empty.jsonl"
    log.write_text("")

    entries = []
    with log.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    assert entries == []


def test_nonexistent_file_verify(tmp_path: Path) -> None:
    """verify_log on a missing file returns is_valid=False with an error message."""
    from promptlog import verify_log

    result = verify_log(tmp_path / "does_not_exist.jsonl")
    assert not result.is_valid
    assert any("not found" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Widget-level smoke tests (skipped if no display)
# ---------------------------------------------------------------------------

@skip_no_display
def test_viewer_opens_and_closes(tmp_path: Path) -> None:
    """PromptLogViewer can be instantiated and destroyed without errors."""
    from promptlog import PromptLogger
    from promptlog.gui import PromptLogViewer

    log = tmp_path / "viewer.jsonl"
    logger = PromptLogger(log)
    logger.log("test prompt", "test response", "gpt-4o", {})

    viewer = PromptLogViewer()
    viewer._load_file(log)
    assert len(viewer._entries) == 1
    assert viewer._entries[0]["prompt"] == "test prompt"
    viewer.destroy()


@skip_no_display
def test_viewer_verify_sets_tampered_set(tmp_path: Path) -> None:
    """After calling _verify(), _tampered_set is populated for bad entries."""
    from promptlog import PromptLogger
    from promptlog.gui import PromptLogViewer

    log = tmp_path / "v_tamper.jsonl"
    logger = PromptLogger(log)
    for i in range(2):
        logger.log(f"q{i}", f"a{i}", "m", {})

    lines = log.read_text().splitlines()
    e = json.loads(lines[0])
    e["response"] = "BAD"
    lines[0] = json.dumps(e)
    log.write_text("\n".join(lines) + "\n")

    viewer = PromptLogViewer()
    viewer._load_file(log)
    viewer._verify()
    assert 0 in viewer._tampered_set
    viewer.destroy()
