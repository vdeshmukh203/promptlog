"""
promptlog: Structured logging for LLM prompt-response interactions.

Provides a lightweight, provider-agnostic logger that captures prompts,
responses, model metadata, and arbitrary tags with SHA-256 provenance hashes.
"""
from __future__ import annotations
import json
import sqlite3
import hashlib
import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class PromptRecord:
    """Single logged prompt-response pair with metadata."""
    prompt: str
    response: str
    model: str = ""
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())
    prompt_hash: str = field(init=False)
    response_hash: str = field(init=False)

    def __post_init__(self):
        self.prompt_hash = hashlib.sha256(self.prompt.encode()).hexdigest()
        self.response_hash = hashlib.sha256(self.response.encode()).hexdigest()


class PromptLogger:
    """Log and retrieve LLM prompt-response pairs with metadata."""

    def __init__(self, path: str = "prompts.db", backend: str = "sqlite"):
        self.path = Path(path)
        self.backend = backend
        if backend == "sqlite":
            self._conn = sqlite3.connect(str(self.path))
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS prompts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt TEXT NOT NULL, response TEXT NOT NULL,
                    model TEXT, tags TEXT, metadata TEXT,
                    timestamp TEXT, prompt_hash TEXT, response_hash TEXT
                )
            """)
            self._conn.commit()

    def log(self, prompt: str, response: str, model: str = "",
            tags: Optional[List[str]] = None, **metadata) -> int:
        """Log a prompt-response pair. Returns the record ID."""
        record = PromptRecord(
            prompt=prompt, response=response, model=model,
            tags=tags or [], metadata=metadata
        )
        if self.backend == "sqlite":
            cur = self._conn.execute(
                "INSERT INTO prompts "
                "(prompt,response,model,tags,metadata,timestamp,prompt_hash,response_hash) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (record.prompt, record.response, record.model,
                 json.dumps(record.tags), json.dumps(record.metadata),
                 record.timestamp, record.prompt_hash, record.response_hash)
            )
            self._conn.commit()
            return cur.lastrowid
        elif self.backend == "jsonl":
            with open(self.path, "a") as f:
                f.write(json.dumps(asdict(record)) + "\n")
            return -1

    def search(self, query: str = "", model: str = "",
               tag: str = "", limit: int = 100) -> List[Dict]:
        """Search logged prompts by substring, model, or tag."""
        sql = "SELECT * FROM prompts WHERE 1=1"
        params: List[Any] = []
        if query:
            sql += " AND (prompt LIKE ? OR response LIKE ?)"
            params += [f"%{query}%", f"%{query}%"]
        if model:
            sql += " AND model=?"
            params.append(model)
        if tag:
            sql += " AND tags LIKE ?"
            params.append(f'%"{tag}"%')
        sql += f" ORDER BY id DESC LIMIT {int(limit)}"
        cols = ["id","prompt","response","model","tags","metadata",
                "timestamp","prompt_hash","response_hash"]
        return [dict(zip(cols, r))
                for r in self._conn.execute(sql, params).fetchall()]

    def replay(self, record_id: int) -> Optional[PromptRecord]:
        """Retrieve a single logged record by ID for replay."""
        cols = ["id","prompt","response","model","tags","metadata",
                "timestamp","prompt_hash","response_hash"]
        row = self._conn.execute(
            "SELECT * FROM prompts WHERE id=?", (record_id,)).fetchone()
        if not row:
            return None
        d = dict(zip(cols, row))
        return PromptRecord(
            prompt=d["prompt"], response=d["response"], model=d["model"],
            tags=json.loads(d["tags"]), metadata=json.loads(d["metadata"]),
            timestamp=d["timestamp"]
        )

    def export_jsonl(self, output_path: str):
        """Export all records to JSONL format."""
        with open(output_path, "w") as f:
            for r in self.search(limit=10**9):
                f.write(json.dumps(r) + "\n")

    def close(self):
        if self.backend == "sqlite" and hasattr(self, "_conn"):
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
