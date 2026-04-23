#!/usr/bin/env python3
"""
promptlog.py - A comprehensive prompt/response logging system with integrity verification.

Features:
- SQLite-backed storage for prompt/response pairs
- SHA-256 hashing for integrity verification
- Session-based context management
- Full-text search with filters (model, tag, date)
- JSONL export for data analysis
- CLI for direct usage
- Production-ready error handling

Usage:
    # Programmatic API
    logger = PromptLogger('logs.db')
    logger.log('What is 2+2?', '4', model='gpt-4', tags=['math'])
    results = logger.search(model='gpt-4', tag='math')

    # Context manager
    with session('my-session') as log:
        log.log('prompt', 'response')

    # CLI
    python promptlog.py log "What is 2+2?" "4" --model gpt-4 --tag math
    python promptlog.py search --model gpt-4
    python promptlog.py export output.jsonl
"""

import argparse
import contextlib
import dataclasses
import datetime
import hashlib
import json
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


@dataclasses.dataclass
class PromptRecord:
    """Immutable record of a prompt/response pair with integrity hashing."""

    prompt: str
    response: str
    model: str = ""
    tags: List[str] = dataclasses.field(default_factory=list)
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)
    timestamp: str = ""
    session_id: str = ""
    prompt_hash: str = ""
    response_hash: str = ""
    record_id: Optional[int] = None

    def __post_init__(self):
        """Compute hashes and set defaults after initialization."""
        if not self.prompt_hash:
            object.__setattr__(
                self, "prompt_hash",
                hashlib.sha256(self.prompt.encode()).hexdigest()
            )
        if not self.response_hash:
            object.__setattr__(
                self, "response_hash",
                hashlib.sha256(self.response.encode()).hexdigest()
            )
        if not self.timestamp:
            object.__setattr__(
                self, "timestamp",
                datetime.datetime.utcnow().isoformat()
            )
        if not self.session_id:
            object.__setattr__(self, "session_id", str(uuid.uuid4()))

    @staticmethod
    def _compute_hash(text: str) -> str:
        """Compute SHA-256 hash of text."""
        return hashlib.sha256(text.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Convert record to dictionary."""
        return {
            "prompt": self.prompt,
            "response": self.response,
            "model": self.model,
            "tags": self.tags,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "prompt_hash": self.prompt_hash,
            "response_hash": self.response_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PromptRecord":
        """Create record from dictionary."""
        return cls(
            prompt=data["prompt"],
            response=data["response"],
            model=data.get("model", ""),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
            timestamp=data.get("timestamp", ""),
            session_id=data.get("session_id", ""),
            prompt_hash=data.get("prompt_hash", ""),
            response_hash=data.get("response_hash", ""),
        )

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-like .get() for compatibility with dict-based code."""
        return self.to_dict().get(key, default)


class PromptLogger:
    """SQLite/JSONL-backed logger for prompt/response pairs with search and export."""

    def __init__(self, db_path: Union[str, Path] = ":memory:", backend: str = "sqlite"):
        """Initialize logger.

        Args:
            db_path: Path to SQLite database file, ':memory:', or JSONL file path.
            backend: 'sqlite' or 'jsonl'
        """
        self.db_path = str(db_path)
        self.backend = backend
        # For in-memory databases, keep a persistent connection
        self._persistent_conn: Optional[sqlite3.Connection] = None
        self._jsonl_records: List[PromptRecord] = []
        if backend == "jsonl":
            # Load existing records from JSONL file if it exists
            import pathlib as _pathlib
            p = _pathlib.Path(self.db_path)
            if p.exists():
                with open(self.db_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                self._jsonl_records.append(PromptRecord.from_dict(json.loads(line)))
                            except Exception:
                                pass
        else:
            if self.db_path == ":memory:":
                self._persistent_conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection (persistent for in-memory, new for files)."""
        if self._persistent_conn is not None:
            return self._persistent_conn
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = self._get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt TEXT NOT NULL,
                    response TEXT NOT NULL,
                    model TEXT,
                    metadata TEXT,
                    timestamp TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    response_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id INTEGER NOT NULL,
                    tag TEXT NOT NULL,
                    FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE,
                    UNIQUE(record_id, tag)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_model ON records(model)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp ON records(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session ON records(session_id)
            """)
            conn.commit()
        finally:
            if self._persistent_conn is None:
                conn.close()

    def log(
        self,
        prompt: str,
        response: str,
        model: str = "",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PromptRecord:
        """Log a prompt/response pair."""
        if tags is None:
            tags = []
        if metadata is None:
            metadata = {}

        record = PromptRecord(
            prompt=prompt,
            response=response,
            model=model,
            tags=tags,
            metadata=metadata,
        )

        if self.backend == "jsonl":
            self._jsonl_records.append(record)
            with open(self.db_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict()) + "\n")
            return record

        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO records (
                    prompt, response, model, metadata,
                    timestamp, session_id, prompt_hash, response_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.prompt,
                    record.response,
                    record.model,
                    json.dumps(record.metadata),
                    record.timestamp,
                    record.session_id,
                    record.prompt_hash,
                    record.response_hash,
                ),
            )
            record_id = cursor.lastrowid

            # Insert tags
            for tag in tags:
                conn.execute(
                    "INSERT INTO tags (record_id, tag) VALUES (?, ?)",
                    (record_id, tag),
                )

            conn.commit()
            object.__setattr__(record, "record_id", record_id)
        finally:
            if self._persistent_conn is None:
                conn.close()

        return record

    def count(self) -> int:
        """Return total number of logged records."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM records")
            return cursor.fetchone()[0]
        finally:
            if self._persistent_conn is None:
                conn.close()

    def search(
        self,
        query: str = "",
        model: str = "",
        tag: str = "",
        since: Optional[Union[str, datetime.datetime]] = None,
        limit: int = 1000,
    ) -> List[PromptRecord]:
        """Search records with optional filters."""
        if self.backend == "jsonl":
            results = list(self._jsonl_records)
            if query:
                q = query.lower()
                results = [r for r in results if q in r.prompt.lower() or q in r.response.lower()]
            if model:
                results = [r for r in results if r.model == model]
            if tag:
                results = [r for r in results if tag in r.tags]
            if since:
                since_str = since.isoformat() if isinstance(since, datetime.datetime) else since
                results = [r for r in results if r.timestamp >= since_str]
            return results[:limit]

        sql = "SELECT * FROM records WHERE 1=1"
        params: List[Any] = []

        if query:
            sql += " AND (prompt LIKE ? OR response LIKE ?)"
            search_term = f"%{query}%"
            params.extend([search_term, search_term])

        if model:
            sql += " AND model = ?"
            params.append(model)

        if since:
            if isinstance(since, datetime.datetime):
                since_str = since.isoformat()
            else:
                since_str = since
            sql += " AND timestamp >= ?"
            params.append(since_str)

        if tag:
            sql = f"""
                {sql} AND id IN (
                    SELECT record_id FROM tags WHERE tag = ?
                )
            """
            params.append(tag)

        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        records = []
        conn = self._get_connection()
        try:
            cursor = conn.execute(sql, params)
            for row in cursor.fetchall():
                record = self._row_to_record(row, conn)
                records.append(record)
        finally:
            if self._persistent_conn is None:
                conn.close()

        return records

    def _row_to_record(self, row: tuple, conn: sqlite3.Connection) -> PromptRecord:
        """Convert database row to PromptRecord."""
        (
            record_id, prompt, response, model, metadata_str,
            timestamp, session_id, prompt_hash, response_hash, _
        ) = row

        metadata = json.loads(metadata_str) if metadata_str else {}

        # Fetch tags for this record
        cursor = conn.execute(
            "SELECT tag FROM tags WHERE record_id = ? ORDER BY tag",
            (record_id,)
        )
        tags = [tag_row[0] for tag_row in cursor.fetchall()]

        return PromptRecord(
            prompt=prompt,
            response=response,
            model=model,
            tags=tags,
            metadata=metadata,
            timestamp=timestamp,
            session_id=session_id,
            prompt_hash=prompt_hash,
            response_hash=response_hash,
            record_id=record_id,
        )

    def get_by_id(self, record_id: int) -> Optional[PromptRecord]:
        """Retrieve a specific record by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM records WHERE id = ?",
                (record_id,)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_record(row, conn)
        finally:
            if self._persistent_conn is None:
                conn.close()
        return None

    def verify(self, record: PromptRecord) -> bool:
        """Verify integrity of a record by checking hashes.

        Args:
            record: PromptRecord to verify

        Returns:
            True if hashes match, False otherwise
        """
        expected_prompt_hash = hashlib.sha256(record.prompt.encode()).hexdigest()
        expected_response_hash = hashlib.sha256(record.response.encode()).hexdigest()

        return (
            record.prompt_hash == expected_prompt_hash and
            record.response_hash == expected_response_hash
        )

    def export_jsonl(self, path: Union[str, Path]) -> int:
        """Export all records to JSONL format.

        Args:
            path: Output file path

        Returns:
            Number of records exported
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        count = 0
        conn = self._get_connection()
        try:
            with open(path, "w", encoding="utf-8") as f:
                cursor = conn.execute(
                    "SELECT * FROM records ORDER BY timestamp DESC"
                )
                for row in cursor.fetchall():
                    record = self._row_to_record(row, conn)
                    f.write(json.dumps(record.to_dict()) + "\n")
                    count += 1
        finally:
            if self._persistent_conn is None:
                conn.close()

        return count

    def import_jsonl(self, path: Union[str, Path]) -> int:
        """Import records from JSONL file.

        Args:
            path: Input file path

        Returns:
            Number of records imported
        """
        path = Path(path)
        count = 0

        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    record = PromptRecord.from_dict(data)
                    self.log(
                        prompt=record.prompt,
                        response=record.response,
                        model=record.model,
                        tags=record.tags,
                        metadata=record.metadata,
                    )
                    count += 1

        return count

    def delete_by_id(self, record_id: int) -> bool:
        """Delete a record by ID.

        Args:
            record_id: ID of record to delete

        Returns:
            True if record was deleted, False if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM records WHERE id = ?",
                (record_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if self._persistent_conn is None:
                conn.close()

    def clear(self) -> None:
        """Delete all records from the database."""
        conn = self._get_connection()
        try:
            conn.execute("DELETE FROM tags")
            conn.execute("DELETE FROM records")
            conn.commit()
        finally:
            if self._persistent_conn is None:
                conn.close()

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about logged records."""
        conn = self._get_connection()
        try:
            total = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]

            cursor = conn.execute("""
                SELECT model, COUNT(*) as count
                FROM records
                GROUP BY model
                ORDER BY count DESC
            """)
            models = {row[0] or "unknown": row[1] for row in cursor.fetchall()}

            cursor = conn.execute("""
                SELECT tag, COUNT(DISTINCT record_id) as count
                FROM tags
                GROUP BY tag
                ORDER BY count DESC
            """)
            tags = {row[0]: row[1] for row in cursor.fetchall()}

            cursor = conn.execute("""
                SELECT MIN(timestamp), MAX(timestamp) FROM records
            """)
            first_ts, last_ts = cursor.fetchone()

            return {
                "total_records": total,
                "models": models,
                "tags": tags,
                "first_record": first_ts,
                "last_record": last_ts,
            }
        finally:
            if self._persistent_conn is None:
                conn.close()

    def close(self) -> None:
        """Close connections."""
        if self.backend == "jsonl":
            return  # JSONL writes are immediate; nothing to close
        if self._persistent_conn:
            self._persistent_conn.close()
            self._persistent_conn = None

    def __enter__(self) -> "PromptLogger":
        """Support use as context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close on context manager exit."""
        self.close()
        return False


# Global logger instance for session context manager
_default_logger: Optional[PromptLogger] = None


@contextlib.contextmanager
def session(
    session_name: str,
    db_path: Union[str, Path] = "promptlog.db"
):
    """Context manager for session-based logging.

    Example:
        with session('my-session') as log:
            log.log('prompt text', 'response text')

    Args:
        session_name: Identifier for this session
        db_path: Path to database file

    Yields:
        PromptLogger instance
    """
    logger = PromptLogger(db_path)
    try:
        yield logger
    finally:
        logger.close()


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Prompt logging system with integrity verification",
        prog="promptlog",
    )

    parser.add_argument(
        "--db",
        default="promptlog.db",
        help="Path to SQLite database (default: promptlog.db)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # log subcommand
    log_parser = subparsers.add_parser("log", help="Log a prompt/response pair")
    log_parser.add_argument("prompt", help="The prompt text")
    log_parser.add_argument("response", help="The response text")
    log_parser.add_argument("--model", default="", help="Model identifier")
    log_parser.add_argument(
        "--tag",
        action="append",
        default=[],
        help="Tag for categorization (can be used multiple times)",
    )
    log_parser.add_argument(
        "--metadata",
        help="JSON metadata",
    )

    # search subcommand
    search_parser = subparsers.add_parser("search", help="Search logged records")
    search_parser.add_argument("--query", default="", help="Full-text search term")
    search_parser.add_argument("--model", default="", help="Filter by model")
    search_parser.add_argument("--tag", default="", help="Filter by tag")
    search_parser.add_argument("--since", default="", help="Filter by timestamp (ISO format)")
    search_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum results to return",
    )
    search_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    # export subcommand
    export_parser = subparsers.add_parser("export", help="Export records to JSONL")
    export_parser.add_argument("output", help="Output file path")

    # import subcommand
    import_parser = subparsers.add_parser("import", help="Import records from JSONL")
    import_parser.add_argument("input", help="Input file path")

    # stats subcommand
    stats_parser = subparsers.add_parser("stats", help="Show database statistics")

    # clear subcommand
    clear_parser = subparsers.add_parser("clear", help="Delete all records (use with caution)")

    args = parser.parse_args()

    logger = PromptLogger(args.db)

    try:
        if args.command == "log":
            metadata = {}
            if args.metadata:
                metadata = json.loads(args.metadata)

            record = logger.log(
                prompt=args.prompt,
                response=args.response,
                model=args.model,
                tags=args.tag,
                metadata=metadata,
            )
            print(f"Logged record {record.record_id}")
            print(f"  Prompt hash: {record.prompt_hash[:16]}...")
            print(f"  Response hash: {record.response_hash[:16]}...")

        elif args.command == "search":
            results = logger.search(
                query=args.query,
                model=args.model,
                tag=args.tag,
                since=args.since if args.since else None,
                limit=args.limit,
            )

            if args.json:
                output = [r.to_dict() for r in results]
                print(json.dumps(output, indent=2))
            else:
                print(f"Found {len(results)} records")
                for i, record in enumerate(results, 1):
                    print(f"\n[{i}] {record.timestamp} | {record.model}")
                    print(f"    Prompt: {record.prompt[:60]}...")
                    print(f"    Response: {record.response[:60]}...")
                    if record.tags:
                        print(f"    Tags: {', '.join(record.tags)}")

        elif args.command == "export":
            count = logger.export_jsonl(args.output)
            print(f"Exported {count} records to {args.output}")

        elif args.command == "import":
            count = logger.import_jsonl(args.input)
            print(f"Imported {count} records from {args.input}")

        elif args.command == "stats":
            stats = logger.get_stats()
            print(f"Total records: {stats['total_records']}")
            print(f"Date range: {stats['first_record']} to {stats['last_record']}")
            if stats['models']:
                print("\nRecords by model:")
                for model, count in sorted(stats['models'].items(), key=lambda x: x[1], reverse=True):
                    print(f"  {model}: {count}")
            if stats['tags']:
                print("\nRecords by tag:")
                for tag, count in sorted(stats['tags'].items(), key=lambda x: x[1], reverse=True):
                    print(f"  {tag}: {count}")

        elif args.command == "clear":
            response = input("Delete all records? Type 'yes' to confirm: ")
            if response.lower() == "yes":
                logger.clear()
                print("All records deleted")
            else:
                print("Cancelled")

        else:
            parser.print_help()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        logger.close()


if __name__ == "__main__":
    main()
