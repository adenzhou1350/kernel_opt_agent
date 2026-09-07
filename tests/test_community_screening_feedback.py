#!/usr/bin/env python3
"""Exercise append-only postselection screening feedback."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_knowledge import atomic_json, sha256_file  # noqa: E402
from community_screening_feedback import (  # noqa: E402
    build_feedback,
    validate_feedback,
)


def file_identity(path: Path) -> dict:
    return {"path": path.resolve().as_posix(), "sha256": sha256_file(path)}


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        queue_path = root / "queue.json"
        screen_path = root / "screen.json"
        audit_path = root / "audit.json"
        assessment_path = root / "assessment.json"
        feedback_path = root / "feedback.json"
        atomic_json(
            queue_path,
            {
                "items": [
                    {
                        "repository": "example/project",
                        "pr_number": 7,
                        "title": "CI: baseline unguarded perf cases",
                        "earliest_public_at": "2026-01-02T00:01:00Z",
                        "selection": "SELECTED",
                    }
                ]
            },
        )
        atomic_json(
            screen_path,
            {
                "items": [
                    {
                        "repository": "example/project",
                        "pr_number": 7,
                        "status": "ELIGIBLE",
                        "matched_rule_id": "default",
                    }
                ]
            },
        )
        atomic_json(
            audit_path,
            {
                "observations": {
                    "cutoff_at": "2026-01-02T00:00:00Z",
                    "git_commit": "a" * 40,
                    "observed_repositories": ["example/project"],
                }
            },
        )
        atomic_json(
            assessment_path,
            {
                "schema_version": "community-postselection-task-assessment-v1",
                "generated_at": "2026-01-02T00:02:00Z",
                "claim_boundary": "POST_SELECTION_PUBLIC_METADATA_ASSESSMENT_NOT_PERFORMANCE_EXECUTION",
                "candidate": {
                    "repository": "example/project",
                    "pr_number": 7,
                    "title": "CI: baseline unguarded perf cases",
                    "earliest_public_at": "2026-01-02T00:01:00Z",
                    "url": "https://github.com/example/project/pull/7",
                    "state_at_assessment": "open",
                    "draft_at_assessment": False,
                    "base_sha": "b" * 40,
                    "head_sha": "c" * 40,
                    "head_ref": "ci/perf-baseline",
                    "commit_count": 1,
                    "changed_file_count": 2,
                    "additions": 10,
                    "deletions": 1,
                },
                "frozen_selection_evidence": {
                    "queue": file_identity(queue_path),
                    "screen": file_identity(screen_path),
                    "chain_audit": file_identity(audit_path),
                    "preselection_decision": "ELIGIBLE",
                    "preselection_rule": "default",
                },
                "public_problem_statement": {
                    "symptom": "Latency expectations were disabled.",
                    "reported_regressions": ["2x latency remained CI-green"],
                    "declared_change": "Populate latency expectations.",
                    "declared_benchmarking": "N/A; CI baseline only",
                    "target_hardware_in_source": ["H100"],
                },
                "materialization_decision": {
                    "status": "KNOWLEDGE_ONLY_NO_OPTIMIZATION_TARGET",
                    "reason_codes": [
                        "CI_BASELINE_MAINTENANCE",
                        "NO_FASTER_IMPLEMENTATION_OBJECTIVE",
                    ],
                    "gpu_dispatch": False,
                    "compile_or_benchmark": False,
                    "duplicate_pr_allowed": False,
                    "task_materialized": False,
                },
                "knowledge_value": {
                    "event_family": "PERFORMANCE_REGRESSION_GUARD",
                    "positive_method": "Bind a nonzero latency expectation.",
                    "negative_experience": "Disabled limits hide regressions.",
                    "transfer_targets": ["other performance CI"],
                    "falsification": "Reject stale or noisy thresholds.",
                },
                "future_policy_observation": {
                    "status": "RECORDED_FOR_FUTURE_COHORT_ONLY",
                    "candidate_rule": "Route CI-only baseline work to knowledge-only.",
                    "anti_leakage": "Never modify the active cohort.",
                },
                "source_access": {
                    "metadata_endpoint": "https://api.github.com/repos/example/project/pulls/7",
                    "conversation_url": "https://github.com/example/project/pull/7",
                    "patch_or_diff_read": False,
                },
            },
        )
        feedback = build_feedback(
            assessment_path,
            "example-7-ci-baseline-not-optimization-v1",
            "2026-01-02T00:03:00Z",
        )
        assert feedback["activation_policy"] == {
            "minimum_distinct_candidates": 2,
            "current_distinct_candidates": 1,
            "status": "INSUFFICIENT_EVIDENCE",
            "action": "RECORD_ONLY_DO_NOT_ROUTE",
        }
        assert feedback["cohort"]["excluded_from_same_cohort"]
        atomic_json(feedback_path, feedback)
        assert validate_feedback(feedback_path)["status"] == "PASS"

        original_queue = queue_path.read_text(encoding="utf-8")
        queue = json.loads(original_queue)
        queue["items"][0]["title"] = "tampered"
        atomic_json(queue_path, queue)
        try:
            validate_feedback(feedback_path)
        except ValueError as error:
            assert "queue evidence hash changed" in str(error)
        else:
            raise AssertionError("tampered frozen queue passed feedback validation")
        queue_path.write_text(original_queue, encoding="utf-8")

        feedback["activation_policy"]["current_distinct_candidates"] = 2
        atomic_json(feedback_path, feedback)
        try:
            validate_feedback(feedback_path)
        except ValueError as error:
            assert "invalid screening feedback" in str(error)
        else:
            raise AssertionError("single observation activated routing")
    print("community screening feedback test: PASS")


if __name__ == "__main__":
    main()
