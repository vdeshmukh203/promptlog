# Changelog

All notable changes to promptlog are documented here.

## [Unreleased]

### Planned
- `AsyncPromptLogger` for high-throughput async environments (#2)
- Export to Apache Parquet format via `promptlog export` CLI (#3)

## [0.1.0] - 2026-04-23

### Added
- Initial release of `promptlog`
- `PromptLogger` class with JSONL output and SHA-256 hash-chain verification
- Support for OpenAI, Anthropic, Google, and custom LLM providers
- `verify_log()` tamper detection function
- CLI: `promptlog verify &lt;file&gt;`
