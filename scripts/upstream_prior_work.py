#!/usr/bin/env python3
"""Route a candidate against observed open, merged and closed upstream PRs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


ROOT_KEYS = {
    "schema_version",
    "observed_at",
    "repository",
    "queries",
    "candidate",
    "matches",
}
CANDIDATE_KEYS = {
    "candidate_id",
    "branch",
    "commit",
    "core_change_signature",
    "changed_paths",
    "attributed_pr_numbers",
    "coordination_status",
}
MATCH_KEYS = {
    "number",
    "url",
    "author",
    "state",
    "draft",
    "head_commit",
    "relationship",
    "closure_class",
    "closure_evidence_url",
    "core_change_signature",
    "changed_paths",
    "material_delta",
}

RELATIONSHIPS = {
    "EXACT_PREDECESSOR",
    "FEATURE_OVERLAP",
    "ADJACENT",
    "PREREQUISITE",
}
PR_STATES = {"OPEN", "CLOSED", "MERGED"}
CLOSURE_CLASSES = {
    "NOT_CLOSED",
    "MERGED",
    "INACTIVITY_AUTOMATION",
    "TECHNICAL_REJECTION",
    "SUPERSEDED",
    "UNKNOWN",
}
COORDINATION_STATES = {"NONE", "PLANNED", "POSTED"}
HEX40 = re.compile(r"^[0-9a-f]{40}$")


def exact_keys(value: object, expected: set[str], path: str, errors: list[str]) -> dict:
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return {}
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing:
        errors.append(f"{path}: missing keys {missing}")
    if extra:
        errors.append(f"{path}: unexpected keys {extra}")
    return value


def string_list(value: object, path: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        errors.append(f"{path}: must be a list of non-empty strings")
        return []
    if len(value) != len(set(value)):
        errors.append(f"{path}: duplicate values")
    return value


def validate(record: object) -> list[str]:
    errors: list[str] = []
    root = exact_keys(record, ROOT_KEYS, "root", errors)
    if root.get("schema_version") != "upstream-prior-work-v1":
        errors.append("schema_version must be upstream-prior-work-v1")
    repository = root.get("repository")
    if not isinstance(repository, str) or repository.count("/") != 1:
        errors.append("repository: must be OWNER/REPO")
        repository = "invalid/invalid"
    if not isinstance(root.get("observed_at"), str) or not root.get("observed_at"):
        errors.append("observed_at: must be non-empty")
    queries = string_list(root.get("queries"), "queries", errors)
    if not queries:
        errors.append("queries: at least one bounded query is required")
    elif any(
        not query.startswith(f"https://github.com/{repository}/") for query in queries
    ):
        errors.append("queries: every query must target the declared GitHub repository")

    candidate = exact_keys(root.get("candidate"), CANDIDATE_KEYS, "candidate", errors)
    for key in ("candidate_id", "branch", "core_change_signature"):
        if not isinstance(candidate.get(key), str) or not candidate.get(key):
            errors.append(f"candidate.{key}: must be non-empty")
    commit = candidate.get("commit")
    if commit is not None and (
        not isinstance(commit, str) or not HEX40.fullmatch(commit)
    ):
        errors.append("candidate.commit: must be null or a lowercase 40-hex commit")
    string_list(candidate.get("changed_paths"), "candidate.changed_paths", errors)
    attributed = candidate.get("attributed_pr_numbers")
    if not isinstance(attributed, list) or any(
        not isinstance(number, int) or isinstance(number, bool) or number < 1
        for number in attributed
    ):
        errors.append("candidate.attributed_pr_numbers: must be positive integers")
        attributed = []
    elif len(attributed) != len(set(attributed)):
        errors.append("candidate.attributed_pr_numbers: duplicate values")
    if candidate.get("coordination_status") not in COORDINATION_STATES:
        errors.append("candidate.coordination_status: invalid status")

    matches = root.get("matches")
    if not isinstance(matches, list):
        errors.append("matches: must be a list")
        return errors
    seen: set[int] = set()
    for index, value in enumerate(matches):
        path = f"matches[{index}]"
        match = exact_keys(value, MATCH_KEYS, path, errors)
        number = match.get("number")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            errors.append(f"{path}.number: must be a positive integer")
        elif number in seen:
            errors.append(f"{path}.number: duplicate PR number")
        else:
            seen.add(number)
        expected_url = f"https://github.com/{repository}/pull/{number}"
        if match.get("url") != expected_url:
            errors.append(f"{path}.url: must match repository and PR number")
        if not isinstance(match.get("author"), str) or not match.get("author"):
            errors.append(f"{path}.author: must be non-empty")
        state = match.get("state")
        closure = match.get("closure_class")
        if state not in PR_STATES:
            errors.append(f"{path}.state: invalid state")
        if not isinstance(match.get("draft"), bool):
            errors.append(f"{path}.draft: must be boolean")
        if state != "OPEN" and match.get("draft") is True:
            errors.append(f"{path}.draft: closed or merged PR cannot be draft")
        head = match.get("head_commit")
        if head is not None and (
            not isinstance(head, str) or not HEX40.fullmatch(head)
        ):
            errors.append(f"{path}.head_commit: must be null or lowercase 40-hex")
        if match.get("relationship") not in RELATIONSHIPS:
            errors.append(f"{path}.relationship: invalid relationship")
        if closure not in CLOSURE_CLASSES:
            errors.append(f"{path}.closure_class: invalid closure class")
        expected_closures = {
            "OPEN": {"NOT_CLOSED"},
            "MERGED": {"MERGED"},
            "CLOSED": {
                "INACTIVITY_AUTOMATION",
                "TECHNICAL_REJECTION",
                "SUPERSEDED",
                "UNKNOWN",
            },
        }
        if state in expected_closures and closure not in expected_closures[state]:
            errors.append(f"{path}: state and closure_class disagree")
        evidence_url = match.get("closure_evidence_url")
        if state == "CLOSED":
            if not isinstance(evidence_url, str) or not evidence_url.startswith(
                "https://github.com/"
            ):
                errors.append(
                    f"{path}.closure_evidence_url: closed PR requires evidence"
                )
        elif evidence_url is not None:
            errors.append(f"{path}.closure_evidence_url: must be null unless closed")
        for key in ("core_change_signature",):
            if not isinstance(match.get(key), str) or not match.get(key):
                errors.append(f"{path}.{key}: must be non-empty")
        if match.get("relationship") == "EXACT_PREDECESSOR" and match.get(
            "core_change_signature"
        ) != candidate.get("core_change_signature"):
            errors.append(
                f"{path}: exact predecessor must match candidate core signature"
            )
        string_list(match.get("changed_paths"), f"{path}.changed_paths", errors)
        string_list(match.get("material_delta"), f"{path}.material_delta", errors)
    unknown_attribution = sorted(set(attributed) - seen)
    if unknown_attribution:
        errors.append(
            "candidate.attributed_pr_numbers: references unobserved PRs "
            f"{unknown_attribution}"
        )
    return errors


def classify(record: dict) -> dict:
    candidate = record["candidate"]
    matches = record["matches"]
    exact = [row for row in matches if row["relationship"] == "EXACT_PREDECESSOR"]
    overlapping = [row for row in matches if row["relationship"] == "FEATURE_OVERLAP"]
    adjacent = [row for row in matches if row["relationship"] == "ADJACENT"]
    prerequisites = [row for row in matches if row["relationship"] == "PREREQUISITE"]
    attributed = set(candidate["attributed_pr_numbers"])
    coordinated = candidate["coordination_status"] in {"PLANNED", "POSTED"}

    if any(row["state"] == "MERGED" for row in exact):
        action = "STOP_ALREADY_MERGED"
        implementation = publication = False
        required = ["remove the duplicate candidate or prove a distinct core mechanism"]
    elif any(row["state"] == "OPEN" for row in exact):
        action = "CONTRIBUTE_TO_EXISTING_OPEN_PR"
        implementation = publication = False
        required = [
            "offer evidence or a patch to the existing PR; do not open a competitor"
        ]
    elif any(row["closure_class"] == "SUPERSEDED" for row in exact):
        action = "FOLLOW_SUPERSEDING_WORK"
        implementation = publication = False
        required = ["locate and evaluate the superseding implementation"]
    elif any(row["closure_class"] == "TECHNICAL_REJECTION" for row in exact):
        action = "REQUIRE_REJECTION_RESPONSIVE_DELTA"
        implementation = publication = False
        required = ["document how the new design resolves every technical rejection"]
    elif any(row["closure_class"] == "UNKNOWN" for row in exact):
        action = "REVIEW_UNKNOWN_CLOSURE_BEFORE_IMPLEMENTATION"
        implementation = publication = False
        required = ["classify the closed PR from immutable review or closure evidence"]
    elif any(row["state"] == "OPEN" for row in prerequisites):
        action = "WAIT_FOR_PREREQUISITE_TERMINAL_STATE"
        implementation = True
        publication = False
        required = [
            "do not publish a stacked candidate branch",
            "keep cheap candidate validation current while the prerequisite is open",
        ]
    elif any(row["state"] == "CLOSED" for row in prerequisites):
        action = "REPLAN_AFTER_PREREQUISITE_CLOSED"
        implementation = publication = False
        required = [
            "decide whether to absorb, replace, or abandon the unavailable prerequisite"
        ]
    elif prerequisites:
        action = "REBASE_AND_REQUALIFY_AFTER_PREREQUISITE_MERGE"
        implementation = True
        publication = False
        required = [
            "rebase the candidate onto current upstream after the prerequisite merge",
            "repeat source-bound focused qualification before publishing a standalone Draft",
        ]
    elif exact:
        numbers = {row["number"] for row in exact}
        disclosed = numbers.issubset(attributed)
        action = (
            "REVIVE_INACTIVE_PREDECESSOR_WITH_ATTRIBUTION"
            if disclosed and coordinated
            else "PREPARE_ATTRIBUTED_REVIVAL"
        )
        implementation = True
        publication = disclosed and coordinated
        required = (
            []
            if publication
            else [
                "attribute every exact predecessor in the PR body",
                "post or plan one coordination message on the historical PR",
            ]
        )
    elif any(row["state"] == "OPEN" for row in overlapping):
        action = "COORDINATE_OR_PROVE_MATERIAL_DIFFERENCE"
        implementation = True
        publication = coordinated
        required = (
            []
            if publication
            else ["coordinate with the overlapping open PR before publication"]
        )
    elif overlapping or adjacent:
        action = "PROCEED_WITH_PRIOR_WORK_DISCLOSURE"
        implementation = publication = True
        required = [
            "retain related-work links and a precise non-transfer claim boundary"
        ]
    else:
        action = "PROCEED_NO_PRIOR_MATCH"
        implementation = publication = True
        required = []

    return {
        "schema_version": "upstream-prior-work-decision-v1",
        "input_sha256": hashlib.sha256(
            (
                json.dumps(
                    record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                + "\n"
            ).encode()
        ).hexdigest(),
        "recommended_action": action,
        "implementation_allowed": implementation,
        "draft_publication_allowed": publication,
        "exact_predecessor_prs": [row["number"] for row in exact],
        "feature_overlap_prs": [row["number"] for row in overlapping],
        "adjacent_prs": [row["number"] for row in adjacent],
        "prerequisite_prs": [row["number"] for row in prerequisites],
        "required_actions": required,
        "semantic_relationship_is_human_reviewed_input": True,
        "claim_boundary": "PRIOR_WORK_ROUTING_ONLY_NOT_CODE_CORRECTNESS_OR_PERFORMANCE",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        record = json.loads(args.input.read_text(encoding="utf-8"))
    except Exception as error:
        result = {"status": "FAIL", "errors": [str(error)]}
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    errors = validate(record)
    if errors:
        result = {"status": "FAIL", "errors": errors}
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    result = {"status": "PASS", "errors": [], "decision": classify(record)}
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
