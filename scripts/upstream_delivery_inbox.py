#!/usr/bin/env python3
"""Aggregate hash-bound review states into one deterministic delivery queue."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from upstream_review_handoff import (
    classify as classify_review_handoff,
    validate as validate_review_handoff,
)
from upstream_review_state import classify, validate as validate_review_state


ROOT_KEYS = {"schema_version", "observed_at", "candidates"}
CANDIDATE_KEYS_V1 = {"candidate_id", "lane_id", "review_state"}
CANDIDATE_KEYS_V2 = CANDIDATE_KEYS_V1 | {"review_handoff"}
CANDIDATE_KEYS_V3 = CANDIDATE_KEYS_V2 | {"draft_materials"}
CANDIDATE_KEYS_V4 = CANDIDATE_KEYS_V3
CANDIDATE_KEYS_V5 = CANDIDATE_KEYS_V4
SOURCE_KEYS = {"path", "sha256"}
DRAFT_MATERIAL_KEYS = {
    "title",
    "submission_type",
    "repository",
    "branch",
    "commit",
    "action_url",
    "body",
    "freshness_evidence",
}
DRAFT_MATERIAL_KEYS_V5 = DRAFT_MATERIAL_KEYS | {"author_accountability"}
VERSIONS = {
    "upstream-delivery-inbox-v1",
    "upstream-delivery-inbox-v2",
    "upstream-delivery-inbox-v3",
    "upstream-delivery-inbox-v4",
    "upstream-delivery-inbox-v5",
}
FRESHNESS_KEYS = {
    "schema_version",
    "observed_at",
    "expires_at",
    "candidate_id",
    "repository",
    "branch",
    "candidate_commit",
    "upstream_main_commit",
    "fork_branch_commit",
    "checks",
    "claim_boundary",
}
FRESHNESS_CHECK_KEYS = {
    "fork_branch_matches_candidate",
    "touched_paths_unchanged",
    "merge_conflict",
    "exact_head_pull_request_count",
    "draft_submission_eligible",
}
ACCOUNTABILITY_KEYS = {
    "schema_version",
    "attested_at",
    "candidate_id",
    "repository",
    "branch",
    "candidate_commit",
    "submitter_identity",
    "checks",
    "claim_boundary",
}
ACCOUNTABILITY_CHECK_KEYS = {
    "changed_lines_reviewed",
    "relevant_tests_rerun",
    "can_defend_change",
    "ai_assistance_disclosed",
    "commit_attribution",
}
MAX_FRESHNESS_SECONDS = 6 * 60 * 60
PRIORITY = {
    "CLOSE_OR_REVISE_FAILED_CANDIDATE": 0,
    "RESPOND_TO_REVIEW": 1,
    "OPEN_DRAFT": 2,
    "MARK_READY_AND_REQUEST_REVIEW": 3,
    "REQUEST_TOPIC_REVIEWERS": 3,
    "ONE_TARGETED_REVIEWER_FOLLOW_UP": 3,
    "ONE_TOPIC_SPECIFIC_CHANNEL_ESCALATION": 3,
    "COMPLETE_DRAFT_MINIMUM": 4,
    "COMPLETE_DRAFT_MATERIALS": 4,
    "REFRESH_DRAFT_FRESHNESS": 4,
    "COMPLETE_AUTHOR_ACCOUNTABILITY": 4,
    "KEEP_DRAFT_CONTINUE_QUALIFICATION": 5,
    "CONTINUE_QUALIFICATION_WITH_EARLY_REVIEW": 5,
    "WAIT_FOR_MAINTAINER_CI_AND_REVIEW": 6,
    "WAIT_FOR_REVIEW": 7,
    "WAIT_FOR_CI_OR_MERGE": 7,
    "WAIT": 7,
    "NO_ACTION_CLOSED": 8,
    "NO_ACTION_MERGED": 9,
}
ACTIONABLE = {
    "OPEN_DRAFT",
    "MARK_READY_AND_REQUEST_REVIEW",
    "RESPOND_TO_REVIEW",
    "REQUEST_TOPIC_REVIEWERS",
    "ONE_TARGETED_REVIEWER_FOLLOW_UP",
    "ONE_TOPIC_SPECIFIC_CHANNEL_ESCALATION",
    "COMPLETE_AUTHOR_ACCOUNTABILITY",
}


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


def parse_timestamp(value: object, path: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str):
        errors.append(f"{path}: must be an RFC3339 string")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{path}: invalid RFC3339 timestamp")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        errors.append(f"{path}: timezone is required")
        return None
    return parsed


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def validate_source(value: object, path: str, errors: list[str]) -> dict:
    source = exact_keys(value, SOURCE_KEYS, path, errors)
    if not isinstance(source.get("path"), str) or not source.get("path"):
        errors.append(f"{path}.path: must be non-empty")
    if not valid_sha256(source.get("sha256")):
        errors.append(f"{path}.sha256: must be lowercase SHA-256")
    return source


def contains_scalar(value: object, expected: str) -> bool:
    if value == expected:
        return True
    if isinstance(value, list):
        return any(contains_scalar(item, expected) for item in value)
    if isinstance(value, dict):
        return any(contains_scalar(item, expected) for item in value.values())
    return False


def validate_draft_freshness(
    value: object,
    *,
    candidate_id: str,
    repository: str,
    branch: str,
    commit: str,
    inbox_observed_at: str,
) -> list[str]:
    """Validate a short-lived, exact Draft publication freshness closure."""

    errors: list[str] = []
    record = exact_keys(value, FRESHNESS_KEYS, "freshness", errors)
    if record.get("schema_version") != "upstream-delivery-freshness-v1":
        errors.append(
            "freshness.schema_version: must be upstream-delivery-freshness-v1"
        )
    observed = parse_timestamp(
        record.get("observed_at"), "freshness.observed_at", errors
    )
    expires = parse_timestamp(record.get("expires_at"), "freshness.expires_at", errors)
    inbox_observed = parse_timestamp(
        inbox_observed_at, "freshness.inbox_observed_at", errors
    )
    if observed is not None and expires is not None:
        lifetime = (expires - observed).total_seconds()
        if lifetime <= 0 or lifetime > MAX_FRESHNESS_SECONDS:
            errors.append(
                "freshness.expires_at: validity must be greater than zero and at most "
                f"{MAX_FRESHNESS_SECONDS} seconds"
            )
    if (
        observed is not None
        and inbox_observed is not None
        and inbox_observed < observed
    ):
        errors.append("freshness.observed_at: cannot be after inbox observed_at")
    if expires is not None and inbox_observed is not None and inbox_observed > expires:
        errors.append(
            "freshness.expires_at: evidence is stale for this inbox observation"
        )
    expected = {
        "candidate_id": candidate_id,
        "repository": repository,
        "branch": branch,
        "candidate_commit": commit,
        "fork_branch_commit": commit,
    }
    for field, expected_value in expected.items():
        if record.get(field) != expected_value:
            errors.append(f"freshness.{field}: does not match Draft materials")
    main_commit = record.get("upstream_main_commit")
    if (
        not isinstance(main_commit, str)
        or len(main_commit) != 40
        or any(char not in "0123456789abcdef" for char in main_commit)
    ):
        errors.append("freshness.upstream_main_commit: must be a lowercase Git commit")
    checks = exact_keys(
        record.get("checks"), FRESHNESS_CHECK_KEYS, "freshness.checks", errors
    )
    for field in (
        "fork_branch_matches_candidate",
        "touched_paths_unchanged",
        "draft_submission_eligible",
    ):
        if checks.get(field) is not True:
            errors.append(f"freshness.checks.{field}: must be true")
    if checks.get("merge_conflict") is not False:
        errors.append("freshness.checks.merge_conflict: must be false")
    if checks.get("exact_head_pull_request_count") != 0:
        errors.append("freshness.checks.exact_head_pull_request_count: must be zero")
    if not isinstance(record.get("claim_boundary"), str) or not record.get(
        "claim_boundary"
    ):
        errors.append("freshness.claim_boundary: must be non-empty")
    return errors


def validate_author_accountability(
    value: object,
    *,
    candidate_id: str,
    repository: str,
    branch: str,
    commit: str,
    inbox_observed_at: str,
) -> list[str]:
    """Validate a human submitter's exact candidate accountability record."""

    errors: list[str] = []
    record = exact_keys(value, ACCOUNTABILITY_KEYS, "accountability", errors)
    if record.get("schema_version") != "upstream-delivery-author-accountability-v1":
        errors.append(
            "accountability.schema_version: must be "
            "upstream-delivery-author-accountability-v1"
        )
    attested = parse_timestamp(
        record.get("attested_at"), "accountability.attested_at", errors
    )
    observed = parse_timestamp(
        inbox_observed_at, "accountability.inbox_observed_at", errors
    )
    if attested is not None and observed is not None and attested > observed:
        errors.append("accountability.attested_at: cannot be after inbox observed_at")
    expected = {
        "candidate_id": candidate_id,
        "repository": repository,
        "branch": branch,
        "candidate_commit": commit,
    }
    for field, expected_value in expected.items():
        if record.get(field) != expected_value:
            errors.append(
                f"accountability.{field}: expected {expected_value!r}, "
                f"got {record.get(field)!r}"
            )
    if not isinstance(record.get("submitter_identity"), str) or not record.get(
        "submitter_identity"
    ):
        errors.append("accountability.submitter_identity: must be non-empty")
    if not isinstance(record.get("claim_boundary"), str) or not record.get(
        "claim_boundary"
    ):
        errors.append("accountability.claim_boundary: must be non-empty")
    checks = exact_keys(
        record.get("checks"), ACCOUNTABILITY_CHECK_KEYS, "accountability.checks", errors
    )
    for field in (
        "changed_lines_reviewed",
        "relevant_tests_rerun",
        "can_defend_change",
        "ai_assistance_disclosed",
    ):
        if checks.get(field) is not True:
            errors.append(f"accountability.checks.{field}: must be true")
    if checks.get("commit_attribution") not in {"PASS", "NOT_REQUIRED"}:
        errors.append(
            "accountability.checks.commit_attribution: must be PASS or NOT_REQUIRED"
        )
    return errors


def check_progress(checks: dict[str, str], complete_values: set[str]) -> dict:
    passed = sorted(key for key, value in checks.items() if value in complete_values)
    pending = sorted(key for key, value in checks.items() if value == "PENDING")
    failed = sorted(key for key, value in checks.items() if value == "FAIL")
    return {
        "passed": passed,
        "pending": pending,
        "failed": failed,
        "passed_count": len(passed),
        "total_count": len(checks),
    }


def validate_manifest(record: object) -> list[str]:
    errors: list[str] = []
    root = exact_keys(record, ROOT_KEYS, "root", errors)
    version = root.get("schema_version")
    if version not in VERSIONS:
        errors.append(f"schema_version must be one of {sorted(VERSIONS)}")
    parse_timestamp(root.get("observed_at"), "observed_at", errors)
    candidates = root.get("candidates")
    if not isinstance(candidates, list):
        errors.append("candidates: must be an array")
        return errors
    identities: set[str] = set()
    for index, value in enumerate(candidates):
        expected_keys = {
            "upstream-delivery-inbox-v1": CANDIDATE_KEYS_V1,
            "upstream-delivery-inbox-v2": CANDIDATE_KEYS_V2,
            "upstream-delivery-inbox-v3": CANDIDATE_KEYS_V3,
            "upstream-delivery-inbox-v4": CANDIDATE_KEYS_V4,
            "upstream-delivery-inbox-v5": CANDIDATE_KEYS_V5,
        }.get(version, CANDIDATE_KEYS_V1)
        candidate = exact_keys(value, expected_keys, f"candidates[{index}]", errors)
        candidate_id = candidate.get("candidate_id")
        lane_id = candidate.get("lane_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            errors.append(f"candidates[{index}].candidate_id: must be non-empty")
        elif candidate_id in identities:
            errors.append(f"candidates[{index}].candidate_id: duplicate identity")
        else:
            identities.add(candidate_id)
        if not isinstance(lane_id, str) or not lane_id:
            errors.append(f"candidates[{index}].lane_id: must be non-empty")
        validate_source(
            candidate.get("review_state"),
            f"candidates[{index}].review_state",
            errors,
        )
        if version in {
            "upstream-delivery-inbox-v2",
            "upstream-delivery-inbox-v3",
            "upstream-delivery-inbox-v4",
            "upstream-delivery-inbox-v5",
        }:
            handoff = candidate.get("review_handoff")
            if handoff is not None:
                validate_source(
                    handoff,
                    f"candidates[{index}].review_handoff",
                    errors,
                )
        if version in {
            "upstream-delivery-inbox-v3",
            "upstream-delivery-inbox-v4",
            "upstream-delivery-inbox-v5",
        }:
            materials = candidate.get("draft_materials")
            if materials is not None:
                materials = exact_keys(
                    materials,
                    (
                        DRAFT_MATERIAL_KEYS_V5
                        if version == "upstream-delivery-inbox-v5"
                        else DRAFT_MATERIAL_KEYS
                    ),
                    f"candidates[{index}].draft_materials",
                    errors,
                )
                for field in ("title", "repository", "branch", "action_url"):
                    if not isinstance(materials.get(field), str) or not materials.get(
                        field
                    ):
                        errors.append(
                            f"candidates[{index}].draft_materials.{field}: must be non-empty"
                        )
                if materials.get("submission_type") != "DRAFT_PULL_REQUEST":
                    errors.append(
                        f"candidates[{index}].draft_materials.submission_type: "
                        "must be DRAFT_PULL_REQUEST"
                    )
                commit = materials.get("commit")
                if (
                    not isinstance(commit, str)
                    or len(commit) != 40
                    or any(char not in "0123456789abcdef" for char in commit)
                ):
                    errors.append(
                        f"candidates[{index}].draft_materials.commit: "
                        "must be a lowercase 40-character Git commit"
                    )
                material_fields = ["body", "freshness_evidence"]
                if (
                    version == "upstream-delivery-inbox-v5"
                    and materials.get("author_accountability") is not None
                ):
                    material_fields.append("author_accountability")
                for field in material_fields:
                    validate_source(
                        materials.get(field),
                        f"candidates[{index}].draft_materials.{field}",
                        errors,
                    )
    return errors


def resolve_source(manifest_path: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else manifest_path.parent / path


def build(
    manifest_path: Path, manifest: dict, manifest_bytes: bytes
) -> tuple[dict, list[str]]:
    errors: list[str] = []
    items: list[dict] = []
    pull_identities: dict[tuple[str, int], str] = {}
    for index, candidate in enumerate(manifest["candidates"]):
        source = candidate["review_state"]
        path = resolve_source(manifest_path, source["path"])
        try:
            raw = path.read_bytes()
        except OSError as error:
            errors.append(f"candidates[{index}].review_state.path: {error}")
            continue
        actual_sha = sha256_bytes(raw)
        if actual_sha != source["sha256"]:
            errors.append(
                f"candidates[{index}].review_state.sha256: expected {source['sha256']}, got {actual_sha}"
            )
            continue
        try:
            review_state = json.loads(raw)
        except Exception as error:
            errors.append(f"candidates[{index}].review_state.path: {error}")
            continue
        nested_errors = validate_review_state(review_state)
        if nested_errors:
            errors.extend(
                f"candidates[{index}].review_state: {error}" for error in nested_errors
            )
            continue
        pull = review_state["pull_request"]
        if pull["number"] is not None:
            pull_identity = (pull["repository"], pull["number"])
            previous = pull_identities.get(pull_identity)
            if previous is not None:
                errors.append(
                    f"candidates[{index}]: pull request {pull_identity[0]}#{pull_identity[1]} "
                    f"is already bound to {previous}"
                )
                continue
            pull_identities[pull_identity] = candidate["candidate_id"]
        decision = classify(review_state)
        handoff_result = None
        effective_action = decision["recommended_action"]
        effective_owner = decision["external_action_owner"]
        if manifest["schema_version"] in {
            "upstream-delivery-inbox-v2",
            "upstream-delivery-inbox-v3",
            "upstream-delivery-inbox-v4",
            "upstream-delivery-inbox-v5",
        }:
            handoff_source = candidate["review_handoff"]
            ready_pull = pull["state"] == "OPEN" and pull["draft"] is False
            if ready_pull and handoff_source is None:
                errors.append(
                    f"candidates[{index}].review_handoff: required for an open Ready PR"
                )
                continue
            if handoff_source is not None:
                handoff_path = resolve_source(manifest_path, handoff_source["path"])
                try:
                    handoff_raw = handoff_path.read_bytes()
                except OSError as error:
                    errors.append(f"candidates[{index}].review_handoff.path: {error}")
                    continue
                handoff_sha = sha256_bytes(handoff_raw)
                if handoff_sha != handoff_source["sha256"]:
                    errors.append(
                        f"candidates[{index}].review_handoff.sha256: expected "
                        f"{handoff_source['sha256']}, got {handoff_sha}"
                    )
                    continue
                try:
                    handoff = json.loads(handoff_raw)
                except Exception as error:
                    errors.append(f"candidates[{index}].review_handoff.path: {error}")
                    continue
                nested_errors = validate_review_handoff(handoff)
                if nested_errors:
                    errors.extend(
                        f"candidates[{index}].review_handoff: {error}"
                        for error in nested_errors
                    )
                    continue
                handoff_pull = handoff["pull_request"]
                for field in ("url", "repository", "number", "state", "draft"):
                    if handoff_pull[field] != pull[field]:
                        errors.append(
                            f"candidates[{index}].review_handoff.pull_request.{field}: "
                            "does not match review_state"
                        )
                if handoff["observation"]["observed_at"] != manifest["observed_at"]:
                    errors.append(
                        f"candidates[{index}].review_handoff.observation.observed_at: "
                        "must match inbox observed_at"
                    )
                if errors:
                    continue
                handoff_decision = classify_review_handoff(handoff)
                handoff_result = {
                    "path": handoff_source["path"],
                    "sha256": handoff_sha,
                    **handoff_decision,
                }
                if handoff_decision["recommended_action"] not in {
                    "WAIT",
                    "NO_ACTION",
                }:
                    effective_action = handoff_decision["recommended_action"]
                    effective_owner = handoff_decision["external_action_owner"]
        draft_material_result = None
        if manifest["schema_version"] in {
            "upstream-delivery-inbox-v3",
            "upstream-delivery-inbox-v4",
            "upstream-delivery-inbox-v5",
        }:
            materials = candidate["draft_materials"]
            if effective_action == "OPEN_DRAFT" and materials is None:
                effective_action = "COMPLETE_DRAFT_MATERIALS"
                effective_owner = "EXECUTION_LANE"
            if materials is not None:
                if materials["repository"] != pull["repository"]:
                    errors.append(
                        f"candidates[{index}].draft_materials.repository: "
                        "does not match review_state"
                    )
                    continue
                compare_prefix = (
                    f"https://github.com/{materials['repository']}/compare/"
                )
                if not materials["action_url"].startswith(compare_prefix):
                    errors.append(
                        f"candidates[{index}].draft_materials.action_url: "
                        "must be a repository compare URL"
                    )
                    continue
                material_bytes: dict[str, bytes] = {}
                material_failed = False
                material_fields = ["body", "freshness_evidence"]
                if (
                    manifest["schema_version"] == "upstream-delivery-inbox-v5"
                    and materials["author_accountability"] is not None
                ):
                    material_fields.append("author_accountability")
                for field in material_fields:
                    material_source = materials[field]
                    material_path = resolve_source(
                        manifest_path, material_source["path"]
                    )
                    try:
                        raw_material = material_path.read_bytes()
                    except OSError as error:
                        errors.append(
                            f"candidates[{index}].draft_materials.{field}.path: {error}"
                        )
                        material_failed = True
                        continue
                    material_sha = sha256_bytes(raw_material)
                    if material_sha != material_source["sha256"]:
                        errors.append(
                            f"candidates[{index}].draft_materials.{field}.sha256: "
                            f"expected {material_source['sha256']}, got {material_sha}"
                        )
                        material_failed = True
                        continue
                    material_bytes[field] = raw_material
                if material_failed:
                    continue
                body_raw = material_bytes["body"]
                if not body_raw or len(body_raw) > 65_536:
                    errors.append(
                        f"candidates[{index}].draft_materials.body: "
                        "must be 1..65536 bytes"
                    )
                    continue
                try:
                    body_raw.decode("utf-8")
                except UnicodeDecodeError:
                    errors.append(
                        f"candidates[{index}].draft_materials.body: must be UTF-8"
                    )
                    continue
                try:
                    freshness = json.loads(material_bytes["freshness_evidence"])
                except Exception as error:
                    errors.append(
                        f"candidates[{index}].draft_materials.freshness_evidence.path: "
                        f"{error}"
                    )
                    continue
                freshness_errors = []
                freshness_status = "PASS"
                if manifest["schema_version"] in {
                    "upstream-delivery-inbox-v4",
                    "upstream-delivery-inbox-v5",
                }:
                    freshness_errors = validate_draft_freshness(
                        freshness,
                        candidate_id=candidate["candidate_id"],
                        repository=materials["repository"],
                        branch=materials["branch"],
                        commit=materials["commit"],
                        inbox_observed_at=manifest["observed_at"],
                    )
                    if freshness_errors:
                        freshness_status = "REFRESH_REQUIRED"
                        if effective_action == "OPEN_DRAFT":
                            effective_action = "REFRESH_DRAFT_FRESHNESS"
                            effective_owner = "EXECUTION_LANE"
                elif not contains_scalar(freshness, materials["commit"]):
                    errors.append(
                        f"candidates[{index}].draft_materials.freshness_evidence: "
                        "does not bind the candidate commit"
                    )
                    continue
                accountability_result = None
                if manifest["schema_version"] == "upstream-delivery-inbox-v5":
                    accountability_source = materials["author_accountability"]
                    accountability_errors = []
                    accountability_status = "PASS"
                    if accountability_source is None:
                        accountability_status = "PENDING"
                        accountability_errors = [
                            "author accountability has not been attested"
                        ]
                    else:
                        try:
                            accountability = json.loads(
                                material_bytes["author_accountability"]
                            )
                        except Exception as error:
                            accountability_status = "REVIEW_REQUIRED"
                            accountability_errors = [f"invalid JSON: {error}"]
                        else:
                            accountability_errors = validate_author_accountability(
                                accountability,
                                candidate_id=candidate["candidate_id"],
                                repository=materials["repository"],
                                branch=materials["branch"],
                                commit=materials["commit"],
                                inbox_observed_at=manifest["observed_at"],
                            )
                            if accountability_errors:
                                accountability_status = "REVIEW_REQUIRED"
                    if accountability_errors and effective_action == "OPEN_DRAFT":
                        effective_action = "COMPLETE_AUTHOR_ACCOUNTABILITY"
                        effective_owner = "AUTHOR"
                    accountability_result = {
                        "source": accountability_source,
                        "status": accountability_status,
                        "errors": accountability_errors,
                    }
                draft_material_result = {
                    key: materials[key]
                    for key in (
                        "title",
                        "submission_type",
                        "repository",
                        "branch",
                        "commit",
                        "action_url",
                    )
                }
                draft_material_result.update(
                    {
                        "body": {
                            "path": materials["body"]["path"],
                            "sha256": materials["body"]["sha256"],
                            "bytes": len(body_raw),
                        },
                        "freshness_evidence": materials["freshness_evidence"],
                        "freshness_validation": {
                            "status": freshness_status,
                            "errors": freshness_errors,
                        },
                    }
                )
                if accountability_result is not None:
                    draft_material_result["author_accountability"] = (
                        accountability_result
                    )
        draft_progress = check_progress(review_state["draft_minimum"], {"PASS"})
        ready_progress = check_progress(
            review_state["ready_gates"], {"PASS", "NOT_APPLICABLE"}
        )
        item = {
            "candidate_id": candidate["candidate_id"],
            "lane_id": candidate["lane_id"],
            "review_state": {"path": source["path"], "sha256": actual_sha},
            "repository": pull["repository"],
            "pull_request_number": pull["number"],
            "pull_request_url": pull["url"],
            "github_review_stage": decision["github_review_stage"],
            "candidate_quality": decision["candidate_quality"],
            "recommended_action": effective_action,
            "external_action_owner": effective_owner,
            "internal_candidate_status": pull["internal_candidate_status"],
            "draft_minimum_progress": draft_progress,
            "ready_gate_progress": ready_progress,
            "priority": PRIORITY[effective_action],
        }
        if manifest["schema_version"] in {
            "upstream-delivery-inbox-v2",
            "upstream-delivery-inbox-v3",
            "upstream-delivery-inbox-v4",
            "upstream-delivery-inbox-v5",
        }:
            item["review_state_action"] = decision["recommended_action"]
            item["review_handoff"] = handoff_result
        if manifest["schema_version"] in {
            "upstream-delivery-inbox-v3",
            "upstream-delivery-inbox-v4",
            "upstream-delivery-inbox-v5",
        }:
            item["draft_materials"] = draft_material_result
        items.append(item)
    items.sort(
        key=lambda item: (
            item["priority"],
            -item["draft_minimum_progress"]["passed_count"],
            -item["ready_gate_progress"]["passed_count"],
            item["lane_id"],
            item["candidate_id"],
        )
    )
    counts = Counter(item["recommended_action"] for item in items)
    result = {
        "schema_version": {
            "upstream-delivery-inbox-v1": "upstream-delivery-inbox-result-v1",
            "upstream-delivery-inbox-v2": "upstream-delivery-inbox-result-v2",
            "upstream-delivery-inbox-v3": "upstream-delivery-inbox-result-v3",
            "upstream-delivery-inbox-v4": "upstream-delivery-inbox-result-v4",
            "upstream-delivery-inbox-v5": "upstream-delivery-inbox-result-v5",
        }[manifest["schema_version"]],
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "observed_at": manifest["observed_at"],
        "candidate_count": len(items),
        "actionable_count": sum(
            item["recommended_action"] in ACTIONABLE for item in items
        ),
        "action_counts": dict(sorted(counts.items())),
        "items": items,
    }
    return result, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        raw = args.input.read_bytes()
        manifest = json.loads(raw)
    except Exception as error:
        print(json.dumps({"status": "FAIL", "errors": [str(error)]}, indent=2))
        return 1
    errors = validate_manifest(manifest)
    result = None
    if not errors:
        result, errors = build(args.input, manifest, raw)
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, indent=2))
        return 1
    output = {"status": "PASS", "errors": [], "inbox": result}
    rendered = json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
