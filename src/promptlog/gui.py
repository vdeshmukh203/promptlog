"""Web-based GUI for browsing and verifying promptlog JSONL files.

Launches a local HTTP server (default port 7432) and opens the browser.
Requires only the Python standard library.

Usage::

    # From the command line
    python -m promptlog.gui session.jsonl
    python -m promptlog.gui session.jsonl --port 8080 --no-browser

    # Programmatically
    from promptlog.gui import launch
    launch("session.jsonl")
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .verify import verify_log

# ---------------------------------------------------------------------------
# HTML template (single-file, no external dependencies)
# ---------------------------------------------------------------------------

_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>promptlog viewer</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
  :root {
    --bg: #f8f9fa; --surface: #fff; --border: #dee2e6;
    --primary: #0d6efd; --danger: #dc3545; --success: #198754;
    --text: #212529; --muted: #6c757d; --font: system-ui, sans-serif;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: var(--font); background: var(--bg); color: var(--text); }
  header {
    background: var(--surface); border-bottom: 1px solid var(--border);
    padding: 12px 24px; display: flex; align-items: center; gap: 16px;
    flex-wrap: wrap;
  }
  header h1 { font-size: 1.1rem; font-weight: 600; }
  .badge {
    display: inline-flex; align-items: center; gap: 4px;
    font-size: 0.78rem; font-weight: 600; padding: 3px 10px;
    border-radius: 20px; white-space: nowrap;
  }
  .badge-ok   { background: #d1e7dd; color: #0a3622; }
  .badge-fail { background: #f8d7da; color: #58151c; }
  .badge-info { background: #cfe2ff; color: #084298; }
  .controls {
    padding: 12px 24px; display: flex; gap: 10px; flex-wrap: wrap;
    background: var(--surface); border-bottom: 1px solid var(--border);
  }
  input, select {
    border: 1px solid var(--border); border-radius: 6px;
    padding: 6px 10px; font-size: 0.9rem; font-family: inherit;
    background: var(--bg);
  }
  input[type=search] { flex: 1; min-width: 200px; }
  #count { font-size: 0.85rem; color: var(--muted); align-self: center; margin-left: auto; }
  table {
    width: 100%; border-collapse: collapse; font-size: 0.88rem;
    background: var(--surface);
  }
  th {
    background: var(--bg); border-bottom: 2px solid var(--border);
    padding: 10px 12px; text-align: left; font-weight: 600;
    white-space: nowrap; position: sticky; top: 0; z-index: 1;
  }
  td { padding: 9px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }
  tr:hover td { background: #f1f3f5; }
  tr.tampered td { background: #fff3cd; }
  .mono { font-family: monospace; font-size: 0.82rem; }
  .prompt-cell, .response-cell { max-width: 340px; }
  .clamp { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 340px; }
  .expand-btn {
    background: none; border: none; cursor: pointer; color: var(--primary);
    font-size: 0.78rem; padding: 0 4px; text-decoration: underline;
  }
  dialog {
    max-width: 760px; width: 95%; border: 1px solid var(--border);
    border-radius: 10px; padding: 20px; box-shadow: 0 8px 32px rgba(0,0,0,.15);
  }
  dialog::backdrop { background: rgba(0,0,0,.4); }
  dialog h2 { font-size: 1rem; margin-bottom: 12px; }
  .field-label { font-size: 0.78rem; font-weight: 600; color: var(--muted); margin-top: 10px; }
  .field-value {
    white-space: pre-wrap; word-break: break-word;
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 6px; padding: 8px 10px; margin-top: 4px;
    font-family: monospace; font-size: 0.82rem; max-height: 280px; overflow-y: auto;
  }
  .close-btn {
    margin-top: 14px; padding: 6px 18px; border-radius: 6px;
    border: 1px solid var(--border); background: var(--bg); cursor: pointer;
    font-family: inherit; font-size: 0.9rem;
  }
  #main { overflow-x: auto; }
  .empty { padding: 40px; text-align: center; color: var(--muted); font-size: 1rem; }
</style>
</head>
<body>
<header>
  <h1>promptlog viewer</h1>
  <span id="filepath" class="badge badge-info">loading…</span>
  <span id="integrity" class="badge">—</span>
  <span id="entry-count" class="badge badge-info">—</span>
</header>

<div class="controls">
  <input type="search" id="search" placeholder="Search prompts &amp; responses…" oninput="render()"/>
  <select id="model-filter" onchange="render()"><option value="">All models</option></select>
  <span id="count"></span>
</div>

<div id="main">
  <div class="empty" id="loading">Loading…</div>
  <table id="tbl" style="display:none">
    <thead>
      <tr>
        <th>#</th>
        <th>Timestamp</th>
        <th>Model</th>
        <th>Prompt</th>
        <th>Response</th>
        <th>Latency</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</div>

<dialog id="detail">
  <h2 id="d-title">Entry</h2>
  <div class="field-label">Prompt</div>
  <div class="field-value" id="d-prompt"></div>
  <div class="field-label">Response</div>
  <div class="field-value" id="d-response"></div>
  <div class="field-label">Model</div>
  <div class="field-value" id="d-model"></div>
  <div class="field-label">Metadata</div>
  <div class="field-value" id="d-meta"></div>
  <div class="field-label">Hash</div>
  <div class="field-value mono" id="d-hash"></div>
  <button class="close-btn" onclick="document.getElementById('detail').close()">Close</button>
</dialog>

<script>
let ALL = [];
let TAMPERED = new Set();

async function load() {
  const r = await fetch('/api/entries');
  const data = await r.json();
  ALL = data.entries;
  TAMPERED = new Set(data.tampered_indices);

  document.getElementById('filepath').textContent = data.path;
  const intEl = document.getElementById('integrity');
  if (data.is_valid) {
    intEl.textContent = '✓ chain valid';
    intEl.className = 'badge badge-ok';
  } else {
    intEl.textContent = '⚠ tampered (' + TAMPERED.size + ')';
    intEl.className = 'badge badge-fail';
  }
  document.getElementById('entry-count').textContent = ALL.length + ' entries';

  // Populate model filter
  const models = [...new Set(ALL.map(e => e.model).filter(Boolean))].sort();
  const sel = document.getElementById('model-filter');
  models.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m; opt.textContent = m;
    sel.appendChild(opt);
  });

  document.getElementById('loading').style.display = 'none';
  document.getElementById('tbl').style.display = '';
  render();
}

function esc(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function render() {
  const q = document.getElementById('search').value.toLowerCase();
  const mf = document.getElementById('model-filter').value;
  let rows = ALL;
  if (q) rows = rows.filter(e =>
    (e.prompt||'').toLowerCase().includes(q) ||
    (e.response||'').toLowerCase().includes(q)
  );
  if (mf) rows = rows.filter(e => e.model === mf);
  document.getElementById('count').textContent = rows.length + ' shown';

  const tbody = document.getElementById('tbody');
  tbody.innerHTML = '';
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty">No matching entries.</td></tr>';
    return;
  }
  rows.forEach((e, i) => {
    const isTampered = TAMPERED.has(e.index);
    const latency = e.metadata && e.metadata.latency_ms != null
      ? e.metadata.latency_ms + ' ms' : '—';
    const tr = document.createElement('tr');
    if (isTampered) tr.className = 'tampered';
    tr.innerHTML =
      '<td class="mono">' + esc(e.index) + (isTampered ? ' ⚠' : '') + '</td>' +
      '<td class="mono" style="white-space:nowrap">' + esc((e.timestamp||'').replace('T',' ').slice(0,19)) + '</td>' +
      '<td>' + esc(e.model||'—') + '</td>' +
      '<td class="prompt-cell"><div class="clamp">' + esc(e.prompt||'') + '</div>' +
        '<button class="expand-btn" data-idx="' + i + '" onclick="openDetail(this)">expand</button></td>' +
      '<td class="response-cell"><div class="clamp">' + esc(e.response||'') + '</div></td>' +
      '<td class="mono">' + esc(latency) + '</td>';
    tr._entry = e;
    tbody.appendChild(tr);
  });
}

function openDetail(btn) {
  const idx = parseInt(btn.dataset.idx);
  const rows = filteredRows();
  const e = rows[idx];
  if (!e) return;
  document.getElementById('d-title').textContent =
    'Entry #' + e.index + (TAMPERED.has(e.index) ? '  ⚠ TAMPERED' : '');
  document.getElementById('d-prompt').textContent = e.prompt || '';
  document.getElementById('d-response').textContent = e.response || '';
  document.getElementById('d-model').textContent = e.model || '—';
  document.getElementById('d-meta').textContent =
    JSON.stringify(e.metadata || {}, null, 2);
  document.getElementById('d-hash').textContent =
    'prev: ' + (e.prev_hash||'—') + '\\n cur: ' + (e.hash||'—');
  document.getElementById('detail').showModal();
}

function filteredRows() {
  const q = document.getElementById('search').value.toLowerCase();
  const mf = document.getElementById('model-filter').value;
  let rows = ALL;
  if (q) rows = rows.filter(e =>
    (e.prompt||'').toLowerCase().includes(q) ||
    (e.response||'').toLowerCase().includes(q)
  );
  if (mf) rows = rows.filter(e => e.model === mf);
  return rows;
}

load();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    """Minimal HTTP handler: serves the GUI HTML and a JSON data endpoint."""

    log_path: Path
    tampered: set[int]
    is_valid: bool
    entries: list[dict[str, Any]]

    def log_message(self, *_args: Any) -> None:  # silence request logs
        pass

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", _HTML.encode("utf-8"))
        elif parsed.path == "/api/entries":
            params = parse_qs(parsed.query)
            data = {
                "path": str(self.__class__.log_path),
                "is_valid": self.__class__.is_valid,
                "tampered_indices": list(self.__class__.tampered),
                "entries": self.__class__.entries,
            }
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
        else:
            self._send(404, "text/plain", b"Not found")

    def _send(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def launch(
    path: str | os.PathLike[str],
    *,
    port: int = 7432,
    open_browser: bool = True,
) -> None:
    """Start the GUI server and (optionally) open a browser tab.

    Parameters
    ----------
    path:
        Path to the JSONL log file to view.
    port:
        TCP port for the local HTTP server (default 7432).
    open_browser:
        If *True* (default), open the system browser automatically.

    The server runs until interrupted with Ctrl-C.
    """
    log_path = Path(path)

    # Load entries
    entries: list[dict[str, Any]] = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    # Verify chain
    result = verify_log(log_path)

    # Wire data into handler class (simple class-level sharing for stdlib server)
    _Handler.log_path = log_path
    _Handler.is_valid = result.is_valid
    _Handler.tampered = set(result.tampered_entries)
    _Handler.entries = entries

    server = HTTPServer(("127.0.0.1", port), _Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"promptlog GUI → {url}  (Ctrl-C to stop)")
    print(f"  file    : {log_path.resolve()}")
    print(f"  entries : {len(entries)}")
    integrity = "valid" if result.is_valid else f"TAMPERED ({len(result.tampered_entries)} entries)"
    print(f"  chain   : {integrity}")

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


# ---------------------------------------------------------------------------
# CLI via `python -m promptlog.gui`
# ---------------------------------------------------------------------------

def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m promptlog.gui",
        description="Browse a promptlog JSONL file in your browser.",
    )
    parser.add_argument("log_file", help="Path to .jsonl log file")
    parser.add_argument("--port", type=int, default=7432, help="HTTP port (default: 7432)")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open browser automatically",
    )
    args = parser.parse_args(argv)
    launch(args.log_file, port=args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
