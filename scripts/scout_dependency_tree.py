"""Bounded, read-only dependency content observation; no install or execution.

A matching digest does not make a writable directory immutable, authorize its
code, bind lockfiles to installed packages, or eliminate concurrent-write races.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import time

MAX_METADATA_BYTES = 8*1024**2


def inspect_tree(root, *, max_entries=20000, max_bytes=1024**3, timeout=60):
    """Observe relative paths, regular-file bytes and in-tree symlink targets.

    Modes, owners, timestamps and hardlink aliasing are not part of the digest.
    Deadlines are cooperative; an external timeout must bound stalled OS I/O.
    This is not a filesystem sandbox or an atomic snapshot.
    """
    if (type(max_entries) is not int or not 0 < max_entries <= 50000
            or type(max_bytes) is not int or not 0 < max_bytes <= 4*1024**3
            or type(timeout) not in (int, float) or not math.isfinite(timeout)
            or not 0 < timeout <= 120):
        raise ValueError('invalid dependency observation budget')
    started = time.monotonic()
    root = Path(root).absolute()
    if root.is_symlink() or getattr(root, 'is_junction', lambda: False)():
        raise ValueError('dependency root must not itself be a link')
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('dependency root must be a directory')
    entries, total_bytes, files, links, metadata_bytes = [], 0, 0, 0, 0

    def check_time():
        if time.monotonic()-started > timeout:
            raise TimeoutError('dependency observation deadline exceeded')

    def check():
        check_time()
        if len(entries) >= max_entries:
            raise ValueError('dependency entry budget exceeded')

    def record(entry):
        nonlocal metadata_bytes
        metadata_bytes += len(json.dumps(entry, ensure_ascii=True, separators=(',', ':')))
        if metadata_bytes > MAX_METADATA_BYTES:
            raise ValueError('dependency metadata budget exceeded')
        entries.append(entry)

    pending = [root]
    while pending:
        # Retain DirEntry's cached file type instead of stat-ing every path again.
        # Any scandir/read error propagates; no silently omitted subtree.
        with os.scandir(pending.pop()) as children:
            for child in children:
                check()
                path = Path(child.path)
                relative = path.relative_to(root).as_posix()
                if os.name == 'nt' and getattr(path, 'is_junction', lambda: False)():
                    raise ValueError('dependency junctions are unsupported')
                if child.is_symlink():
                    if not path.resolve(strict=True).is_relative_to(root):
                        raise ValueError('dependency symlink escapes declared tree')
                    record((relative, 'symlink', os.readlink(path)))
                    links += 1
                elif child.is_dir(follow_symlinks=False):
                    record((relative, 'directory', ''))
                    pending.append(path)
                elif child.is_file(follow_symlinks=False):
                    digest = hashlib.sha256()
                    with path.open('rb') as stream:
                        while chunk := stream.read(256*1024):
                            check()
                            total_bytes += len(chunk)
                            if total_bytes > max_bytes:
                                raise ValueError('dependency byte budget exceeded')
                            digest.update(chunk)
                    record((relative, 'file', digest.hexdigest()))
                    files += 1
                else:
                    raise ValueError('dependency special files are unsupported')
    # Include empty directories; sorting makes traversal order irrelevant.
    check_time()
    encoded = json.dumps(sorted(entries), ensure_ascii=True, separators=(',', ':')).encode()
    check_time()
    return dict(algorithm='dependency-content-layout-v1', root=str(root),
        content_sha256=hashlib.sha256(encoded).hexdigest(), entries=len(entries),
        regular_files=files, symlinks=links, regular_file_bytes=total_bytes,
        metadata_bytes=metadata_bytes,
        elapsed_seconds=time.monotonic()-started,
        boundary='Non-atomic content/layout observation, not read-only isolation, '
                 'complete runtime identity, lockfile equivalence or execution authority.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--max-entries', type=int, default=20000)
    parser.add_argument('--max-bytes', type=int, default=1024**3)
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--expect-sha256')
    args = parser.parse_args()
    try:
        result = inspect_tree(args.root, max_entries=args.max_entries,
                              max_bytes=args.max_bytes, timeout=args.timeout)
        if args.expect_sha256 is not None and result['content_sha256'] != args.expect_sha256:
            raise ValueError('dependency content digest differs from expected observation')
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, str(error)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
