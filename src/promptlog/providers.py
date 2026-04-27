"""Built-in provider rules for popular LLM HTTP APIs.

Each :class:`ProviderRule` declares:

* a URL matcher (``host, path -> bool``)
* a request extractor that pulls ``(prompt, model, params)`` from the body
* a response extractor that pulls ``(response, usage)`` from the body

Compose a custom rule with :func:`make_provider`.

Built-in rules
--------------
:data:`OPENAI_CHAT`
    ``POST /v1/chat/completions`` on ``api.openai.com`` or Azure OpenAI.
:data:`ANTHROPIC_MESSAGES`
    ``POST /v1/messages`` on ``api.anthropic.com``.
:data:`GOOGLE_GENERATE`
    ``POST /v1beta/models/{model}:generateContent`` on
    ``generativelanguage.googleapis.com``.
:data:`DEFAULT_PROVIDERS`
    List containing all three rules above, used by :func:`~promptlog.install`
    when no custom providers are specified.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ProviderRule:
    """Immutable descriptor for a single LLM provider endpoint.

    Parameters
    ----------
    name:
        Human-readable identifier used in log metadata (e.g.
        ``"openai.chat_completions"``).
    match:
        Callable ``(host: str, path: str) -> bool`` that returns ``True``
        when a request should be logged by this rule.
    extract_request:
        Callable ``(body: bytes, path: str) -> dict`` that parses the request
        body and returns at minimum ``{"prompt": str, "model": str}``.
    extract_response:
        Callable ``(body: bytes) -> dict`` that parses the response body and
        returns at minimum ``{"response": str}``.
    """

    name: str
    match: Callable[[str, str], bool]
    extract_request: Callable[[bytes, str], dict[str, Any]]
    extract_response: Callable[[bytes], dict[str, Any]]


def make_provider(base: ProviderRule, *, match: Callable[[str, str], bool]) -> ProviderRule:
    """Return a copy of *base* with a different URL matcher.

    This is the recommended way to create provider rules for testing or for
    self-hosted deployments where the hostname differs from the public API.

    Parameters
    ----------
    base:
        Existing :class:`ProviderRule` whose extractors you want to reuse.
    match:
        Replacement ``(host, path) -> bool`` function.

    Example
    -------
    >>> from promptlog.providers import OPENAI_CHAT, make_provider
    >>> local_openai = make_provider(
    ...     OPENAI_CHAT,
    ...     match=lambda h, p: h == "localhost" and p.endswith("/chat/completions"),
    ... )
    """
    return ProviderRule(base.name, match, base.extract_request, base.extract_response)


def _decode_json(body: bytes | None) -> dict[str, Any]:
    """Decode *body* as UTF-8 JSON, returning an empty dict on any error."""
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


def match_provider(providers: list[ProviderRule], host: str, path: str) -> ProviderRule | None:
    """Return the first provider whose matcher accepts ``(host, path)``.

    Matcher exceptions are caught and reported as :class:`RuntimeWarning` so
    a broken custom rule cannot silently discard log entries or crash the
    caller.

    Parameters
    ----------
    providers:
        Ordered list of :class:`ProviderRule` objects to test.
    host:
        Hostname from the HTTP request (e.g. ``"api.openai.com"``).
    path:
        URL path component (e.g. ``"/v1/chat/completions"``).

    Returns
    -------
    ProviderRule or None
        The first matching rule, or ``None`` if no rule matches.
    """
    for p in providers:
        try:
            if p.match(host, path):
                return p
        except Exception as exc:
            warnings.warn(
                f"promptlog: provider rule {p.name!r} matcher raised an exception "
                f"for host={host!r} path={path!r}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
    return None
