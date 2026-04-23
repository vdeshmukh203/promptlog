   # promptlog

Provider-agnostic LLM interaction logger with SHA-256 tamper-evident provenance.

Records every prompt, response, model metadata, and timestamp to structured JSONL
files. Each log entry is SHA-256 hashed and linked in a chain — any post-hoc
modification is detectable, making interaction logs suitable for reproducible
research and scientific reporting.

## Installation

```bash
pip install promptlog
```

## Quick Start

```python
from promptlog import PromptLogger, verify_log

logger = PromptLogger("session.jsonl")

logger.log(
    prompt="Explain transformer attention",
    response="Attention mechanisms allow the model to...",
    model="gpt-4o",
    metadata={"temperature": 0.7}
)

# Verify log integrity
result = verify_log("session.jsonl")
print(result.is_valid, result.tampered_entries)
```

## Features

- Supports OpenAI, Anthropic, Google, and any custom LLM provider
- SHA-256 hash chain: each entry hashes the previous, detecting insertions or deletions
- Structured JSONL output compatible with `jq`, pandas, and standard log tools
- Lightweight — zero required dependencies beyond the standard library
- Designed for reproducible research: logs are deterministic and archivable

## Documentation

Full API documentation and examples are available in the `docs/` directory.

## Citation

If you use `promptlog` in your research, please cite the associated JOSS paper
(under review).

## License

MIT — see [LICENSE](LICENSE) for details.
