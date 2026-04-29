---
title: 'promptlog: A Python library for structured logging of large language model interactions'
tags:
  - Python
  - LLM
  - logging
  - reproducibility
  - prompts
authors:
  - name: Vaibhav Deshmukh
    orcid: 0000-0001-6745-7062
    affiliation: 1
affiliations:
  - name: Independent Researcher, Nagpur, India
    index: 1
date: 23 April 2026
bibliography: paper.bib
---

# Summary

`promptlog` is a Python library that provides structured, provider-agnostic
logging of interactions with large language model (LLM) APIs. Researchers and
developers who use LLMs in their workflows often lack a systematic way to
record, replay, and audit the exact prompts, parameters, and responses that
produced a given result. `promptlog` addresses this gap by intercepting API
calls at the HTTP level and writing structured JSON Lines (JSONL) records that
include the full request payload, response text, model identifier, latency,
token-usage counts, and a SHA-256 hash of each record for tamper detection
[@nist2015sha]. The library supports OpenAI, Anthropic (Claude), and Google
Gemini out of the box, and can be extended to any HTTP-based LLM API. It
requires no changes to existing calling code beyond a single `install()` call.

# Statement of Need

Reproducibility in LLM-based research depends on capturing not just model
outputs but the complete context of each inference call: the system prompt,
user messages, model version, temperature, and other sampling parameters
[@gundersen2018state; @pineau2021improving]. Without a record of these inputs,
independent replication of a result is impossible even when the same model is
nominally re-used, because model providers routinely update weights and
default parameters between versions.

Existing approaches fall into two categories. Provider-specific SDKs
(e.g., the OpenAI Python client) emit logs only for their own endpoints and
require opt-in instrumentation of every call site. General-purpose HTTP
inspection tools (proxy servers, Wireshark, `mitmproxy`) capture raw bytes but
require significant post-processing to extract semantic fields such as the
last user turn or the assistant's reply text. Neither approach produces the
structured, self-verifying log format that `promptlog` provides.

`promptlog` fills this gap by operating at the `http.client.HTTPConnection`
layer of the Python standard library, which is the transport used by
`urllib`, `requests`, `httpx` (sync), and the official SDKs for all three
major providers. By patching two methods on this class at runtime, the
library intercepts every outbound HTTP POST matching a registered provider
rule, reads the full JSON response body once, and writes a tamper-evident
JSONL record — all without modifying caller code and without adding any
runtime dependency beyond the Python standard library.

# Design and Implementation

## Hash-chained log format

Each log entry is a JSON object written as a single line of a JSONL file.
The object contains the following fields:

| Field | Description |
|---|---|
| `index` | Zero-based integer position in the log |
| `timestamp` | ISO 8601 UTC timestamp of the call |
| `prompt` | Last user-role message text extracted from the request |
| `response` | Assistant reply text extracted from the response |
| `model` | Model identifier as returned by the provider |
| `metadata` | Provider name, endpoint URL, HTTP status, latency (ms), token usage, finish reason |
| `prev_hash` | SHA-256 hash of the previous entry (genesis entry uses 64 zero digits) |
| `hash` | SHA-256 of `prev_hash || canonical_json(payload)` |

The `prev_hash`/`hash` chain means that any retroactive edit — whether to
`response`, `timestamp`, or `metadata` — changes the hash of that entry, which
in turn invalidates `prev_hash` of every subsequent entry. Deleting or
inserting entries similarly breaks the chain. `promptlog.verify_log()` walks
the chain and reports the index of every tampered entry together with the
specific mismatch (wrong hash, wrong `prev_hash`, missing field, or invalid
JSON) [@stodden2016enhancing].

## Provider rules

Provider-specific logic is encapsulated in frozen `ProviderRule` dataclasses
that bundle a URL matcher, a request extractor, and a response extractor.
The three built-in rules cover:

- **OpenAI** — `POST /v1/chat/completions`, including Azure OpenAI endpoints
- **Anthropic** — `POST /v1/messages`
- **Google Gemini** — `POST …/models/{model}:generateContent`

Custom rules can be constructed with `make_provider()` and passed to
`install()`. Streaming responses (`text/event-stream`) are passed through
unmodified and not logged, because their incremental body cannot be buffered
without disrupting the caller.

## Graphical log viewer

`promptlog` ships a zero-dependency Tkinter GUI (`promptlog-gui`) that allows
researchers to browse log files without writing code. The viewer provides:

- A sortable table of log entries with timestamp, model, and prompt preview
- A detail pane with tabbed views of the full prompt, response, and metadata
- Full-text and model-based filtering
- One-click hash-chain verification with a plain-language result dialog
- JSONL export of the current view

# Usage

## Automatic HTTP interception

```python
import promptlog

promptlog.install("session.jsonl")

# Any urllib / requests / SDK call to a known endpoint is now auto-logged.
import openai
client = openai.OpenAI()
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Summarise transformers in one sentence."}],
)

promptlog.uninstall()
```

## Manual logging

```python
from promptlog import PromptLogger

logger = PromptLogger("session.jsonl")
logger.log(
    prompt="Explain transformer attention",
    response="Attention mechanisms allow the model to weigh token relationships.",
    model="gpt-4o",
    metadata={"temperature": 0.7},
)
```

## Integrity verification

```python
from promptlog import verify_log

result = verify_log("session.jsonl")
print(result.is_valid)           # True if chain intact
print(result.tampered_entries)   # list of tampered entry indices
```

## Graphical viewer

```bash
promptlog-gui session.jsonl
```

# Acknowledgements

The author used Claude (Anthropic) for drafting portions of this manuscript.
All scientific claims and design decisions are the author's own.

# References
