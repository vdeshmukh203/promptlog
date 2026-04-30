"""Tkinter GUI for viewing and verifying promptlog JSONL files.

Launch with::

    promptlog-viewer [path/to/session.jsonl]

or programmatically::

    from promptlog.gui import main
    main()
"""

from __future__ import annotations

import json
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from .verify import VerifyResult, verify_log


# ---------------------------------------------------------------------------
# Colour palette (light theme)
# ---------------------------------------------------------------------------
_CLR_OK = "#e8f5e9"         # green tint for verified entries
_CLR_TAMPERED = "#ffebee"   # red tint for tampered entries
_CLR_UNKNOWN = "#fffde7"    # yellow tint when not yet verified
_CLR_HEADER = "#1565C0"     # dark blue for section headers in detail pane
_CLR_SEP = "#9E9E9E"        # grey for separator lines


class PromptLogViewer(tk.Tk):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.title("PromptLog Viewer")
        self.geometry("1280x720")
        self.minsize(900, 550)

        self._log_path: Optional[Path] = None
        self._entries: list[dict] = []
        self._verify_result: Optional[VerifyResult] = None
        self._tampered_set: set[int] = set()

        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._build_statusbar()

        # Support passing a file path as a CLI argument.
        if len(sys.argv) > 1:
            self.after(100, lambda: self._load_file(sys.argv[1]))

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open…", accelerator="Ctrl+O", command=self._open_file)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        log_menu = tk.Menu(menubar, tearoff=0)
        log_menu.add_command(label="Verify Integrity", accelerator="Ctrl+Shift+V", command=self._verify)
        log_menu.add_command(label="Refresh", accelerator="F5", command=self._refresh)
        menubar.add_cascade(label="Log", menu=log_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About promptlog", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)
        self.bind("<Control-o>", lambda _e: self._open_file())
        self.bind("<Control-V>", lambda _e: self._verify())   # Ctrl+Shift+V
        self.bind("<F5>", lambda _e: self._refresh())

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, relief=tk.RAISED, borderwidth=1)
        bar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(bar, text="Open File", command=self._open_file).pack(side=tk.LEFT, padx=2, pady=2)
        ttk.Button(bar, text="Verify Integrity", command=self._verify).pack(side=tk.LEFT, padx=2, pady=2)
        ttk.Button(bar, text="Refresh", command=self._refresh).pack(side=tk.LEFT, padx=2, pady=2)

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=3)

        ttk.Label(bar, text="Filter:").pack(side=tk.LEFT, padx=(2, 0))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._populate_table())
        search_entry = ttk.Entry(bar, textvariable=self._search_var, width=32)
        search_entry.pack(side=tk.LEFT, padx=2, pady=2)
        ttk.Button(bar, text="✕", width=2,
                   command=lambda: self._search_var.set("")).pack(side=tk.LEFT, padx=0)

        # Legend on the right
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.RIGHT, fill=tk.Y, padx=6, pady=3)
        for label, colour in (("OK", _CLR_OK), ("Tampered", _CLR_TAMPERED), ("Unverified", _CLR_UNKNOWN)):
            swatch = tk.Label(bar, text=f"  {label}  ", background=colour, relief=tk.SUNKEN, borderwidth=1)
            swatch.pack(side=tk.RIGHT, padx=2, pady=4)

    def _build_body(self) -> None:
        pane = ttk.PanedWindow(self, orient=tk.VERTICAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # ---- Top: entries table ----
        top = ttk.Frame(pane)
        pane.add(top, weight=3)

        cols = ("idx", "timestamp", "model", "prompt", "response", "status")
        headers = ("#", "Timestamp", "Model", "Prompt preview", "Response preview", "Status")
        widths = (45, 185, 160, 310, 310, 75)

        self._tree = ttk.Treeview(top, columns=cols, show="headings", selectmode="browse")
        for col, hdr, w in zip(cols, headers, widths):
            self._tree.heading(col, text=hdr)
            self._tree.column(col, width=w, stretch=(col in ("prompt", "response")))

        sy = ttk.Scrollbar(top, orient=tk.VERTICAL, command=self._tree.yview)
        sx = ttk.Scrollbar(top, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)

        sy.pack(side=tk.RIGHT, fill=tk.Y)
        sx.pack(side=tk.BOTTOM, fill=tk.X)
        self._tree.pack(fill=tk.BOTH, expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        self._tree.tag_configure("ok",       background=_CLR_OK)
        self._tree.tag_configure("tampered", background=_CLR_TAMPERED)
        self._tree.tag_configure("unknown",  background=_CLR_UNKNOWN)

        # ---- Bottom: detail pane ----
        bottom = ttk.LabelFrame(pane, text="Entry Detail")
        pane.add(bottom, weight=2)

        self._detail = tk.Text(
            bottom,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("TkFixedFont", 10),
            relief=tk.FLAT,
            padx=6,
            pady=4,
        )
        detail_sy = ttk.Scrollbar(bottom, orient=tk.VERTICAL, command=self._detail.yview)
        self._detail.configure(yscrollcommand=detail_sy.set)
        detail_sy.pack(side=tk.RIGHT, fill=tk.Y)
        self._detail.pack(fill=tk.BOTH, expand=True)

        self._detail.tag_configure("header", font=("TkFixedFont", 10, "bold"), foreground=_CLR_HEADER)
        self._detail.tag_configure("sep",    foreground=_CLR_SEP)
        self._detail.tag_configure("hash",   font=("TkFixedFont", 9), foreground="#555555")
        self._detail.tag_configure("warn",   foreground="#b71c1c")

    def _build_statusbar(self) -> None:
        self._status_var = tk.StringVar(value="No file loaded — open a .jsonl log file to begin.")
        ttk.Label(self, textvariable=self._status_var, relief=tk.SUNKEN, anchor=tk.W,
                  padding=(4, 1)).pack(side=tk.BOTTOM, fill=tk.X)

    # ------------------------------------------------------------------
    # File actions
    # ------------------------------------------------------------------

    def _open_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open PromptLog File",
            filetypes=[
                ("JSONL files", "*.jsonl"),
                ("JSON files", "*.json"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._load_file(path)

    def _load_file(self, path: str | os.PathLike[str]) -> None:
        self._log_path = Path(path)
        self._verify_result = None
        self._tampered_set = set()
        self._load_entries()
        self._populate_table()
        self._clear_detail()
        self.title(f"PromptLog Viewer — {self._log_path.name}")
        self._status_var.set(
            f"Loaded {len(self._entries)} entr{'y' if len(self._entries) == 1 else 'ies'} "
            f"from {self._log_path}  |  Use 'Verify Integrity' to check the hash chain."
        )

    def _load_entries(self) -> None:
        self._entries = []
        if not self._log_path or not self._log_path.exists():
            return
        with self._log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    def _verify(self) -> None:
        if not self._log_path:
            messagebox.showinfo("No File", "Open a log file first.")
            return
        self._verify_result = verify_log(self._log_path)
        self._tampered_set = set(self._verify_result.tampered_entries)
        self._populate_table()
        n = self._verify_result.entries_checked
        if self._verify_result.is_valid:
            msg = f"All {n} entr{'y' if n == 1 else 'ies'} passed SHA-256 chain verification."
            self._status_var.set(f"VALID — {msg}")
            messagebox.showinfo("Integrity Verified ✓", msg)
        else:
            bad = len(self._tampered_set)
            errors_preview = "\n".join(self._verify_result.errors[:8])
            if len(self._verify_result.errors) > 8:
                errors_preview += f"\n… and {len(self._verify_result.errors) - 8} more"
            self._status_var.set(f"TAMPERED — {bad} suspicious entr{'y' if bad == 1 else 'ies'} detected")
            messagebox.showwarning(
                "Integrity Failed ✗",
                f"{bad} entr{'y' if bad == 1 else 'ies'} failed verification.\n\n{errors_preview}",
            )

    def _refresh(self) -> None:
        if self._log_path:
            prev_verify = self._verify_result
            self._load_file(self._log_path)
            if prev_verify is not None:
                self._verify()

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------

    def _populate_table(self) -> None:
        self._tree.delete(*self._tree.get_children())
        query = self._search_var.get().lower().strip() if hasattr(self, "_search_var") else ""

        for entry in self._entries:
            idx = entry.get("index", "?")
            ts = str(entry.get("timestamp", ""))[:19].replace("T", " ")
            model = entry.get("model", "")
            prompt = entry.get("prompt", "")[:100].replace("\n", " ")
            response = entry.get("response", "")[:100].replace("\n", " ")

            if query and not any(query in str(v).lower() for v in (idx, ts, model, prompt, response)):
                continue

            if self._verify_result is None:
                tag, status = "unknown", "?"
            elif isinstance(idx, int) and idx in self._tampered_set:
                tag, status = "tampered", "FAIL ✗"
            else:
                tag, status = "ok", "OK ✓"

            # Use str(idx) as the item ID so we can look entries up by index.
            self._tree.insert(
                "", tk.END,
                iid=str(idx),
                values=(idx, ts, model, prompt, response, status),
                tags=(tag,),
            )

    # ------------------------------------------------------------------
    # Detail pane
    # ------------------------------------------------------------------

    def _clear_detail(self) -> None:
        self._detail.config(state=tk.NORMAL)
        self._detail.delete("1.0", tk.END)
        self._detail.config(state=tk.DISABLED)

    def _on_select(self, _event=None) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except ValueError:
            return
        entry = next((e for e in self._entries if e.get("index") == idx), None)
        if entry is None:
            return
        self._render_detail(entry)

    def _render_detail(self, entry: dict) -> None:
        self._detail.config(state=tk.NORMAL)
        self._detail.delete("1.0", tk.END)

        is_tampered = (
            self._verify_result is not None
            and isinstance(entry.get("index"), int)
            and entry["index"] in self._tampered_set
        )

        def sep() -> None:
            self._detail.insert(tk.END, "─" * 72 + "\n", "sep")

        def section(label: str, value: str, tag: str = "") -> None:
            sep()
            self._detail.insert(tk.END, f"{label}\n", "header")
            self._detail.insert(tk.END, value + "\n\n", tag or None)

        # Integrity banner
        if self._verify_result is not None:
            if is_tampered:
                self._detail.insert(tk.END, "⚠  TAMPERED — hash chain verification FAILED for this entry\n\n", "warn")
            else:
                self._detail.insert(tk.END, "✓  Verified — hash chain is intact\n\n", "header")

        section(
            "INDEX  |  TIMESTAMP  |  MODEL",
            f"#{entry.get('index')}    {entry.get('timestamp', '')}    {entry.get('model', '')}",
        )
        section("PROMPT", entry.get("prompt", ""))
        section("RESPONSE", entry.get("response", ""))

        meta = entry.get("metadata")
        if meta:
            section("METADATA", json.dumps(meta, indent=2, ensure_ascii=False))

        sep()
        self._detail.insert(tk.END, "HASH CHAIN\n", "header")
        self._detail.insert(tk.END, f"prev_hash  {entry.get('prev_hash', '')}\n", "hash")
        self._detail.insert(tk.END, f"hash       {entry.get('hash', '')}\n", "hash")

        self._detail.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _show_about(self) -> None:
        messagebox.showinfo(
            "About promptlog",
            "promptlog — Provider-agnostic LLM interaction logger\n\n"
            "Records prompts, responses, model metadata, and timestamps\n"
            "to structured JSONL files with SHA-256 tamper detection.\n\n"
            "https://github.com/vdeshmukh203/promptlog",
        )


def main() -> None:
    """Entry point for the ``promptlog-viewer`` CLI command."""
    app = PromptLogViewer()
    app.mainloop()


if __name__ == "__main__":
    main()
