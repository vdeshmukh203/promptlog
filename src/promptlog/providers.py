"""Built-in provider rules for popular LLM HTTP APIs.

Each :class:`ProviderRule` declares:
  * a URL matcher (host + path -> bool)
  * a request extractor that pulls (prompt, model, params) from the body
  * a response extractor that pulls (response, usage) from the body

Compose a rule with a custom matcher via :func:`make_provider`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ProviderRule:
    name: str
    match: Callable[[str, str], bool]
    extract_request: Callable[[bytes, str], dict[str, Any]]
    extract_response: Callable[[bytes], dict[str, Any]]


def make_provider(base: ProviderRule, *, match: Callable[[str, str], bool]) -> ProviderRule:
    """Return a copy of ``base`` with a different URL matcher (useful for tests)."""
    return ProviderRule(base.name, match, base.extract_request, base.extract_response)


def _decode_json(body: bytes | None) -> dict[str, Any]:
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


# --- OpenAI: POST /v1/chat/completions ------------------------------------

def _openai_match(host: str, path: str) -> bool:
    return ("openai.com" in host or "openai.azure.com" in host) and path.endswith("/chat/completions")


def _openai_extract_request(body: bytes, path: str) -> dict[str, Any]:
    data = _decode_json(body)
    msgs = data.get("messages", []) or []
    last_user: Any = ""
    for m in reversed(msgs):
        if m.get("role") == "user":
            last_user = m.get("content", "")
            break
    if isinstance(last_user, list):
        last_user = "".join(p.get("text", "") for p in last_user if isinstance(p, dict))
    return {
        "prompt": str(last_user) if last_user is not None else "",
        "model": data.get("model", ""),
        "params": {k: v for k, v in data.items() if k != "messages"},
        "messages": msgs,
    }


def _openai_extract_response(body: bytes) -> dict[str, Any]:
    data = _decode_json(body)
    text = ""
    choices = data.get("choices") or []
    if choices:
        msg = choices[0].get("message") or {}
        c = msg.get("content")
        if isinstance(c, str):
            text = c
        elif isinstance(c, list):
            text = "".join(p.get("text", "") for p in c if isinstance(p, dict))
    return {
        "response": text,
        "usage": data.get("usage"),
        "raw_model": data.get("model"),
        "id": data.get("id"),
        "finish_reason": (choices[0].get("finish_reason") if choices else None),
    }


# --- Anthropic: POST /v1/messages -----------------------------------------

def _anthropic_match(host: str, path: str) -> bool:
    return "anthropic.com" in host and path.endswith("/messages")


def _anthropic_extract_request(body: bytes, path: str) -> dict[str, Any]:
    data = _decode_json(body)
    msgs = data.get("messages", []) or []
    last_user = ""
    for m in reversed(msgs):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                last_user = c
            elif isinstance(c, list):
                last_user = "".join(
                    p.get("text", "") for p in c
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            break
    return {
        "prompt": last_user,
        "model": data.get("model", ""),
        "params": {k: v for k, v in data.items() if k != "messages"},
        "messages": msgs,
        "system": data.get("system"),
    }


def _anthropic_extract_response(body: bytes) -> dict[str, Any]:
    data = _decode_json(body)
    blocks = data.get("content") or []
    text = "".join(
        b.get("text", "") for b in blocks
        if isinstance(b, dict) and b.get("type") == "text"
    )
    return {
        "response": text,
        "usage": data.get("usage"),
        "raw_model": data.get("model"),
        "id": data.get("id"),
        "stop_reason": data.get("stop_reason"),
    }


# --- Google Gemini: POST /v1beta/models/{model}:generateContent -----------

def _google_match(host: str, path: str) -> bool:
    return "generativelanguage.googleapis.com" in host and ":generateContent" in path


def _google_extract_request(body: bytes, path: str) -> dict[str, Any]:
    data = _decode_json(body)
    contents = data.get("contents") or []
    last_user = ""
    for c in reversed(contents):
        role = c.get("role", "user")
        if role in ("user", None):
            parts = c.get("parts") or []
            last_user = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            break
    model = ""
    if "/models/" in path:
        tail = path.split("/models/", 1)[1]
        model = tail.split(":", 1)[0]
        if "?" in model:
            model = model.split("?", 1)[0]
    return {
        "prompt": last_user,
        "model": model,
        "params": {k: v for k, v in data.items() if k != "contents"},
        "contents": contents,
    }


def _google_extract_response(body: bytes) -> dict[str, Any]:
    data = _decode_json(body)
    text = ""
    cands = data.get("candidates") or []
    if cands:
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    return {
        "response": text,
        "usage": data.get("usageMetadata"),
        "raw_model": data.get("modelVersion"),
        "finish_reason": (cands[0].get("finishReason") if cands else None),
    }


OPENAI_CHAT = ProviderRule(
    "openai.chat_completions",
    _openai_match,
    _openai_extract_request,
    _openai_extract_response,
)
ANTHROPIC_MESSAGES = ProviderRule(
    "anthropic.messages",
    _anthropic_match,
    _anthropic_extract_request,
    _anthropic_extract_response,
)
GOOGLE_GENERATE = ProviderRule(
    "google.generate_content",
    _google_match,
    _google_extract_request,
    _google_extract_response,
)

DEFAULT_PROVIDERS: list[ProviderRule] = [OPENAI_CHAT, ANTHROPIC_MESSAGES, GOOGLE_GENERATE]


def match_provider(providers, host: str, path: str) -> ProviderRule | None:
    for p in providers:
        try:
            if p.match(host, path):
                return p
        except Exception:
            continue
    return None
