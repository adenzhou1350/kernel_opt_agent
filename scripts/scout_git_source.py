"""Prepare a reviewed public-source Scout packet from local, pinned Git objects.

No fetch, checkout, target import, model call or queue mutation. The caller must
review public provenance and contribution rules before transferring the output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from contextlib import closing
from pathlib import Path

import kimi_scout as scout
import qualification_source_bundle as bundle
from scout_requested_definition import requested_function_window


MAX_FILES = 8  # Existing supplied-source context selectors inspect eight sources.
MAX_BLOB_BYTES = 100_000  # Match the existing delivery source read budget.
MAX_RANGED_BLOB_BYTES = 1_000_000  # Explicit line-only selections; prompt cap unchanged.


def _ranges(item, path, lines):
    ranges = []
    definitions = item.get("definitions", [])
    windows = item.get("ranges", [])
    if not isinstance(definitions, list) or not isinstance(windows, list):
        raise ValueError("definitions and ranges must be lists")
    if len(definitions) + len(windows) > 16:
        raise ValueError("select at most sixteen ranges/definitions per file")
    for name in definitions:
        if (not path.endswith(".py") or not isinstance(name, str)
                or not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?", name)):
            raise ValueError("definitions require explicit Python names or Class.method")
        selected = requested_function_window(lines, f"definition({name})")
        if selected is None:
            raise ValueError(f"missing or ambiguous Python definition: {name}")
        ranges.append((selected["start_line"], selected["end_line"]))
    for window in windows:
        if not isinstance(window, dict) or set(window) != {"start", "end"}:
            raise ValueError("each line range needs start and end")
        start, end = window["start"], window["end"]
        if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines):
            raise ValueError("line range lies outside the pinned file")
        ranges.append((start, end))
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def build_packet(local_repo, spec, *, with_lessons=False):
    """Return a bounded packet; never repair/truncate source to make it fit.

    ``files`` contains literal files, with optional inclusive ``ranges`` and/or
    Python ``definitions``. Missing or ambiguous definitions reject the packet.
    Definition selection is syntax-only, not reachability or callable resolution.
    """
    if not isinstance(spec, dict) or set(spec) != {"name", "repo", "commit", "question", "files"}:
        raise ValueError("spec needs only name, repo, commit, question and files")
    repo = scout.public_repo(spec["repo"])
    if any(part in {".", ".."} for part in repo.split("/")):
        raise ValueError("invalid public repository name")
    commit = spec["commit"]
    if not bundle.full_sha1(commit):
        raise ValueError("use a full pinned commit, not a branch or abbreviated revision")
    for key in ("name", "question"):
        if not isinstance(spec[key], str) or not spec[key].strip():
            raise ValueError(f"{key} must be a nonempty string")
    files = spec["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError("select one to eight literal source files")
    by_path = {}
    for item in files:
        if not isinstance(item, dict) or "path" not in item or set(item) - {"path", "definitions", "ranges"}:
            raise ValueError("source selection needs path and optional definitions/ranges")
        path = item["path"]
        bundle.literal_source_paths([path])
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", path):
            raise ValueError("source path must be compatible with delivery raw-URL routing")
        if path in by_path:
            raise ValueError("select each file once; combine its ranges/definitions")
        by_path[path] = item
    local_repo = Path(local_repo)
    resolved = bundle.git(local_repo, "rev-parse", "--verify", commit + "^{commit}").decode().strip()
    if resolved != commit:
        raise ValueError("source identity is not this commit")
    entries = bundle.git_tree_entries(local_repo, commit, sorted(by_path))
    if {path for path, _, _ in entries} != set(by_path):
        raise ValueError("select literal files, not directories")
    if any(mode not in {"100644", "100755"} for _, mode, _ in entries):
        raise ValueError("selected source must be a regular Git file, not a symlink")
    blob_ids = {path: oid for path, _, oid in entries}
    sources = {}
    # Large native sources may be read only for explicit line windows. Keep
    # full-file/AST reads at their existing bound, including mixed packets.
    limits = {
        path: (MAX_RANGED_BLOB_BYTES if isinstance(item.get("ranges"), list)
               and item["ranges"] and not item.get("definitions") else MAX_BLOB_BYTES)
        for path, item in by_path.items()
    }
    # Reap the batch reader even when this consumer rejects UTF-8 or a range.
    with closing(bundle.iter_git_tree_blobs(
        local_repo, entries, max_blob_bytes=max(limits.values()),
        max_blob_bytes_by_path=limits,
    )) as blobs:
        for path, _, raw in blobs:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError(f"source is not UTF-8: {path}") from error
            if "\0" in text:
                raise ValueError(f"source contains NUL bytes: {path}")
            lines = text.splitlines()
            ranges = _ranges(by_path[path], path, lines)
            if ranges:
                text = "\n\n".join(
                    "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
                    for start, end in ranges
                )
            sources[path] = {
                "url": f"https://raw.githubusercontent.com/{repo}/{commit}/{path}",
                "text": text,
                "truncated": bool(ranges) and ranges != [(1, len(lines))],
                "supplied_ranges": [list(window) for window in ranges] if ranges else [[1, len(lines)]] if lines else [],
                "full_file_sha256": hashlib.sha256(raw).hexdigest(),
                "git_blob_sha1": blob_ids[path],
            }
    # Batch reads are path-sorted, but retain the owner's primary/context order.
    sources = [sources[path] for path in by_path]
    packet = {
        "name": spec["name"], "repo": repo, "commit": commit,
        "question": spec["question"], "sources": sources,
        "duplicate_search_complete": False, "related_open_items_sample": [],
        "reviewed_lessons": [],
    }
    if with_lessons:
        packet["lesson_suggestions"] = scout.lesson_suggestions(
            spec["question"], source_text="\n".join(s["text"] for s in sources),
            source_urls=[s["url"] for s in sources],
        )
    scout.fit_lesson_context(packet, scout.MAX_INPUT_BYTES, scout.SYSTEM)
    input_bytes = len((scout.SYSTEM + scout.dumps(packet)).encode("utf-8"))
    if input_bytes > scout.MAX_INPUT_BYTES:
        source_sizes = ", ".join(
            f"{path}={len(entry['text'].encode('utf-8'))}"
            for path, entry in zip(by_path, sources)
        )
        raise ValueError(
            f"packet exceeds input budget ({input_bytes} > {scout.MAX_INPUT_BYTES} "
            f"UTF-8 bytes including system and serialized metadata; "
            f"selected source text bytes: {source_sizes}); select narrower source windows"
        )
    return packet


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="existing reviewed local repository")
    parser.add_argument("--spec", type=Path, required=True, help="reviewed public packet selection JSON")
    parser.add_argument("--output", type=Path, required=True, help="fresh packet output; never enqueue")
    parser.add_argument("--lessons", action="store_true", help="optional advisory knowledge lookup")
    args = parser.parse_args(argv)
    packet = build_packet(args.repo, json.loads(args.spec.read_text(encoding="utf-8")), with_lessons=args.lessons)
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(packet, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
