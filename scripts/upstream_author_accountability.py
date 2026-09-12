#!/usr/bin/env python3
"""Issue one explicit human submitter attestation for an exact Draft commit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from upstream_delivery_inbox import validate_author_accountability


def timestamp(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("attested-at must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("attested-at must include a timezone")
    return value


def build(args: argparse.Namespace) -> dict:
    attested_at = timestamp(args.attested_at)
    if re.fullmatch(r"[0-9a-f]{40}", args.commit) is None:
        raise ValueError("candidate_commit must be a lowercase 40-hex Git commit")
    submitter_identity = args.submitter_identity.strip()
    if (
        not submitter_identity
        or "REPLACE_WITH" in submitter_identity.upper()
        or submitter_identity.upper() in {"NAME_OR_EMAIL", "YOUR_NAME_OR_EMAIL"}
    ):
        raise ValueError("submitter_identity must identify the actual human submitter")
    record = {
        "schema_version": "upstream-delivery-author-accountability-v1",
        "attested_at": attested_at,
        "candidate_id": args.candidate_id,
        "repository": args.repository,
        "branch": args.branch,
        "candidate_commit": args.commit,
        "submitter_identity": submitter_identity,
        "checks": {
            "changed_lines_reviewed": args.attest_changed_lines_reviewed,
            "relevant_tests_rerun": args.attest_relevant_tests_rerun,
            "can_defend_change": args.attest_can_defend_change,
            "ai_assistance_disclosed": args.attest_ai_assistance_disclosed,
            "commit_attribution": args.commit_attribution,
        },
        "claim_boundary": "HUMAN_SUBMITTER_ATTESTED_EXACT_COMMIT",
    }
    errors = validate_author_accountability(
        record,
        candidate_id=args.candidate_id,
        repository=args.repository,
        branch=args.branch,
        commit=args.commit,
        inbox_observed_at=attested_at,
    )
    if errors:
        raise ValueError("invalid author accountability: " + "; ".join(errors))
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--submitter-identity", required=True)
    parser.add_argument(
        "--commit-attribution", choices=("PASS", "NOT_REQUIRED"), required=True
    )
    parser.add_argument("--attested-at")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--attest-changed-lines-reviewed", action="store_true", required=True
    )
    parser.add_argument(
        "--attest-relevant-tests-rerun", action="store_true", required=True
    )
    parser.add_argument(
        "--attest-can-defend-change", action="store_true", required=True
    )
    parser.add_argument(
        "--attest-ai-assistance-disclosed", action="store_true", required=True
    )
    return parser.parse_args()


def write_once(path: Path, value: dict) -> str:
    """Create one immutable receipt without a check-then-overwrite race."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as error:
        raise FileExistsError(
            f"refusing to replace existing attestation: {path}"
        ) from error
    with os.fdopen(descriptor, "wb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    record = build(args)
    digest = write_once(output, record)
    print(
        json.dumps(
            {
                "status": "PASS",
                "path": output.as_posix(),
                "sha256": digest,
                "candidate_id": record["candidate_id"],
                "candidate_commit": record["candidate_commit"],
                "claim_boundary": record["claim_boundary"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
