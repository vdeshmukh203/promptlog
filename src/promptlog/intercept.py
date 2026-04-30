"""HTTP-level interceptor that auto-logs LLM API calls to a PromptLogger.

Patches :class:`http.client.HTTPConnection` (used by ``urllib``, ``requests``,
``urllib3``, and most stdlib-based HTTP code). For each POST whose host/path
matches a registered provider rule, the request and response JSON are decoded,
a record is appended to a tamper-evident JSONL log, and the response is
returned to the caller unchanged (the body is replayed from cache).

Usage::

    import promptlog
    promptlog.install("session.jsonl")
    # ... any urllib/requests call to a known LLM endpoint is now logged ...
    promptlog.uninstall()
"""

from __future__ import annotations

import http.client
import os
import sys
import time
import traceback
from typing import Iterable

from .logger import PromptLogger
from .providers import DEFAULT_PROVIDERS, ProviderRule, match_provider


class _CachedBodyResponse:
    """HTTPResponse-compatible wrapper that replays an already-read body."""

    def __init__(self, real: http.client.HTTPResponse, body: bytes) -> None:
        self._real = real
        self._body = body
        self._pos = 0
        self._manually_closed = False
        self.status = real.status
        self.reason = real.reason
        self.headers = real.headers
        self.msg = real.msg
        self.version = real.version

    def read(self, amt: int | None = None) -> bytes:
        if amt is None or amt < 0:
            data = self._body[self._pos:]
            self._pos = len(self._body)
            return data
        end = min(self._pos + amt, len(self._body))
        data = self._body[self._pos:end]
        self._pos = end
        return data

    def readline(self, limit: int = -1) -> bytes:
        idx = self._body.find(b"\n", self._pos)
        if idx == -1:
            end = len(self._body) if limit < 0 else min(self._pos + limit, len(self._body))
        else:
            end = idx + 1
            if 0 <= limit < end - self._pos:
                end = self._pos + limit
        data = self._body[self._pos:end]
        self._pos = end
        return data

    def readinto(self, buf) -> int:
        n = min(len(buf), len(self._body) - self._pos)
        buf[:n] = self._body[self._pos:self._pos + n]
        self._pos += n
        return n

    def close(self) -> None:
        self._real.close()
        self._manually_closed = True

    def __iter__(self):
        return self

    def __next__(self) -> bytes:
        line = self.readline()
        if not line:
            raise StopIteration
        return line

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    @property
    def closed(self) -> bool:
        return self._manually_closed or self._pos >= len(self._body)

    def isclosed(self) -> bool:
        return self.closed

    def getheader(self, name, default=None):
        return self._real.getheader(name, default)

    def getheaders(self):
        return self._real.getheaders()

    def info(self):
        return self.headers

    def geturl(self):
        return getattr(self._real, "url", None)

    def getcode(self) -> int:
        return self.status

    def __getattr__(self, name):
        return getattr(self._real, name)


class Interceptor:
    """Handle for an active interception. Use :func:`install` / :func:`uninstall`."""

    def __init__(self, logger: PromptLogger, providers: list[ProviderRule], debug: bool = False) -> None:
        self.logger = logger
        self.providers = list(providers)
        self.debug = debug


_INSTALLED: dict | None = None


def _normalize_body(body) -> bytes | None:
    if body is None:
        return None
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    if isinstance(body, str):
        try:
            return body.encode("utf-8")
        except UnicodeEncodeError:
            return None
    return None


def install(
    path: str | os.PathLike[str],
    *,
    providers: Iterable[ProviderRule] | None = None,
    debug: bool = False,
) -> Interceptor:
    """Patch ``http.client.HTTPConnection`` to auto-log matching LLM API calls.

    Returns an :class:`Interceptor` handle. Call :func:`uninstall` to undo.
    Streaming (``text/event-stream``) responses are passed through unmodified
    and not logged. Set *debug=True* to print extraction warnings to stderr.
    """
    global _INSTALLED
    if _INSTALLED is not None:
        raise RuntimeError(
            "promptlog.install() has already been called; call promptlog.uninstall() first"
        )

    logger = PromptLogger(path)
    rules = list(providers) if providers is not None else list(DEFAULT_PROVIDERS)
    interceptor = Interceptor(logger, rules, debug=debug)

    orig_request = http.client.HTTPConnection.request
    orig_getresponse = http.client.HTTPConnection.getresponse

    def patched_request(self, method, url, body=None, headers=None, *args, **kwargs):
        if headers is None:
            headers = {}
        try:
            scheme = "https" if isinstance(self, http.client.HTTPSConnection) else "http"
            self._promptlog_captured = {
                "method": method,
                "url": url,
                "host": self.host or "",
                "port": self.port,
                "scheme": scheme,
                "headers": dict(headers) if hasattr(headers, "items") else {},
                "body": _normalize_body(body),
                "started_at": time.monotonic(),
            }
        except Exception:
            self._promptlog_captured = None
        return orig_request(self, method, url, body, headers, *args, **kwargs)

    def patched_getresponse(self):
        response = orig_getresponse(self)
        captured = getattr(self, "_promptlog_captured", None)
        if not captured or captured.get("method", "").upper() != "POST":
            return response

        host = captured["host"] or ""
        url = captured["url"] or ""
        rule = match_provider(interceptor.providers, host, url)
        if rule is None:
            return response

        ctype = ""
        try:
            if response.headers:
                ctype = response.headers.get("Content-Type", "") or ""
        except Exception:
            ctype = ""
        if "event-stream" in ctype.lower():
            return response

        try:
            body = response.read()
        except Exception:
            return response

        latency_ms = int((time.monotonic() - captured["started_at"]) * 1000)

        try:
            req_info = rule.extract_request(captured.get("body") or b"", url)
            resp_info = rule.extract_response(body)
            metadata = {
                "provider": rule.name,
                "endpoint": f"{captured['scheme']}://{host}{url}",
                "status_code": response.status,
                "latency_ms": latency_ms,
                "request_params": req_info.get("params", {}),
                "response_usage": resp_info.get("usage"),
                "response_id": resp_info.get("id"),
                "finish_reason": resp_info.get("finish_reason"),
            }
            interceptor.logger.log(
                prompt=req_info.get("prompt", "") or "",
                response=resp_info.get("response", "") or "",
                model=resp_info.get("raw_model") or req_info.get("model", "") or "",
                metadata=metadata,
            )
        except Exception:
            if interceptor.debug:
                print(
                    f"[promptlog] WARNING: failed to extract/log {rule.name} "
                    f"response from {host}{url}:\n{traceback.format_exc()}",
                    file=sys.stderr,
                )

        return _CachedBodyResponse(response, body)

    http.client.HTTPConnection.request = patched_request
    http.client.HTTPConnection.getresponse = patched_getresponse

    _INSTALLED = {
        "interceptor": interceptor,
        "orig_request": orig_request,
        "orig_getresponse": orig_getresponse,
    }
    return interceptor


def uninstall() -> None:
    """Undo a previous :func:`install` call. No-op if not installed."""
    global _INSTALLED
    if _INSTALLED is None:
        return
    http.client.HTTPConnection.request = _INSTALLED["orig_request"]
    http.client.HTTPConnection.getresponse = _INSTALLED["orig_getresponse"]
    _INSTALLED = None


def is_installed() -> bool:
    return _INSTALLED is not None
