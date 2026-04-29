"""Tkinter GUI for browsing and verifying promptlog JSONL files.

Launch with:
    python -m promptlog.gui [path/to/file.jsonl]
or via the installed console script:
    promptlog-gui [path/to/file.jsonl]
"""

from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from .verify import verify_log


def _set_text(widget: tk.Text, text: str) -> None:
    widget.configure(state=tk.NORMAL)
    widget.delete("1.0", tk.END)
    widget.insert("1.0", text)
    widget.configure(state=tk.DISABLED)


def _scrolled_text(parent: tk.Widget, **kwargs) -> tk.Text:
    frame = tk.Frame(parent)
    vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL)
    text = tk.Text(frame, yscrollcommand=vsb.set, state=tk.DISABLED,
                   wrap=tk.WORD, **kwargs)
    vsb.configure(command=text.yview)
    vsb.pack(side=tk.RIGHT, fill=tk.Y)
    text.pack(fill=tk.BOTH, expand=True)
    frame.pack(fill=tk.BOTH, expand=True)
    return text


class PromptLogViewer(tk.Tk):
    """Main application window."""

    def __init__(self, initial_path: str | None = None) -> None:
        super().__init__()
        self.title("PromptLog Viewer")
        self.geometry("1200x750")
        self.minsize(800, 500)

        self._log_path: Path | None = None
        self._entries: list[dict[str, Any]] = []

        self._build_menu()
        self._build_toolbar()
        self._build_search_bar()
        self._build_main_pane()
        self._build_status_bar()

        if initial_path:
            self._load_file(Path(initial_path))

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        self.configure(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open…", accelerator="Ctrl+O", command=self._open_file)
        file_menu.add_command(label="Export JSONL…", command=self._export)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", accelerator="Ctrl+Q", command=self.destroy)

        tools_menu = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Verify Integrity", command=self._verify)
        tools_menu.add_command(label="Show Statistics", command=self._show_stats)

        self.bind_all("<Control-o>", lambda _: self._open_file())
        self.bind_all("<Control-q>", lambda _: self.destroy())

    def _build_toolbar(self) -> None:
        tb = tk.Frame(self, bd=1, relief=tk.RAISED)
        tb.pack(side=tk.TOP, fill=tk.X)
        tk.Button(tb, text="Open", width=7, command=self._open_file).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(tb, text="Verify", width=7, command=self._verify).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(tb, text="Stats", width=7, command=self._show_stats).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(tb, text="Export", width=7, command=self._export).pack(side=tk.LEFT, padx=2, pady=2)

    def _build_search_bar(self) -> None:
        bar = tk.Frame(self)
        bar.pack(side=tk.TOP, fill=tk.X, padx=6, pady=3)

        tk.Label(bar, text="Search:").pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._apply_filter())
        tk.Entry(bar, textvariable=self._search_var, width=28).pack(side=tk.LEFT, padx=4)

        tk.Label(bar, text="Model:").pack(side=tk.LEFT, padx=(8, 0))
        self._model_var = tk.StringVar()
        self._model_combo = ttk.Combobox(bar, textvariable=self._model_var, width=22, state="readonly")
        self._model_combo.pack(side=tk.LEFT, padx=4)
        self._model_combo.bind("<<ComboboxSelected>>", lambda _: self._apply_filter())

        tk.Button(bar, text="Clear", command=self._clear_filter).pack(side=tk.LEFT, padx=4)

    def _build_main_pane(self) -> None:
        pw = tk.PanedWindow(self, orient=tk.VERTICAL, sashrelief=tk.RAISED, sashwidth=5)
        pw.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        # --- entry list (top pane) ---
        list_frame = tk.Frame(pw)
        pw.add(list_frame, minsize=180)

        cols = ("index", "timestamp", "model", "prompt")
        self._tree = ttk.Treeview(list_frame, columns=cols, show="headings", selectmode="browse")
        self._tree.heading("index", text="#", anchor=tk.CENTER)
        self._tree.heading("timestamp", text="Timestamp")
        self._tree.heading("model", text="Model")
        self._tree.heading("prompt", text="Prompt")
        self._tree.column("index", width=55, anchor=tk.CENTER, stretch=False)
        self._tree.column("timestamp", width=210, stretch=False)
        self._tree.column("model", width=190, stretch=False)
        self._tree.column("prompt", width=600)

        vsb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self._tree.yview)
        hsb = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._tree.pack(fill=tk.BOTH, expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # --- detail pane (bottom pane) ---
        detail_frame = tk.Frame(pw)
        pw.add(detail_frame, minsize=200)

        nb = ttk.Notebook(detail_frame)
        nb.pack(fill=tk.BOTH, expand=True)

        # Prompt tab
        prompt_tab = tk.Frame(nb)
        nb.add(prompt_tab, text="  Prompt  ")
        self._prompt_text = _scrolled_text(prompt_tab)

        # Response tab
        resp_tab = tk.Frame(nb)
        nb.add(resp_tab, text="  Response  ")
        self._response_text = _scrolled_text(resp_tab)

        # Metadata / hashes tab
        meta_tab = tk.Frame(nb)
        nb.add(meta_tab, text="  Metadata  ")
        self._meta_text = _scrolled_text(meta_tab, font=("Courier", 10))

    def _build_status_bar(self) -> None:
        self._status_var = tk.StringVar(value="No file loaded.")
        tk.Label(self, textvariable=self._status_var, bd=1, relief=tk.SUNKEN,
                 anchor=tk.W).pack(side=tk.BOTTOM, fill=tk.X)

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def _open_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open promptlog JSONL file",
            filetypes=[("JSONL files", "*.jsonl"), ("All files", "*.*")],
        )
        if path:
            self._load_file(Path(path))

    def _load_file(self, path: Path) -> None:
        entries: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except OSError as exc:
            messagebox.showerror("Error", str(exc))
            return

        self._log_path = path
        self._entries = entries
        self.title(f"PromptLog Viewer — {path.name}")

        models = sorted({e.get("model", "") for e in entries if e.get("model")})
        self._model_combo.configure(values=["(all)"] + models)
        self._model_combo.set("(all)")
        self._search_var.set("")

        self._apply_filter()
        self._status_var.set(f"Loaded {len(entries)} entries from {path}")

    def _export(self) -> None:
        if not self._entries:
            messagebox.showwarning("No data", "Open a log file first.")
            return
        out = filedialog.asksaveasfilename(
            title="Export JSONL",
            defaultextension=".jsonl",
            filetypes=[("JSONL files", "*.jsonl"), ("All files", "*.*")],
        )
        if not out:
            return
        try:
            with open(out, "w", encoding="utf-8") as fh:
                for entry in self._entries:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            messagebox.showinfo("Exported", f"Wrote {len(self._entries)} entries to {Path(out).name}")
        except OSError as exc:
            messagebox.showerror("Error", str(exc))

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _visible_entries(self) -> list[dict[str, Any]]:
        query = self._search_var.get().lower()
        model_filter = self._model_var.get()
        out = []
        for entry in self._entries:
            if model_filter and model_filter != "(all)" and entry.get("model", "") != model_filter:
                continue
            if query:
                if query not in entry.get("prompt", "").lower() and \
                   query not in entry.get("response", "").lower():
                    continue
            out.append(entry)
        return out

    def _apply_filter(self) -> None:
        self._tree.delete(*self._tree.get_children())
        visible = self._visible_entries()
        for i, entry in enumerate(visible):
            ts = entry.get("timestamp", "")
            idx = entry.get("index", "")
            model = entry.get("model", "")
            preview = entry.get("prompt", "").replace("\n", " ")[:90]
            self._tree.insert("", tk.END, iid=str(i), values=(idx, ts, model, preview))

        total = len(self._entries)
        shown = len(visible)
        suffix = f" ({total} total)" if shown != total else ""
        self._status_var.set(f"Showing {shown} entries{suffix}" + (
            f" — {self._log_path.name}" if self._log_path else ""
        ))

    def _clear_filter(self) -> None:
        self._search_var.set("")
        self._model_var.set("(all)")

    # ------------------------------------------------------------------
    # Detail view
    # ------------------------------------------------------------------

    def _on_select(self, _event: tk.Event | None = None) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        iid = int(sel[0])
        visible = self._visible_entries()
        if iid >= len(visible):
            return
        entry = visible[iid]

        _set_text(self._prompt_text, entry.get("prompt", ""))
        _set_text(self._response_text, entry.get("response", ""))

        meta_keys = ("index", "timestamp", "model", "metadata",
                     "prev_hash", "hash")
        meta = {k: entry[k] for k in meta_keys if k in entry}
        _set_text(self._meta_text, json.dumps(meta, indent=2, ensure_ascii=False))

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def _verify(self) -> None:
        if not self._log_path:
            messagebox.showwarning("No file", "Open a log file first.")
            return
        result = verify_log(self._log_path)
        if result.is_valid:
            messagebox.showinfo(
                "Integrity OK",
                f"Hash chain verified.\n\nEntries checked: {result.entries_checked}\n"
                "No tampering detected.",
            )
        else:
            errors_preview = "\n".join(result.errors[:20])
            if len(result.errors) > 20:
                errors_preview += f"\n… and {len(result.errors) - 20} more"
            messagebox.showerror(
                "Integrity Failure",
                f"TAMPERED ENTRIES: {result.tampered_entries}\n\n{errors_preview}",
            )

    def _show_stats(self) -> None:
        if not self._entries:
            messagebox.showwarning("No data", "Open a log file first.")
            return

        total = len(self._entries)
        models: dict[str, int] = {}
        for e in self._entries:
            m = e.get("model") or "unknown"
            models[m] = models.get(m, 0) + 1

        first_ts = self._entries[0].get("timestamp", "")
        last_ts = self._entries[-1].get("timestamp", "")
        avg_prompt = sum(len(e.get("prompt", "")) for e in self._entries) / total if total else 0.0
        avg_response = sum(len(e.get("response", "")) for e in self._entries) / total if total else 0.0

        model_lines = "\n".join(
            f"  {m}: {c}" for m, c in sorted(models.items(), key=lambda x: -x[1])
        )
        msg = (
            f"Total entries : {total}\n"
            f"First entry   : {first_ts}\n"
            f"Last entry    : {last_ts}\n"
            f"Avg prompt len: {avg_prompt:.0f} chars\n"
            f"Avg resp len  : {avg_response:.0f} chars\n\n"
            f"Models:\n{model_lines}"
        )
        messagebox.showinfo("Statistics", msg)


def main() -> None:
    initial = sys.argv[1] if len(sys.argv) > 1 else None
    app = PromptLogViewer(initial_path=initial)
    app.mainloop()


if __name__ == "__main__":
    main()
