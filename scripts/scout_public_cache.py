"""Lossless, bounded compression for regenerable public-context JSON caches."""

from __future__ import annotations

import argparse
import errno
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

LIMIT = 20_000_000
NAME = re.compile(r"[a-z][a-z-]*-[0-9a-f]{64}\.json")


def read_cache(path, limit=LIMIT):
    """Prefer the current plain entry; never resurrect an older compressed alias."""
    path = Path(path)
    opener = path.open
    if not path.exists():
        opener = lambda mode: gzip.open(path.with_suffix(".json.gz"), mode)
    with opener("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("public cache exceeds read budget")
    return data


def compress_entry(path):
    """Replace only after exact round-trip and unchanged-source checks.

    Run maintenance with the controller stopped. The .gz retains the original
    bytes, including formatting; decompression recovers the original file.
    """
    path = Path(path)
    if not NAME.fullmatch(path.name) or path.is_symlink():
        raise ValueError("not a regular public-cache entry")
    before = path.stat()
    if not 0 < before.st_size <= LIMIT:
        return 0
    original = read_cache(path)
    if not isinstance(json.loads(original), dict):
        raise ValueError("cache entry must be a JSON object")
    packed = gzip.compress(original, compresslevel=6, mtime=0)
    if len(packed) >= len(original):
        return 0
    destination = path.with_suffix(".json.gz")
    temporary = None
    try:
        if destination.exists():
            if destination.is_symlink():
                raise ValueError("compressed cache is a symlink")
            with gzip.open(destination, "rb") as stream:
                if stream.read(LIMIT + 1) != original:
                    raise ValueError("conflicting compressed cache")
        else:
            with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".cache-tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(packed)
                stream.flush()
                os.fsync(stream.fileno())
            with gzip.open(temporary, "rb") as stream:
                if stream.read(LIMIT + 1) != original:
                    raise ValueError("compressed round-trip mismatch")
            os.replace(temporary, destination)
            temporary = None
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or path.read_bytes() != original:
            raise ValueError("cache changed during compression; plain entry preserved")
        path.unlink()
        return len(original) - destination.stat().st_size
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--max-files", type=int, default=2000)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--min-bytes", type=int, default=262144)
    args = parser.parse_args()
    if args.cache.name != "public-cache" or args.cache.is_symlink() or not args.cache.is_dir():
        parser.error("requires an existing non-symlink public-cache directory")
    if not 1 <= args.max_files <= 200000 or not 1 <= args.seconds <= 3600 or args.min_bytes < 0:
        parser.error("invalid maintenance budget")
    start = time.monotonic()
    free_before = shutil.disk_usage(args.cache).free
    stopped = None
    attempted = errors = saved = 0
    with os.scandir(args.cache) as entries:
        for entry in entries:
            if attempted >= args.max_files or time.monotonic() - start >= args.seconds:
                break
            if not NAME.fullmatch(entry.name) or not entry.is_file(follow_symlinks=False):
                continue
            if entry.stat(follow_symlinks=False).st_size < args.min_bytes:
                continue
            # Existing NTFS compression can make logical savings misleading.
            # Keep room for the verified replacement rather than filling disk.
            if shutil.disk_usage(args.cache).free < 2 * LIMIT:
                stopped = "insufficient temporary disk headroom"
                break
            attempted += 1
            try:
                saved += compress_entry(Path(entry.path))
            except (OSError, ValueError, EOFError) as exc:
                errors += 1
                if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
                    stopped = "disk full; originals preserved"
                    break
    print(json.dumps({"attempted": attempted, "errors": errors, "logical_saved_bytes": saved,
                      "free_bytes_before": free_before,
                      "free_bytes_after": shutil.disk_usage(args.cache).free,
                      "stopped": stopped, "wall_seconds": round(time.monotonic() - start, 3)}))


if __name__ == "__main__":
    main()
