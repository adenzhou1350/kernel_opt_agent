"""Explicit one-time Scout history index maintenance (no provider/GPU calls).

Building scans the inbox once and holds its SQLite writer lock. Run during a
quiet maintenance window, not automatically on worker/dashboard startup.
"""

import argparse
import json
import sqlite3
import time
from pathlib import Path

from kimi_scout_dashboard import ACTIVITY_FIELDS, ACTIVITY_INDEX


def build_index(root, timeout_seconds=60):
    if not 0 < timeout_seconds <= 3600:
        raise ValueError("timeout_seconds must be in (0, 3600]")
    database = (Path(root) / "scout.sqlite").resolve()
    started = time.monotonic()
    deadline = started + timeout_seconds
    # mode=rw deliberately refuses to create an empty inbox at a typoed path.
    db = sqlite3.connect(
        database.as_uri() + "?mode=rw", uri=True, timeout=min(2, timeout_seconds)
    )
    try:
        db.execute("PRAGMA cache_size=-2048")
        db.execute("PRAGMA temp_store=FILE")
        db.set_progress_handler(lambda: time.monotonic() >= deadline, 1000)
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            f"CREATE INDEX IF NOT EXISTS {ACTIVITY_INDEX} ON jobs("
            + ",".join(expression for _, expression in ACTIVITY_FIELDS)
            + ")"
        )
        db.commit()
    except Exception:
        db.set_progress_handler(None, 0)
        db.rollback()
        raise
    finally:
        db.close()
    return {"index": ACTIVITY_INDEX, "elapsed_seconds": time.monotonic() - started}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build_index(args.root, args.timeout_seconds)))
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
