#!/usr/bin/env python3
"""A small run notebook. Recorded judgments and file hashes are not test proofs.

Run and evidence paths are resolved relative to the caller's current directory.
Commands are descriptions only; this module never executes them. One writer at
a time may update a notebook; a busy lock is reported rather than retried.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit


CONTEXT = ("source", "workload", "hardware")
KINDS = ("baseline", "correctness", "inspection", "performance", "decision")
DECISIONS = ("ACCEPT", "REJECT", "INCONCLUSIVE")
NOTE = (
    "Status is the last explicitly recorded judgment, not automatic PR "
    "readiness. Evidence checks establish file identity only, not "
    "correctness, performance, or human review."
)


def nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value


def check_timestamp(value):
    nonempty(value, "timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")


def check_pr(value):
    nonempty(value, "pr")
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("pr must be an HTTP(S) URL")


def check_record(entry):
    if not isinstance(entry, dict):
        raise ValueError("record must be an object")
    if entry.get("kind") not in KINDS:
        raise ValueError("invalid record kind")
    nonempty(entry.get("summary"), "summary")
    check_timestamp(entry.get("at"))
    context = entry.get("context")
    if not isinstance(context, dict):
        raise ValueError("record context must be an object")
    for field in CONTEXT:
        nonempty(context.get(field), field)
    evidence = entry.get("evidence")
    if evidence is None:
        if entry["kind"] != "decision":
            raise ValueError(f"{entry['kind']} requires an evidence file")
    else:
        if not isinstance(evidence, dict):
            raise ValueError("evidence must be an object")
        nonempty(evidence.get("path"), "evidence path")
        digest = evidence.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid evidence SHA-256")
    if entry.get("command") is not None:
        nonempty(entry["command"], "command")
    if entry.get("status") is not None:
        if entry["kind"] != "decision" or entry["status"] not in DECISIONS:
            raise ValueError("only a decision may set ACCEPT, REJECT, or INCONCLUSIVE")
    if entry.get("pr") is not None:
        if entry["kind"] != "decision":
            raise ValueError("only a decision may link a PR")
        check_pr(entry["pr"])
    candidate = entry.get("candidate")
    if candidate is not None:
        if entry["kind"] != "decision" or entry.get("status") not in DECISIONS:
            raise ValueError("candidate requires an explicit decision")
        if not isinstance(candidate, dict):
            raise ValueError("candidate must be an object")
        nonempty(candidate.get("family"), "candidate family")
        nonempty(candidate.get("path"), "candidate path")
        if not re.fullmatch(r"[0-9a-f]{64}", str(candidate.get("sha256", ""))):
            raise ValueError("invalid candidate SHA-256")
        latency = candidate.get("latency_us")
        if latency is not None and (isinstance(latency, bool) or not isinstance(latency, (int, float))
                                    or not math.isfinite(latency) or latency <= 0):
            raise ValueError("candidate latency must be finite and positive")
        if entry["status"] == "ACCEPT":
            if latency is None or entry.get("evidence") is None:
                raise ValueError("accepted candidate requires latency and evidence")
            if any(entry["context"][key] == "UNKNOWN" for key in ("workload", "hardware")):
                raise ValueError("accepted candidate requires workload and hardware context")


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_run(path):
    try:
        state = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys
        )
        if not isinstance(state, dict):
            raise ValueError("run must be an object")
        for field in ("objective", *CONTEXT):
            nonempty(state.get(field), field)
        for field in ("created_at", "updated_at"):
            check_timestamp(state.get(field))
        if not isinstance(state.get("records"), list):
            raise ValueError("records must be a list")
        expected_status = "OPEN"
        for entry in state["records"]:
            check_record(entry)
            if entry.get("status") is not None:
                expected_status = entry["status"]
        if state.get("status") != expected_status:
            raise ValueError("status does not match the last recorded decision")
        return state
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"invalid notebook {path}: {exc}") from exc


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def writer(path):
    lock = path.with_name(".worklog.lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError(
            f"notebook is busy: {lock}; check for an active writer"
        ) from exc
    os.close(fd)
    try:
        yield
    finally:
        lock.unlink()


def write_run(path, state):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=".worklog-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(state, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def now():
    return datetime.now(timezone.utc).isoformat()


def frontier(state):
    """Show declared passing search routes; never infer correctness from timing."""
    latest = {}
    for index, entry in enumerate(state["records"]):
        candidate = entry.get("candidate")
        if candidate:
            key = (entry["context"]["workload"], entry["context"]["hardware"], candidate["path"])
            latest[key] = (index, entry)
    groups, excluded = {}, []
    for (workload, hardware, _), (index, entry) in latest.items():
        candidate = entry["candidate"]
        if entry["status"] != "ACCEPT":
            excluded.append({"record": index, "reason": entry["status"]})
            continue
        reason = None
        for identity in (candidate, entry["evidence"]):
            try:
                if file_hash(Path(identity["path"])) != identity["sha256"]:
                    reason = "source or evidence changed"
            except OSError:
                reason = "source or evidence unavailable"
        if reason:
            excluded.append({"record": index, "reason": reason})
            continue
        families = groups.setdefault((workload, hardware), {})
        current = families.get(candidate["family"])
        member = {**candidate, "record": index, "evidence": entry["evidence"], "summary": entry["summary"]}
        if current is None or member["latency_us"] <= current["latency_us"]:
            families[candidate["family"]] = member
    result = []
    for (workload, hardware), families in groups.items():
        members = sorted(families.values(), key=lambda item: item["latency_us"])
        result.append({"workload": workload, "hardware": hardware, "members": members,
                       "fastest_record": members[0]["record"]})
    return {"groups": result, "excluded": excluded,
            "note": "Explicit ACCEPT judgments with matching file identities only; not automatic proof. "
                    "Keep the best measured member per mechanism family, including slower distinct routes. "
                    "Only identical workload/hardware context strings are compared."}


def execute(args):
    directory = Path(args.run).expanduser().resolve()
    path = directory / "run.json"
    if args.action == "frontier":
        return frontier(read_run(path))
    if args.action == "status":
        state = read_run(path)
        checks = []
        for index, entry in enumerate(state["records"], 1):
            evidence = entry.get("evidence")
            if evidence is None:
                continue
            artifact = Path(evidence["path"])
            try:
                outcome = (
                    "MATCH" if file_hash(artifact) == evidence["sha256"] else "CHANGED"
                )
            except FileNotFoundError:
                outcome = "MISSING"
            except OSError:
                outcome = "UNREADABLE"
            checks.append({"record": index, "path": str(artifact), "status": outcome})
        return {**state, "evidence_checks": checks, "note": NOTE}

    if args.action == "init":
        nonempty(args.objective, "objective")
        context = {
            field: getattr(args, field)
            if getattr(args, field) is not None
            else "UNKNOWN"
            for field in CONTEXT
        }
        for field, value in context.items():
            nonempty(value, field)
        directory.mkdir(parents=True, exist_ok=True)
        with writer(path):
            if path.exists() or path.is_symlink():
                raise ValueError(f"notebook already exists: {path}")
            timestamp = now()
            state = {
                "objective": args.objective,
                **context,
                "status": "OPEN",
                "created_at": timestamp,
                "updated_at": timestamp,
                "records": [],
            }
            write_run(path, state)
        return state

    with writer(path):
        state = read_run(path)
        context = {
            field: getattr(args, field)
            if getattr(args, field) is not None
            else state[field]
            for field in CONTEXT
        }
        evidence = None
        if args.evidence is not None:
            artifact = Path(args.evidence).expanduser().resolve()
            if artifact == path:
                raise ValueError("run.json cannot be its own evidence")
            evidence = {"path": str(artifact), "sha256": file_hash(artifact)}
        entry = {
            "kind": args.kind,
            "summary": args.summary,
            "at": now(),
            "context": context,
            "evidence": evidence,
            "command": args.command,
            "status": args.status,
            "pr": args.pr,
        }
        if any(value is not None for value in (args.candidate, args.family, args.latency_us)):
            if args.candidate is None or args.family is None:
                raise ValueError("candidate and family must be supplied together")
            candidate = Path(args.candidate).expanduser().resolve()
            if candidate == path:
                raise ValueError("run.json cannot be a candidate")
            entry["candidate"] = {"path": str(candidate), "sha256": file_hash(candidate),
                                  "family": args.family, "latency_us": args.latency_us}
        check_record(entry)
        state["records"].append(entry)
        state.update(context)
        state["updated_at"] = entry["at"]
        if args.status is not None:
            state["status"] = args.status
        write_run(path, state)
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=NOTE)
    subparsers = parser.add_subparsers(dest="action", required=True)
    initialize = subparsers.add_parser(
        "init", help="create a notebook without overwriting"
    )
    initialize.add_argument("--objective", required=True)
    record = subparsers.add_parser(
        "record", help="append evidence or an explicit judgment"
    )
    record.add_argument("--kind", required=True, choices=KINDS)
    record.add_argument("--summary", required=True)
    record.add_argument(
        "--evidence", help="existing file; required except for decisions"
    )
    record.add_argument(
        "--command", help="literal reproduction command; never executed"
    )
    record.add_argument(
        "--status", choices=DECISIONS, help="decision only; explicit judgment"
    )
    record.add_argument("--pr", help="decision only; HTTP(S) PR URL")
    record.add_argument("--candidate", help="optional candidate source file for an explicit decision")
    record.add_argument("--family", help="optimization mechanism, e.g. vectorized or persistent")
    record.add_argument("--latency-us", type=float, help="measured latency under the exact workload/hardware context")
    status = subparsers.add_parser(
        "status", help="show notes and current evidence file identities"
    )
    routes = subparsers.add_parser("frontier", help="show measured accepted candidates, retaining distinct mechanisms")
    for command in (initialize, record, status, routes):
        command.add_argument(
            "--run", required=True, help="run directory, containing run.json"
        )
    for command in (initialize, record):
        for field in CONTEXT:
            command.add_argument(
                f"--{field}", help="plain text context; unspecified starts UNKNOWN"
            )
    args = parser.parse_args(argv)
    try:
        result = execute(args)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
