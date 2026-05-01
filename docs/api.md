# promptlog API Reference

## PromptLogger

Append-only, thread-safe JSONL logger with a SHA-256 hash chain.

```python
from promptlog import PromptLogger

logger = PromptLogger("session.jsonl")

entry = logger.log(
    prompt="Explain transformer attention",
    response="Attention mechanisms allow the model to weigh token relationships.",
    model="gpt-4o",
    metadata={"temperature": 0.7},
)
# entry is a dict with index, timestamp, prompt, response, model, metadata,
# prev_hash, and hash fields.
```

### Constructor

```python
PromptLogger(path: str | Path)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `str \| Path` | Filesystem path for the JSONL log (created if absent). |

### `log(prompt, response, model, metadata=None, timestamp=None)`

Append one record and return the written entry as a `dict`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prompt` | `str` | — | User prompt text. |
| `response` | `str` | — | Model response text. |
| `model` | `str` | — | Model identifier (e.g. `"gpt-4o"`). |
| `metadata` | `dict \| None` | `{}` | Optional extra fields (temperature, token counts, …). |
| `timestamp` | `str \| None` | `datetime.now(UTC)` | ISO-8601 timestamp; auto-generated if omitted. |

---

## verify_log

Validate the SHA-256 hash chain of a JSONL log file.

```python
from promptlog import verify_log

result = verify_log("session.jsonl")
print(result.is_valid)            # True / False
print(result.entries_checked)     # int
print(result.tampered_entries)    # list[int] – indices of bad entries
print(result.errors)              # list[str] – human-readable error messages
```

### `VerifyResult` fields

| Field | Type | Description |
|-------|------|-------------|
| `is_valid` | `bool` | `True` iff the entire chain is intact. |
| `entries_checked` | `int` | Number of entries successfully parsed. |
| `tampered_entries` | `list[int]` | Entry indices that failed verification. |
| `errors` | `list[str]` | Diagnostic messages for each failure. |

---

## HTTP Interceptor

Auto-log every LLM API call without modifying application code.

```python
import promptlog

promptlog.install("session.jsonl")
# All urllib / requests calls to OpenAI, Anthropic, and Google are now logged.
promptlog.uninstall()

print(promptlog.is_installed())  # False
```

Streaming (`text/event-stream`) responses are passed through unmodified and
are **not** logged.

### Custom providers

```python
from promptlog.providers import make_provider, OPENAI_CHAT

my_rule = make_provider(OPENAI_CHAT, match=lambda host, path: "my-proxy.internal" in host)
promptlog.install("session.jsonl", providers=[my_rule])
```

---

## GUI

Browse and verify a log file in your default web browser.

```bash
# Command line
python -m promptlog.gui session.jsonl
python -m promptlog.gui session.jsonl --port 8080 --no-browser

# If installed as a package
promptlog-gui session.jsonl
```

```python
# Programmatic
from promptlog import launch_gui
launch_gui("session.jsonl", port=7432, open_browser=True)
```

The GUI shows all entries in a searchable, filterable table.
Entries from a tampered chain are highlighted in amber.
No internet connection or external JavaScript libraries are required.
