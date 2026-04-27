"""Tkinter GUI for browsing and verifying promptlog JSONL files.

Launch from the command line::

    python -m promptlog.gui [path/to/session.jsonl]

or programmatically::

    from promptlog.gui import launch_gui
    launch_gui("session.jsonl")

Requirements: Python's built-in ``tkinter`` (no extra packages needed).
"""

from __future__ import annotations

import json
import os
import sys
import tkinter as tk
import tkinter.filedialog as tkfd
import tkinter.messagebox as tkmb
import tkinter.ttk as ttk
from pathlib import Path
from typing import Any

from .verify import VerifyResult, verify_log


# ---------------------------------------------------------------------------
# Colour palette (light / dark aware via ttk themes)
# ---------------------------------------------------------------------------
_VALID_BG = "#d4edda"     # pale green for verified entries
_TAMPERED_BG = "#f8d7da"  # pale red  for tampered entries
_SELECTED_BG = "#cce5ff"  # pale blue for row selection

_MONO_FONT = ("Courier New", 10) if sys.platform == "win32" else ("Monospace", 10)
_UI_FONT = ("Segoe UI", 10) if sys.platform == "win32" else ("Sans", 10)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _short(text: str, n: int = 80) -> str:
    """Truncate *text* to *n* characters for table display."""
    text = text.replace("\n", " ")
    return text[:n] + "…" if len(text) > n else text


def _load_entries(path: Path) -> list[dict[str, Any]]:
    """Parse all valid JSON lines from *path*."""
    entries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


# ---------------------------------------------------------------------------
# Detail window
# ---------------------------------------------------------------------------

class _EntryDetailWindow(tk.Toplevel):
    """Pop-up that shows the full contents of a single log entry."""

    def __init__(self, parent: tk.Widget, entry: dict[str, Any], is_tampered: bool) -> None:
        super().__init__(parent)
        self.title(f"Entry #{entry.get('index', '?')} — {'TAMPERED' if is_tampered else 'OK'}")
        self.resizable(True, True)
        self.geometry("760x540")
        self._build(entry, is_tampered)

    def _build(self, entry: dict[str, Any], is_tampered: bool) -> None:
        bg = _TAMPERED_BG if is_tampered else _VALID_BG
        header_text = (
            f"Entry {entry.get('index', '?')}  |  "
            f"Model: {entry.get('model', '')}  |  "
            f"Time: {entry.get('timestamp', '')}"
        )
        tk.Label(
            self, text=header_text, bg=bg, font=_UI_FONT, anchor="w", padx=8, pady=4,
        ).pack(fill="x")

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=6, pady=6)

        for tab_title, content in [
            ("Prompt", entry.get("prompt", "")),
            ("Response", entry.get("response", "")),
            ("Metadata", json.dumps(entry.get("metadata", {}), indent=2, ensure_ascii=False)),
            ("Chain", (
                f"Index    : {entry.get('index')}\n"
                f"Timestamp: {entry.get('timestamp')}\n"
                f"Model    : {entry.get('model')}\n\n"
                f"prev_hash:\n  {entry.get('prev_hash', '')}\n\n"
                f"hash:\n  {entry.get('hash', '')}"
            )),
        ]:
            frame = tk.Frame(notebook)
            notebook.add(frame, text=tab_title)
            text_widget = tk.Text(
                frame, wrap="word", font=_MONO_FONT, relief="flat",
                bg="#fafafa" if not is_tampered else "#fff5f5",
            )
            scroll = ttk.Scrollbar(frame, orient="vertical", command=text_widget.yview)
            text_widget.configure(yscrollcommand=scroll.set)
            scroll.pack(side="right", fill="y")
            text_widget.pack(fill="both", expand=True)
            text_widget.insert("1.0", content)
            text_widget.configure(state="disabled")

        ttk.Button(self, text="Close", command=self.destroy).pack(pady=6)


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class PromptLogViewer(tk.Tk):
    """Main GUI window for browsing and verifying promptlog JSONL files."""

    def __init__(self, initial_path: str | os.PathLike[str] | None = None) -> None:
        super().__init__()
        self.title("PromptLog Viewer")
        self.geometry("1100x640")
        self.minsize(720, 400)

        self._log_path: Path | None = None
        self._entries: list[dict[str, Any]] = []
        self._verify_result: VerifyResult | None = None
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._apply_filter())

        self._build_menu()
        self._build_toolbar()
        self._build_table()
        self._build_statusbar()

        if initial_path is not None:
            self._open_file(Path(initial_path))

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        self.configure(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open…", accelerator="Ctrl+O", command=self._browse_file)
        file_menu.add_command(label="Reload", accelerator="F5", command=self._reload)
        file_menu.add_separator()
        file_menu.add_command(label="Export filtered as JSONL…", command=self._export_filtered)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", accelerator="Ctrl+Q", command=self.quit)

        view_menu = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Verify log", command=self._run_verify)
        view_menu.add_command(label="Clear filter", command=self._clear_filter)

        self.bind_all("<Control-o>", lambda _: self._browse_file())
        self.bind_all("<F5>", lambda _: self._reload())
        self.bind_all("<Control-q>", lambda _: self.quit())

    def _build_toolbar(self) -> None:
        toolbar = tk.Frame(self, bd=1, relief="groove")
        toolbar.pack(side="top", fill="x")

        ttk.Button(toolbar, text="Open…", command=self._browse_file).pack(side="left", padx=2, pady=2)
        ttk.Button(toolbar, text="Reload", command=self._reload).pack(side="left", padx=2, pady=2)
        ttk.Button(toolbar, text="Verify", command=self._run_verify).pack(side="left", padx=2, pady=2)

        tk.Label(toolbar, text="  Filter:", font=_UI_FONT).pack(side="left")
        filter_entry = ttk.Entry(toolbar, textvariable=self._filter_var, width=35)
        filter_entry.pack(side="left", padx=2)
        ttk.Button(toolbar, text="✕", width=2, command=self._clear_filter).pack(side="left")

        self._path_label = tk.Label(toolbar, text="No file loaded", font=_UI_FONT, fg="#555")
        self._path_label.pack(side="right", padx=8)

    def _build_table(self) -> None:
        columns = ("#", "Timestamp", "Model", "Prompt", "Response", "Status")
        container = tk.Frame(self)
        container.pack(fill="both", expand=True, padx=4, pady=2)

        self._tree = ttk.Treeview(
            container,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        vsb = ttk.Scrollbar(container, orient="vertical", command=self._tree.yview)
        hsb = ttk.Scrollbar(container, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        col_widths = {"#": 50, "Timestamp": 190, "Model": 160, "Prompt": 260, "Response": 260, "Status": 80}
        for col in columns:
            self._tree.heading(col, text=col, command=lambda c=col: self._sort_by(c))
            self._tree.column(col, width=col_widths.get(col, 120), stretch=(col in ("Prompt", "Response")))

        self._tree.tag_configure("ok", background=_VALID_BG)
        self._tree.tag_configure("tampered", background=_TAMPERED_BG)
        self._tree.tag_configure("unknown", background="#ffffff")

        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self._tree.pack(fill="both", expand=True)

        self._tree.bind("<Double-1>", self._on_row_double_click)
        self._tree.bind("<Return>", self._on_row_double_click)

    def _build_statusbar(self) -> None:
        self._status_var = tk.StringVar(value="Ready — open a .jsonl file to begin")
        statusbar = tk.Label(
            self, textvariable=self._status_var,
            bd=1, relief="sunken", anchor="w", font=_UI_FONT, padx=6,
        )
        statusbar.pack(side="bottom", fill="x")

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def _browse_file(self) -> None:
        path = tkfd.askopenfilename(
            title="Open promptlog JSONL",
            filetypes=[("JSONL files", "*.jsonl"), ("All files", "*.*")],
        )
        if path:
            self._open_file(Path(path))

    def _open_file(self, path: Path) -> None:
        try:
            entries = _load_entries(path)
        except Exception as exc:
            tkmb.showerror("Error", f"Could not read {path}:\n{exc}")
            return
        self._log_path = path
        self._entries = entries
        self._verify_result = None
        self._path_label.configure(text=str(path))
        self.title(f"PromptLog Viewer — {path.name}")
        self._populate_table(entries)
        self._status_var.set(
            f"Loaded {len(entries)} entries from {path.name}  |  "
            "Use 'Verify' to check the hash chain."
        )

    def _reload(self) -> None:
        if self._log_path is None:
            return
        self._open_file(self._log_path)

    # ------------------------------------------------------------------
    # Table population and filtering
    # ------------------------------------------------------------------

    def _populate_table(
        self,
        entries: list[dict[str, Any]],
        tampered: set[int] | None = None,
    ) -> None:
        self._tree.delete(*self._tree.get_children())
        tampered = tampered or set()
        for entry in entries:
            idx = entry.get("index", "?")
            tag = "tampered" if idx in tampered else ("ok" if tampered is not None and self._verify_result else "unknown")
            self._tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    idx,
                    entry.get("timestamp", "")[:19].replace("T", " "),
                    entry.get("model", ""),
                    _short(entry.get("prompt", "")),
                    _short(entry.get("response", "")),
                    "TAMPERED" if idx in tampered else ("OK" if self._verify_result and self._verify_result.is_valid else "—"),
                ),
                tags=(tag,),
            )

    def _apply_filter(self) -> None:
        q = self._filter_var.get().lower().strip()
        if not q:
            filtered = self._entries
        else:
            filtered = [
                e for e in self._entries
                if q in e.get("prompt", "").lower()
                or q in e.get("response", "").lower()
                or q in e.get("model", "").lower()
            ]
        tampered = set(self._verify_result.tampered_entries) if self._verify_result else set()
        self._populate_table(filtered, tampered if self._verify_result else None)
        self._status_var.set(
            f"Showing {len(filtered)} of {len(self._entries)} entries"
            + (f'  |  filter: "{q}"' if q else "")
        )

    def _clear_filter(self) -> None:
        self._filter_var.set("")

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def _run_verify(self) -> None:
        if self._log_path is None:
            tkmb.showinfo("No file", "Open a .jsonl file first.")
            return
        result = verify_log(self._log_path)
        self._verify_result = result
        tampered = set(result.tampered_entries)

        # Re-colour rows
        for iid in self._tree.get_children():
            idx = int(iid)
            tag = "tampered" if idx in tampered else "ok"
            status = "TAMPERED" if idx in tampered else "OK"
            current = list(self._tree.item(iid, "values"))
            current[-1] = status
            self._tree.item(iid, values=current, tags=(tag,))

        if result.is_valid:
            msg = f"Chain valid — {result.entries_checked} entries verified."
            tkmb.showinfo("Verification", msg)
            self._status_var.set(msg)
        else:
            n = len(result.tampered_entries)
            detail = "\n".join(result.errors[:10])
            if len(result.errors) > 10:
                detail += f"\n… ({len(result.errors) - 10} more errors)"
            tkmb.showerror("Tampering detected", f"{n} tampered entr{'y' if n == 1 else 'ies'}:\n\n{detail}")
            self._status_var.set(
                f"INVALID — {n} tampered entr{'y' if n == 1 else 'ies'} "
                f"out of {result.entries_checked} checked"
            )

    # ------------------------------------------------------------------
    # Row interaction
    # ------------------------------------------------------------------

    def _on_row_double_click(self, _event: tk.Event | None = None) -> None:
        selection = self._tree.selection()
        if not selection:
            return
        iid = selection[0]
        idx = int(iid)
        entry = next((e for e in self._entries if e.get("index") == idx), None)
        if entry is None:
            return
        is_tampered = (
            self._verify_result is not None
            and idx in self._verify_result.tampered_entries
        )
        _EntryDetailWindow(self, entry, is_tampered)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _export_filtered(self) -> None:
        visible = [
            e for e in self._entries
            if self._tree.exists(str(e.get("index")))
        ]
        if not visible:
            tkmb.showinfo("Nothing to export", "No entries visible after filtering.")
            return
        dest = tkfd.asksaveasfilename(
            defaultextension=".jsonl",
            filetypes=[("JSONL", "*.jsonl"), ("All files", "*.*")],
            title="Export filtered entries",
        )
        if not dest:
            return
        with open(dest, "w", encoding="utf-8") as f:
            for entry in visible:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        tkmb.showinfo("Exported", f"Wrote {len(visible)} entries to:\n{dest}")

    # ------------------------------------------------------------------
    # Sorting
    # ------------------------------------------------------------------

    def _sort_by(self, col: str) -> None:
        """Sort table by column (toggles ascending/descending)."""
        items = [(self._tree.set(iid, col), iid) for iid in self._tree.get_children("")]
        try:
            items.sort(key=lambda t: int(t[0]) if t[0].lstrip("-").isdigit() else t[0].lower())
        except Exception:
            items.sort(key=lambda t: t[0].lower())
        for i, (_, iid) in enumerate(items):
            self._tree.move(iid, "", i)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def launch_gui(path: str | os.PathLike[str] | None = None) -> None:
    """Open the PromptLog GUI, optionally loading *path* on startup.

    Parameters
    ----------
    path:
        Optional path to a ``.jsonl`` log file to open immediately.
    """
    app = PromptLogViewer(initial_path=path)
    app.mainloop()


def main() -> None:
    """CLI entry point: ``python -m promptlog.gui [file.jsonl]``."""
    p = sys.argv[1] if len(sys.argv) > 1 else None
    launch_gui(p)


if __name__ == "__main__":
    main()
