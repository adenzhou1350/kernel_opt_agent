"""Write reviewed advisory feedback through the actual bounded Scout reader.

Single-writer local operation, not publication, job mutation or a quality gate.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from contextlib import closing
from urllib.parse import urlsplit

import scout_publication_context as memory

FIELDS = {"repo", "prior_hypothesis", "source_url", "reason", "reopen_when", "evidence_url"}
BOUNDARY = (
    "Stored/projected advisory context only; no model call, job mutation, "
    "publication, suppression, qualification or measured discovery benefit."
)


def canonical_source(url, repo):
    """Accept an exact public raw/blob file URL, never a branch or fork alias."""
    if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() for c in url):
        raise ValueError("source_url must be an exact same-repository GitHub file URL")
    try:
        parsed = urlsplit(url)
        parts = parsed.path.strip("/").split("/")
        if parsed.scheme != "https" or parsed.query or parsed.username or parsed.password:
            raise ValueError
        if parsed.netloc == "raw.githubusercontent.com" and not parsed.fragment:
            owner, project, revision, *path = parts
        elif parsed.netloc == "github.com" and len(parts) >= 5 and parts[2] == "blob":
            owner, project, _, revision, *path = parts
            if parsed.fragment and not re.fullmatch(r"L[1-9][0-9]*(?:-L[1-9][0-9]*)?", parsed.fragment):
                raise ValueError
        else:
            raise ValueError
        if (
            (owner + "/" + project).casefold() != repo.casefold()
            or not re.fullmatch(r"[0-9a-f]{40}", revision)
            or not path
            or any(not part or part in {".", ".."} or "\\" in part or "%" in part for part in path)
            or len("/".join(path)) > 256
        ):
            raise ValueError
    except (ValueError, AttributeError):
        raise ValueError("source_url needs HTTPS, this repository, a 40-hex commit and a safe full file path") from None
    return f"https://raw.githubusercontent.com/{owner}/{project}/{revision}/{'/'.join(path)}"


def validate_note(note):
    if not isinstance(note, dict) or set(note) != FIELDS:
        raise ValueError("note requires exactly " + ", ".join(sorted(FIELDS)))
    repo = note["repo"]
    if memory.owner_source_note_path(Path.cwd(), repo) is None:
        raise ValueError("repo must be owner/repository")
    for key, limit in (("prior_hypothesis", 200), ("reason", 1000), ("reopen_when", 1000)):
        value = note[key]
        if not isinstance(value, str) or not 0 < len(value.strip()) <= limit:
            raise ValueError(f"{key} must contain 1..{limit} characters")
        if memory.contains_local_artifact_path(value):
            raise ValueError(f"{key} contains a recognizable private artifact path")
    match = memory.advisory_evidence_match(note["evidence_url"])
    if not match or match[1].casefold() != repo.casefold():
        raise ValueError("evidence_url must be a supported same-repository public blob/commit/issue/PR/discussion URL or comment/review permalink; a personal fork is not that repository")
    result = {**note, "source_url": canonical_source(note["source_url"], repo)}
    # Test the deployed reader's actual rules, not a duplicate schema alone.
    with tempfile.TemporaryDirectory(prefix="scout-note-check-") as stage:
        path = memory.owner_source_note_path(stage, repo)
        path.parent.mkdir()
        path.write_text(json.dumps([result]), encoding="utf-8")
        if len(memory.owner_note_rows(stage, repo)) != 1:
            raise ValueError("note is not admitted by this Scout reader")
    return result


def snapshot(path):
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError("owner feedback file/directory must not be a symlink")
    if not path.exists():
        return b""
    if not path.is_file():
        raise ValueError("owner feedback path must be a regular file")
    with path.open("rb") as stream:
        raw = stream.read(memory.OWNER_NOTE_LIMIT_BYTES + 1)
    if len(raw) > memory.OWNER_NOTE_LIMIT_BYTES:
        raise ValueError("existing feedback exceeds the reader's 64 KiB cap; preserved")
    return raw


def write_note(root, note, *, expected_sha256=None):
    note = validate_note(note)
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("root must be an existing nonsymlink Scout directory")
    root = root.resolve()
    target = memory.owner_source_note_path(root, note["repo"])
    before = snapshot(target)
    before_sha = hashlib.sha256(before).hexdigest()
    if expected_sha256 is not None and expected_sha256 != before_sha:
        raise ValueError("feedback snapshot changed; read the current file before updating")
    try:
        notes = json.loads(before) if target.exists() else []
        if not isinstance(notes, list):
            raise ValueError
    except (ValueError, RecursionError):
        raise ValueError("existing feedback is malformed; preserved") from None
    # Replace only this hypothesis+file, including an older source revision.
    wanted = memory.source_paths([{"url": note["source_url"]}], note["repo"])
    def same_key(row):
        return (
            isinstance(row, dict) and row.get("repo") == note["repo"]
            and row.get("prior_hypothesis") == note["prior_hypothesis"]
            and memory.source_paths([{"url": row.get("source_url")}], note["repo"]) == wanted
        )
    matching = [row for row in notes if same_key(row)]
    # Exact repeat is byte-for-byte idempotent; don't reformat or reset recency.
    unchanged = matching == [note]
    updated = notes if unchanged else [row for row in notes if not same_key(row)] + [note]
    after = before if unchanged else (json.dumps(updated, ensure_ascii=False, indent=2) + "\n").encode()
    if len(after) > memory.OWNER_NOTE_LIMIT_BYTES:
        raise ValueError("update would exceed the reader's 64 KiB cap; nothing pruned; use --indexed for path-scoped storage")
    # Validate the complete proposed file and expose the real 350-char projection.
    with tempfile.TemporaryDirectory(prefix="scout-note-projection-") as stage:
        staged = memory.owner_source_note_path(stage, note["repo"])
        staged.parent.mkdir()
        staged.write_bytes(after)
        context = memory.owner_deferral_context(stage, note["repo"], [{"url": note["source_url"]}], prior_analysis=json.dumps({"title": note["prior_hypothesis"]}))
        projected = next((item for item in (context or {}).get("items", []) if item["prior_hypothesis"] == note["prior_hypothesis"] and item["reason"] == note["reason"][:350] and item["reopen_when"] == note["reopen_when"][:350]), None)
        if projected is None:
            raise ValueError("note is outside the reader's current context window; no write performed")
    if snapshot(target) != before:
        raise ValueError("feedback changed during validation; no write performed")
    if not unchanged:
        target.parent.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".reviewed-note-", suffix=".tmp", delete=False) as stream:
            stream.write(after)
            temporary = Path(stream.name)
        try:
            if snapshot(target) != before:
                raise ValueError("feedback changed before replacement; no write performed")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    current = memory.owner_deferral_context(root, note["repo"], [{"url": note["source_url"]}], prior_analysis=json.dumps({"title": note["prior_hypothesis"]}))
    visible = next((item for item in (current or {}).get("items", []) if item == projected), None)
    return dict(status="UNCHANGED" if unchanged else "STORED", sha256=hashlib.sha256(after).hexdigest(), source_url=note["source_url"], projection=visible, context_status="SELECTED_NOW" if visible else "NOT_SELECTED_NOW", boundary=BOUNDARY)


def _store_indexed_note(root, note, expected_sha256=None):
    """One transaction replaces only the same repository/file/hypothesis key."""
    target = memory.owner_note_index_path(root)
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValueError("owner feedback index must be a regular nonsymlink file")
    existed = target.exists()
    raw = json.dumps(note, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(raw.encode()) > memory.OWNER_INDEX_NOTE_LIMIT_BYTES:
        raise ValueError("indexed note exceeds 16 KiB")
    key = (note["repo"], next(iter(memory.source_paths(
        [{"url": note["source_url"]}], note["repo"]))), note["prior_hypothesis"])
    with closing(sqlite3.connect(target, timeout=0.1)) as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if existed and version != 1:
                raise ValueError("unknown owner feedback index schema; preserved")
            if not existed:
                db.execute("CREATE TABLE owner_notes (repo TEXT NOT NULL, source_path TEXT NOT NULL, "
                           "hypothesis TEXT NOT NULL, revision INTEGER NOT NULL, note TEXT NOT NULL, "
                           "PRIMARY KEY(repo,source_path,hypothesis))")
                db.execute("CREATE INDEX owner_notes_path ON owner_notes(repo,source_path,revision DESC)")
                db.execute("CREATE INDEX owner_notes_repo ON owner_notes(repo,revision DESC)")
                db.execute("CREATE INDEX owner_notes_revision ON owner_notes(revision DESC)")
                db.execute("PRAGMA user_version=1")
            row = db.execute("SELECT note FROM owner_notes WHERE repo=? AND source_path=? AND hypothesis=?", key).fetchone()
            if row and not isinstance(row[0], str):
                raise ValueError("indexed note is malformed; preserved")
            before = row[0].encode() if row else b""
            if expected_sha256 is not None and hashlib.sha256(before).hexdigest() != expected_sha256:
                raise ValueError("indexed note snapshot changed; read this note before updating")
            unchanged = before == raw.encode()
            if not unchanged:
                revision = db.execute("SELECT coalesce(max(revision),0)+1 FROM owner_notes").fetchone()[0]
                db.execute("INSERT INTO owner_notes VALUES (?,?,?,?,?) ON CONFLICT(repo,source_path,hypothesis) "
                           "DO UPDATE SET revision=excluded.revision,note=excluded.note", (*key, revision, raw))
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return dict(status="UNCHANGED" if unchanged else "STORED",
                sha256=hashlib.sha256(raw.encode()).hexdigest())


def indexed_projection(root, note):
    context = memory.owner_deferral_context(
        root, note["repo"], [{"url": note["source_url"]}],
        prior_analysis=json.dumps({"title": note["prior_hypothesis"]}))
    return next((item for item in (context or {}).get("items", [])
                 if item["prior_hypothesis"] == note["prior_hypothesis"]
                 and item["reason"] == note["reason"][:350]
                 and item["reopen_when"] == note["reopen_when"][:350]
                 and item["evidence_url"] == note["evidence_url"]), None)


def write_indexed_note(root, note, *, expected_sha256=None):
    """Explicit scalable writer; legacy files and raw jobs are never modified.

    expected_sha256 binds this logical note's canonical bytes, not the database
    or legacy repository file. An absent indexed note hashes as empty bytes.
    """
    note = validate_note(note)
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("root must be an existing nonsymlink Scout directory")
    root = root.resolve()
    with tempfile.TemporaryDirectory(prefix="scout-indexed-note-check-") as stage:
        _store_indexed_note(stage, note)
        if indexed_projection(stage, note) is None:
            raise ValueError("note is not projected by the indexed Scout reader; no write performed")
    result = _store_indexed_note(root, note, expected_sha256)
    projected = indexed_projection(root, note)
    return dict(**result, storage="indexed", source_url=note["source_url"],
                projection=projected,
                context_status="SELECTED_NOW" if projected else "NOT_SELECTED_NOW",
                boundary=BOUNDARY)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--note", type=Path, required=True, help="Existing six-field JSON note")
    parser.add_argument("--expected-sha256", help="Optional snapshot hash; missing target hashes as empty bytes")
    parser.add_argument("--indexed", action="store_true", help="Path-scoped SQLite storage; snapshot hash binds this note, not legacy JSON")
    args = parser.parse_args(argv)
    try:
        with args.note.open("rb") as stream:
            raw = stream.read(memory.OWNER_NOTE_LIMIT_BYTES + 1)
        if len(raw) > memory.OWNER_NOTE_LIMIT_BYTES:
            raise ValueError("input note exceeds 64 KiB")
        write = write_indexed_note if args.indexed else write_note
        result = write(args.root, json.loads(raw), expected_sha256=args.expected_sha256)
    except (OSError, ValueError, RecursionError, sqlite3.Error) as error:
        parser.exit(2, f"owner note rejected: {error}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
