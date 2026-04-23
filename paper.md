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

`promptlog` is a Python library that provides structured, provider-agnostic logging of interactions with large language model (LLM) APIs. Researchers and developers who use LLMs in their workflows often lack a systematic way to record, replay, and audit the exact prompts, parameters, and responses that produced a given result. `promptlog` addresses this gap by intercepting API calls at the HTTP level and writing structured JSON records that include the full request payload, response, latency, token counts, and a SHA-256 hash of each record for tamper detection [@nist2015sha]. The library supports all major LLM providers that use HTTP-based APIs and requires no code changes beyond a one-line initialization call.

# Statement of Need

Reproducibility in LLM-based research depends on capturing not just model outputs but the complete context of each inference call: the system prompt, user messages, model version, temperature, and sampling parameters [@gundersen2018state; @pineau2021improving]. Existing logging solutions either require provider-specific integration code, lack structured output formats, or do not capture the full HTTP payload. `promptlog` provides a single, consistent logging interface across providers, emitting JSONL records that can be ingested by downstream analysis tools, replayed for regression testing, and archived for reproducibility audits [@stodden2016enhancing].

# Acknowledgements

The author used Claude (Anthropic) for drafting portions of this manuscript. All scientific claims and design decisions are the author's own.

# References
