"""End-to-end tests for promptlog.install (HTTP interception).

Spins up a local stdlib HTTP server that mimics OpenAI, Anthropic, and Google
Gemini response shapes, makes real urllib.request calls through the patched
http.client, and verifies the auto-logged JSONL entries.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import promptlog  # noqa: E402
from promptlog.providers import (  # noqa: E402
    ANTHROPIC_MESSAGES,
    GOOGLE_GENERATE,
    OPENAI_CHAT,
    make_provider,
)


def _section(title: str) -> None:
    print(f"\n--- {title} ---")


class _FakeProviderHandler(BaseHTTPRequestHandler):
    """Routes /openai, /anthropic, /google to provider-shaped JSON responses."""

    def log_message(self, *args, **kwargs):  # silence test server noise
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or 0)
        try:
            req = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except json.JSONDecodeError:
            req = {}

        path = self.path
        if path.endswith("/openai/v1/chat/completions"):
            payload = {
                "id": "chatcmpl-test-1",
                "model": req.get("model", "gpt-4o-mini"),
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello from fake OpenAI."},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12},
            }
        elif path.endswith("/anthropic/v1/messages"):
            payload = {
                "id": "msg-test-1",
                "model": req.get("model", "claude-3-5-sonnet-20241022"),
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "Hello from fake Anthropic."}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 9, "output_tokens": 6},
            }
        elif ":generateContent" in path:
            payload = {
                "candidates": [{
                    "content": {"role": "model", "parts": [{"text": "Hello from fake Gemini."}]},
                    "finishReason": "STOP",
                }],
                "modelVersion": "gemini-2.0-flash",
                "usageMetadata": {
                    "promptTokenCount": 4,
                    "candidatesTokenCount": 5,
                    "totalTokenCount": 9,
                },
            }
        else:
            self.send_response(404)
            self.end_headers()
            return

        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _start_server() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeProviderHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    return server, base


def _local_providers():
    """Return provider rules wired to the local test server (path-only matching)."""
    return [
        make_provider(OPENAI_CHAT, match=lambda h, p: p.endswith("/openai/v1/chat/completions")),
        make_provider(ANTHROPIC_MESSAGES, match=lambda h, p: p.endswith("/anthropic/v1/messages")),
        make_provider(GOOGLE_GENERATE, match=lambda h, p: ":generateContent" in p),
    ]


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = resp.read()
        assert resp.status == 200, resp.status
    return json.loads(body.decode("utf-8"))


def _read_log(path: Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def test_intercept_three_providers(tmpdir: Path) -> None:
    _section("auto-log OpenAI + Anthropic + Gemini through urllib")
    log_path = tmpdir / "auto.jsonl"
    server, base = _start_server()
    try:
        promptlog.install(log_path, providers=_local_providers())
        try:
            openai_resp = _post_json(
                f"{base}/openai/v1/chat/completions",
                {
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "Say hi from OpenAI"}],
                    "temperature": 0.3,
                },
            )
            anthropic_resp = _post_json(
                f"{base}/anthropic/v1/messages",
                {
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 64,
                    "messages": [{"role": "user", "content": "Say hi from Anthropic"}],
                },
            )
            gemini_resp = _post_json(
                f"{base}/v1beta/models/gemini-2.0-flash:generateContent",
                {"contents": [{"role": "user", "parts": [{"text": "Say hi from Gemini"}]}]},
            )
        finally:
            promptlog.uninstall()
    finally:
        server.shutdown()

    assert openai_resp["choices"][0]["message"]["content"] == "Hello from fake OpenAI."
    assert anthropic_resp["content"][0]["text"] == "Hello from fake Anthropic."
    assert gemini_resp["candidates"][0]["content"]["parts"][0]["text"] == "Hello from fake Gemini."
    print("Caller received original response bodies unchanged.")

    entries = _read_log(log_path)
    assert len(entries) == 3, f"expected 3 logged entries, got {len(entries)}"

    by_provider = {e["metadata"]["provider"]: e for e in entries}
    assert set(by_provider) == {
        "openai.chat_completions",
        "anthropic.messages",
        "google.generate_content",
    }, by_provider

    o = by_provider["openai.chat_completions"]
    assert o["prompt"] == "Say hi from OpenAI"
    assert o["response"] == "Hello from fake OpenAI."
    assert o["model"] == "gpt-4o-mini"
    assert o["metadata"]["status_code"] == 200
    assert o["metadata"]["response_usage"]["total_tokens"] == 12
    assert o["metadata"]["request_params"]["temperature"] == 0.3
    assert o["metadata"]["finish_reason"] == "stop"

    a = by_provider["anthropic.messages"]
    assert a["prompt"] == "Say hi from Anthropic"
    assert a["response"] == "Hello from fake Anthropic."
    assert a["model"] == "claude-3-5-sonnet-20241022"
    assert a["metadata"]["response_usage"]["output_tokens"] == 6

    g = by_provider["google.generate_content"]
    assert g["prompt"] == "Say hi from Gemini"
    assert g["response"] == "Hello from fake Gemini."
    assert g["model"] == "gemini-2.0-flash"
    assert g["metadata"]["response_usage"]["totalTokenCount"] == 9

    result = promptlog.verify_log(log_path)
    assert result.is_valid, result.errors
    assert result.entries_checked == 3
    print("OK: 3 auto-captured entries, hash chain still valid.")


def test_unmatched_calls_are_not_logged(tmpdir: Path) -> None:
    _section("non-matching POSTs pass through unmodified and are not logged")
    log_path = tmpdir / "unmatched.jsonl"
    server, base = _start_server()
    try:
        promptlog.install(log_path, providers=_local_providers())
        try:
            try:
                _post_json(f"{base}/some/other/path", {"foo": "bar"})
            except urllib.error.HTTPError as exc:
                assert exc.code == 404
        finally:
            promptlog.uninstall()
    finally:
        server.shutdown()
    assert not log_path.exists() or Path(log_path).read_text(encoding="utf-8") == "", "no entries should be written"
    print("OK: unrelated traffic untouched.")


def test_uninstall_restores_original(tmpdir: Path) -> None:
    _section("uninstall restores original http.client behaviour")
    import http.client

    orig_request = http.client.HTTPConnection.request
    orig_getresponse = http.client.HTTPConnection.getresponse

    log_path = tmpdir / "restore.jsonl"
    promptlog.install(log_path, providers=_local_providers())
    assert promptlog.is_installed()
    assert http.client.HTTPConnection.request is not orig_request
    promptlog.uninstall()
    assert not promptlog.is_installed()
    assert http.client.HTTPConnection.request is orig_request
    assert http.client.HTTPConnection.getresponse is orig_getresponse
    print("OK: patches reverted cleanly.")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        test_intercept_three_providers(tmpdir)
        test_unmatched_calls_are_not_logged(tmpdir)
        test_uninstall_restores_original(tmpdir)
    print("\nAll promptlog interception tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
