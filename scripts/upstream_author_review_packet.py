#!/usr/bin/env python3
"""Render one evidence-bound human review packet for an exact Draft commit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from upstream_delivery_inbox import build, resolve_source, validate_manifest


def shell_quote(value: str) -> str:
    """Quote an inert argument for the documented POSIX-style command."""

    return "'" + value.replace("'", "'\"'\"'") + "'"


def checklist(values: list[str]) -> str:
    return "\n".join(f"- [x] `{value}`" for value in values) or "- (none)"


def pending_checklist(values: list[str]) -> str:
    return "\n".join(f"- [ ] `{value}`" for value in values) or "- (none)"


def accountability_command(item: dict, output: Path) -> str:
    materials = item["draft_materials"]
    arguments = [
        "python",
        "scripts/kernel_opt.py",
        "upstream-author-accountability",
        "--candidate-id",
        shell_quote(item["candidate_id"]),
        "--repository",
        shell_quote(materials["repository"]),
        "--branch",
        shell_quote(materials["branch"]),
        "--commit",
        shell_quote(materials["commit"]),
        "--submitter-identity",
        shell_quote("REPLACE_WITH_YOUR_NAME_OR_EMAIL"),
        "--commit-attribution",
        "REPLACE_WITH_PASS_OR_NOT_REQUIRED",
        "--output",
        shell_quote(output.as_posix()),
        "--attest-changed-lines-reviewed",
        "--attest-relevant-tests-rerun",
        "--attest-can-defend-change",
        "--attest-ai-assistance-disclosed",
    ]
    continuation = " " + "\\" + "\n  "
    return continuation.join(arguments)


def render(inbox_path: Path, candidate_id: str, accountability_output: Path) -> str:
    manifest_raw = inbox_path.read_bytes()
    manifest = json.loads(manifest_raw)
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("invalid delivery inbox: " + "; ".join(errors))
    if manifest["schema_version"] != "upstream-delivery-inbox-v5":
        raise ValueError("author review packets require upstream-delivery-inbox-v5")
    inbox, errors = build(inbox_path, manifest, manifest_raw)
    if errors:
        raise ValueError("invalid delivery inbox closure: " + "; ".join(errors))
    matches = [item for item in inbox["items"] if item["candidate_id"] == candidate_id]
    if len(matches) != 1:
        raise ValueError(f"candidate_id must resolve exactly once: {candidate_id}")
    item = matches[0]
    if (
        item["recommended_action"] != "COMPLETE_AUTHOR_ACCOUNTABILITY"
        or item["external_action_owner"] != "AUTHOR"
    ):
        raise ValueError(
            "candidate is not awaiting exact-commit human author accountability"
        )
    materials = item.get("draft_materials")
    if not isinstance(materials, dict):
        raise ValueError("candidate has no validated Draft materials")
    accountability = materials.get("author_accountability")
    if (
        not isinstance(accountability, dict)
        or accountability.get("status") != "PENDING"
    ):
        raise ValueError("candidate author accountability is not pending")
    freshness_status = materials["freshness_validation"]["status"]
    already_submitted = item["github_review_stage"] in {
        "DRAFT",
        "READY",
    } and isinstance(item.get("pull_request_url"), str)
    if freshness_status != "PASS" and not already_submitted:
        raise ValueError("candidate Draft freshness is not valid")

    body_path = resolve_source(inbox_path, materials["body"]["path"])
    body = body_path.read_text(encoding="utf-8")
    draft = item["draft_minimum_progress"]
    ready = item["ready_gate_progress"]
    command = accountability_command(item, accountability_output)
    pull_request = item.get("pull_request_url") or "(not submitted)"
    return f"""# Author review packet: {materials["title"]}

This packet gathers machine-validated evidence for one exact commit. It is not a
human attestation and it does not authorize publishing the pull request.

## Exact candidate identity

- Candidate: `{item["candidate_id"]}`
- Repository: `{materials["repository"]}`
- Branch: `{materials["branch"]}`
- Commit: `{materials["commit"]}`
- Compare: {materials["action_url"]}
- Pull request: {pull_request}
- Delivery inbox SHA-256: `{inbox["manifest_sha256"]}`
- PR body SHA-256: `{materials["body"]["sha256"]}`
- Freshness evidence SHA-256: `{materials["freshness_evidence"]["sha256"]}`
- Freshness validation at packet generation: `{freshness_status}`

## Machine-validated Draft minimum

{checklist(draft["passed"])}

## Gates intentionally left for Draft to Ready

Already passed:

{checklist(ready["passed"])}

Still pending:

{pending_checklist(ready["pending"])}

## Human-only review

- [ ] Open the exact compare URL and review every changed line.
- [ ] Personally rerun the relevant Test Plan below and inspect its output.
- [ ] Confirm you can explain and defend the change and its claim boundary.
- [ ] Confirm the PR discloses AI assistance and uses valid commit attribution.

## Proposed pull-request body

{body.rstrip()}

## Record the completed review

Replace both `REPLACE_WITH_...` values. The command deliberately fails closed
while either placeholder remains.

```sh
{command}
```
"""


def write_once(path: Path, value: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = value.encode("utf-8")
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as error:
        raise FileExistsError(
            f"refusing to replace existing review packet: {path}"
        ) from error
    with os.fdopen(descriptor, "wb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inbox", type=Path)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--accountability-output", type=Path)
    args = parser.parse_args()
    inbox_path = args.inbox.resolve(strict=True)
    output = args.output.resolve()
    accountability_output = (
        args.accountability_output.resolve()
        if args.accountability_output is not None
        else output.with_name("author-accountability-v1.json")
    )
    packet = render(inbox_path, args.candidate_id, accountability_output)
    digest = write_once(output, packet)
    print(
        json.dumps(
            {
                "status": "PASS",
                "candidate_id": args.candidate_id,
                "path": output.as_posix(),
                "sha256": digest,
                "claim_boundary": "MACHINE_PREPARED_HUMAN_REVIEW_PACKET_ONLY",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
