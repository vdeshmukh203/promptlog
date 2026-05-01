# Changelog

All notable changes to promptlog are documented here.

## [Unreleased]

### Planned
- `AsyncPromptLogger` for high-throughput async environments (#2)
- Export to Apache Parquet format via `promptlog export` CLI (#3)

## [0.1.1] - 2026-05-01

### Fixed
- `PromptLogger._scan_tail` now uses `readline()` instead of `for line in f`
  so that `f.tell()` tracks correct byte positions when truncating partially-
  written trailing content (mixing buffered iteration with `tell()` is
  unreliable on CPython).
- `_CachedBodyResponse.closed` no longer conflates stream exhaustion with an
  explicit `close()` call; `isclosed()` still returns `True` on exhaustion so
  that `http.client` connection-reuse logic works correctly.
- `promptlog.py` standalone script: replaced deprecated `datetime.utcnow()`
  with `datetime.now(timezone.utc)`; unified `get_stats()` key names between
  SQLite and JSONL backends (`total_records` in both).
- Test suite: `_read_log()` in `test_intercept.py` now passes `encoding="utf-8"`
  to `read_text()` to fix compatibility with `py.path.local`.

### Added
- **Web GUI** (`src/promptlog/gui.py`): zero-dependency browser-based log
  viewer. Launch with `python -m promptlog.gui <file.jsonl>` or the
  `promptlog-gui` entry-point. Displays all entries in a searchable, filterable
  table; highlights tampered entries from a broken hash chain.
- `promptlog.launch_gui` exported from the top-level package.
- `promptlog-gui` console script registered in `pyproject.toml`.
- Expanded docstrings on `PromptLogger` and `PromptLogger.log`.

## [0.1.0] - 2026-04-23

### Added
- Initial release of `promptlog`
- `PromptLogger` class with JSONL output and SHA-256 hash-chain verification
- Support for OpenAI, Anthropic, Google, and custom LLM providers
- `verify_log()` tamper detection function
- CLI: `promptlog verify <file>`
