"""Allow `python -m promptlog` to invoke the CLI."""

from __future__ import annotations

import argparse
import json
import sys

from .logger import PromptLogger
from .verify import verify_log


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="promptlog",
        description="Prompt/response logger with SHA-256 tamper-evident hash chain",
    )
    parser.add_argument("log", help="Path to JSONL log file")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # log subcommand
    p_log = sub.add_parser("log", help="Append a prompt/response entry")
    p_log.add_argument("prompt", help="Prompt text")
    p_log.add_argument("response", help="Response text")
    p_log.add_argument("--model", default="", help="Model identifier")
    p_log.add_argument("--meta", default="{}", help="JSON metadata object")

    # verify subcommand
    sub.add_parser("verify", help="Verify the hash chain of the log file")

    # show subcommand
    p_show = sub.add_parser("show", help="Print log entries")
    p_show.add_argument("--limit", type=int, default=50, help="Max entries to print")
    p_show.add_argument("--json", action="store_true", help="Output as JSON array")

    # stats subcommand
    sub.add_parser("stats", help="Print summary statistics")

    args = parser.parse_args()

    if args.cmd == "log":
        try:
            meta = json.loads(args.meta)
        except json.JSONDecodeError as exc:
            sys.exit(f"Invalid --meta JSON: {exc}")
        entry = PromptLogger(args.log).log(
            prompt=args.prompt,
            response=args.response,
            model=args.model,
            metadata=meta,
        )
        print(f"Logged entry #{entry['index']}")

    elif args.cmd == "verify":
        result = verify_log(args.log)
        if result.is_valid:
            print(f"OK — {result.entries_checked} entries, hash chain valid")
        else:
            print(f"FAIL — tampered entries: {result.tampered_entries}")
            for err in result.errors:
                print(f"  {err}", file=sys.stderr)
            sys.exit(1)

    elif args.cmd == "show":
        entries: list[dict] = []
        try:
            with open(args.log, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except OSError as exc:
            sys.exit(str(exc))

        entries = entries[: args.limit]
        if getattr(args, "json"):
            print(json.dumps(entries, indent=2, ensure_ascii=False))
        else:
            for e in entries:
                ts = e.get("timestamp", "")[:19]
                model = e.get("model", "")
                prompt_preview = e.get("prompt", "").replace("\n", " ")[:60]
                print(f"[{e.get('index', '?')}] {ts}  {model}")
                print(f"  P: {prompt_preview}")

    elif args.cmd == "stats":
        entries = []
        try:
            with open(args.log, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except OSError as exc:
            sys.exit(str(exc))

        total = len(entries)
        models: dict[str, int] = {}
        for e in entries:
            m = e.get("model") or "unknown"
            models[m] = models.get(m, 0) + 1
        print(f"Total entries : {total}")
        if entries:
            print(f"First entry   : {entries[0].get('timestamp', '')}")
            print(f"Last entry    : {entries[-1].get('timestamp', '')}")
        print("Models:")
        for m, c in sorted(models.items(), key=lambda x: -x[1]):
            print(f"  {m}: {c}")


if __name__ == "__main__":
    main()
