---
title: 'promptlog: A Python library for structured, tamper-evident logging of large language model interactions'
tags:
  - Python
  - LLM
  - logging
  - reproducibility
  - provenance
  - prompts
  - hash chain
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

`promptlog` is a Python library that provides structured, provider-agnostic logging
of interactions with large language model (LLM) APIs. Researchers and developers who
use LLMs in their workflows often lack a systematic way to record, replay, and audit
the exact prompts, parameters, and responses that produced a given result.
`promptlog` addresses this gap by intercepting API calls at the HTTP level and writing
structured JSON Lines (JSONL) records that include the full request payload, response
text, latency, token-usage statistics, and a SHA-256 hash linking each record to the
previous one [@nist2015sha]. The library supports all major LLM providers that use
HTTP-based APIs—OpenAI, Anthropic, and Google Gemini are included out of the box—and
requires no code changes beyond a single initialization call. A companion graphical
viewer (`promptlog-viewer`) allows researchers to inspect and verify logs without
writing code.

# Statement of Need

Reproducibility in LLM-based research depends on capturing not just model outputs but
the complete context of each inference call: the system prompt, user messages, model
version, temperature, and sampling parameters [@gundersen2018state; @pineau2021improving].
This is especially critical as LLMs are increasingly used in high-stakes domains such
as medicine [@kung2023chatgpt], law, and software engineering, where the ability to
audit model behaviour after the fact has direct scientific and regulatory implications.

Prompt injection and indirect prompt injection attacks [@perez2022ignore; @greshake2023not]
also motivate forensic logging: researchers need tamper-evident records to distinguish
unexpected model outputs caused by prompt manipulation from genuine model failures.

Existing approaches are insufficient for this use case:

- **General-purpose experiment trackers** such as MLflow [@zaharia2018mlflow] and
  Weights & Biases [@wandb2020] record hyperparameters and metrics but were not
  designed for full-fidelity LLM interaction capture, and they provide no cryptographic
  tamper-evidence mechanism.
- **Provider-specific observability tools** such as LangSmith [@langchain2023] are
  tied to a particular SDK or framework and cannot transparently log interactions made
  through arbitrary HTTP clients.
- **Custom logging wrappers** require modifying existing call sites and must be
  separately maintained for each provider.

`promptlog` provides a single, consistent logging interface across providers,
emitting JSONL records that can be ingested by downstream analysis tools (e.g.,
`jq`, pandas), replayed for regression testing, and archived for reproducibility
audits [@stodden2016enhancing]. The SHA-256 hash chain ensures that any
post-hoc modification—editing a response, deleting an entry, or inserting a
fabricated record—is detectable without requiring a trusted third party.

# State of the Field

Several libraries address adjacent problems. LangChain's callback system
[@langchain2023] and LlamaIndex tracing support structured logging within their
respective frameworks but do not operate at the transport layer and therefore
cannot capture interactions made through plain HTTP clients or competing SDKs.
OpenTelemetry-based solutions [@opentelemetry2021] provide distributed tracing
infrastructure but require significant configuration and do not produce
research-oriented, self-contained JSONL archives. Datasheets for Datasets
[@gebru2021datasheets] establish a conceptual standard for documenting AI data
artefacts, but provide no tooling for automatic capture.

To our knowledge, `promptlog` is the only library that combines (1) transparent,
framework-agnostic HTTP-level interception with (2) a cryptographic hash chain
for tamper detection and (3) a zero-dependency stdlib-only implementation
suitable for embedding in constrained research environments.

# Implementation

## Hash-chained JSONL format

Each log record is a JSON object appended as a single line to a `.jsonl` file.
The mandatory fields are:

| Field | Description |
|-------|-------------|
| `index` | Zero-based sequence number |
| `timestamp` | ISO-8601 UTC timestamp of the call |
| `prompt` | Last user-turn text extracted from the request |
| `response` | Model output text |
| `model` | Model identifier reported by the API |
| `metadata` | Provider name, endpoint URL, HTTP status, latency (ms), token usage, finish reason, request parameters |
| `prev_hash` | SHA-256 digest of the preceding entry (or 64 `'0'` chars for the genesis record) |
| `hash` | SHA-256 digest of `prev_hash || "\n" || canonical_json(payload)` |

The canonical serialisation uses `json.dumps` with `sort_keys=True` and
compact separators, ensuring byte-for-byte reproducibility across Python
versions and platforms. Each write is followed by `os.fsync()` to guarantee
durability before the function returns.

Verification replays the hash chain from the genesis record. Any insertion,
deletion, field modification, or re-hashing cover-up propagates a detectable
`prev_hash` mismatch to all subsequent entries.

## HTTP interception

`promptlog.install()` monkey-patches `http.client.HTTPConnection.request` and
`http.client.HTTPConnection.getresponse`. Because `urllib`, `requests`, and
`urllib3` all delegate to `http.client` internally, the patch captures traffic
from any of these libraries without requiring changes to call sites.

For each matching POST, the response body is buffered in a `_CachedBodyResponse`
wrapper that replays the bytes verbatim to the original caller; the caller
therefore receives an unmodified response object. Streaming responses
(`Content-Type: text/event-stream`) are passed through without buffering or
logging, preserving low-latency semantics for streaming use cases.

Provider matching and field extraction are isolated in a `ProviderRule` dataclass,
making it straightforward to add support for new providers or custom endpoints
without modifying library internals.

## Graphical viewer

The `promptlog-viewer` command-line entry point launches a Tkinter-based GUI
that allows researchers to open a JSONL log file, browse entries in a sortable
table with prompt and response previews, trigger hash-chain verification with
visual pass/fail highlighting, and inspect the full content—including metadata
and raw hash values—of any selected entry. The viewer requires only Python's
standard library (`tkinter` is included in all standard CPython distributions).

# Acknowledgements

The author used Claude (Anthropic) for drafting portions of this manuscript.
All scientific claims and design decisions are the author's own.

# References
