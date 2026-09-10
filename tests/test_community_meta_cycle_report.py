#!/usr/bin/env python3
"""Exercise final cross-framework decision validation and fail-closed gates."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_knowledge import atomic_json, sha256_file  # noqa: E402
from community_meta_cycle_report import validate_report  # noqa: E402
from community_evaluation import build_preselection_anchor  # noqa: E402
from community_work_cycle_observation import validate_observation  # noqa: E402


PROTOCOL_COMMIT = "060b8364a5d1902466a1198e3f8403c094de8e79"
SHARED_DEFAULT_COMMIT = "608ec2a520b38b11ec4b88474178ed31ffccd445"
PROTOCOL_PATH = Path("knowledge/community/meta_cycles/cycle-1-theory-first-prior-gate.v1.json")
PREREGISTRATION_PATH = Path(
    "knowledge/community/preregistrations/"
    "meta-cycle-1-cross-framework-2026-09-08.v1.json"
)
SUITE_ID = "cycle-1-cross-framework-cohort-suite"


def relative_identity(path: Path, base: Path) -> dict:
    return {"path": path.relative_to(base).as_posix(), "sha256": sha256_file(path)}


def assessment(arm: str, repository: str, repeat: int, task_id: str) -> dict:
    null_identity = {"path": "not-resolved-by-this-layer.json", "sha256": "0" * 64}
    return {
        "schema_version": "community-trial-assessment-v1",
        "generated_at": "2026-09-09T00:00:00Z",
        "claim_boundary": "SINGLE_TRIAL_OBSERVATION",
        "trial_identity": null_identity,
        "result_identity": null_identity,
        "suite_id": SUITE_ID,
        "task_id": task_id,
        "repeat_index": repeat,
        "arm": arm,
        "success_thresholds": {"minimum_material_speedup": 1.02},
        "metrics": {
            "time_to_first_correct_seconds": (
                8.0 if arm == "COMMUNITY_AUGMENTED" else 10.0
            ),
            "time_to_first_improvement_seconds": 20.0,
            "best_speedup": 1.03,
            "architecture_family_count": 1,
            "heldout_pass_count": 1,
            "best_whole_model_speedup": 1.01,
            "upstream_ready_count": 1,
        },
        "budget_usage": {
            "elapsed_seconds": 30.0,
            "candidate_count": 1,
            "compile_attempts": 1,
            "measurement_attempts": 1,
            "technical_repair_attempts": 0,
            "causal_revisions": 0,
        },
    }


def ledger(repository: str, repeat: int, arm: str, evidence: Path, task_id: str) -> dict:
    evidence_identity = relative_identity(evidence, evidence.parent)
    return {
        "schema_version": "community-work-cycle-v1",
        "cycle_id": f"{repository.replace('/', '-')}-{arm}-{repeat}",
        "task_id": task_id,
        "started_at": "2026-09-09T00:00:00Z",
        "observation_mode": "PROSPECTIVE_EXACT",
        "claim_boundary": "WORK_CYCLE_TIMING_NOT_PERFORMANCE_CAUSALITY",
        "minimum_material_speedup": 1.02,
        "spans": [
            {
                "span_id": "compile",
                "phase": "COMPILE_AND_MEASURE",
                "actor": "GPU",
                "resource_id": "synthetic-gpu",
                "started_at": "2026-09-09T00:00:00Z",
                "ended_at": "2026-09-09T00:00:10Z",
                "status": "COMPLETE",
                "evidence": [evidence_identity],
            },
            {
                "span_id": "correctness",
                "phase": "CORRECTNESS_VALIDATION",
                "actor": "GPU",
                "resource_id": "synthetic-gpu",
                "started_at": "2026-09-09T00:00:10Z",
                "ended_at": "2026-09-09T00:00:20Z",
                "status": "COMPLETE",
                "evidence": [evidence_identity],
            },
            {
                "span_id": "whole-model",
                "phase": "WHOLE_MODEL_VALIDATION",
                "actor": "GPU",
                "resource_id": "synthetic-gpu",
                "started_at": "2026-09-09T00:00:20Z",
                "ended_at": "2026-09-09T00:00:30Z",
                "status": "COMPLETE",
                "evidence": [evidence_identity],
            },
        ],
        "milestones": [
            {
                "kind": "FIRST_QUALIFIED_RESULT",
                "at": "2026-09-09T00:00:30Z",
                "evidence": [evidence_identity],
            }
        ],
        "outcome": {
            "correctness": "PASS",
            "best_speedup": 1.03,
            "best_whole_model_speedup": 1.01,
            "upstream_ready": True,
            "pull_request_url": None,
            "merged": False,
        },
    }


def build_framework(
    base: Path,
    repository: str,
    pr_number: int,
    suite_path: Path,
    task_id: str,
) -> dict:
    directory = base / repository.replace("/", "-")
    directory.mkdir(parents=True, exist_ok=True)
    source_evidence = directory / "synthetic-evidence.json"
    source_evidence.write_text('{"synthetic": true}\n', encoding="utf-8")
    suite_id = SUITE_ID
    pairs = []
    observations = {"control": [], "community_augmented": []}
    for repeat in (1, 2):
        assessment_paths = {}
        for arm, key in (("CONTROL", "control"), ("COMMUNITY_AUGMENTED", "community")):
            path = directory / f"assessment-{key}-r{repeat}.json"
            atomic_json(path, assessment(arm, repository, repeat, task_id))
            assessment_paths[key] = path
            ledger_path = directory / f"ledger-{key}-r{repeat}.json"
            atomic_json(
                ledger_path,
                ledger(repository, repeat, key, source_evidence, task_id),
            )
            observation_path = directory / f"observation-{key}-r{repeat}.json"
            is_community = key == "community"
            atomic_json(
                observation_path,
                {
                    "schema_version": "community-work-cycle-observation-v1",
                    "generated_at": "2026-09-09T00:01:00Z",
                    "claim_boundary": "UNIFIED_OBSERVATION_NOT_CROSS_FRAMEWORK_CAUSALITY",
                    "repository": repository,
                    "suite_id": suite_id,
                    "task_id": task_id,
                    "repeat_index": repeat,
                    "arm": arm,
                    "ledger_identity": relative_identity(ledger_path, directory),
                    "assessment_identity": relative_identity(path, directory),
                    "candidate_sources": [
                        {
                            "kind": "COMMUNITY_EVENT" if is_community else "LOCAL_THEORY",
                            "identity": relative_identity(source_evidence, directory),
                        }
                    ],
                    "search_policy": {
                        "policy_id": (
                            "theory-first-prior-gated-v1"
                            if is_community
                            else "theory-first-local-v1"
                        ),
                        "protocol_commit": PROTOCOL_COMMIT,
                        "community_knowledge_exposed": is_community,
                    },
                    "failure_stage": "NOT_FAILED",
                    "regression": {
                        "test_count": 10,
                        "failure_count": 0,
                        "rate": 0.0,
                        "evidence": [relative_identity(source_evidence, directory)],
                    },
                    "real_workload": {
                        "status": "PASS",
                        "speedup": 1.01,
                        "evidence": [relative_identity(source_evidence, directory)],
                    },
                    "resource_usage": {
                        "wall_clock_seconds": 30.0,
                        "gpu_seconds": 30.0,
                        "validation_seconds": 20.0,
                    },
                },
            )
            observations[
                "community_augmented" if key == "community" else "control"
            ].append(
                {
                    "repeat_index": repeat,
                    "observation": relative_identity(observation_path, base),
                }
            )
        pair_path = directory / f"pair-r{repeat}.json"
        atomic_json(
            pair_path,
            {
                "schema_version": "community-ab-report-v1",
                "generated_at": "2026-09-09T00:00:00Z",
                "claim_boundary": "PAIRED_TRIAL_ONLY",
                "suite_id": suite_id,
                "task_id": task_id,
                "repeat_index": repeat,
                "control_assessment": relative_identity(assessment_paths["control"], directory),
                "community_assessment": relative_identity(assessment_paths["community"], directory),
                "deltas": {},
                "treatment_fidelity": {
                    "community_event_prior_realized": True,
                    "method_prior_realized": False,
                    "any_prior_realized": True,
                    "causal_interpretation": "TREATMENT_REALIZED",
                },
            },
        )
        pairs.append(pair_path)
    summary_path = directory / "repeat-summary.json"
    atomic_json(
        summary_path,
        {
            "schema_version": "community-ab-repeat-summary-v1",
            "generated_at": "2026-09-09T00:00:00Z",
            "claim_boundary": "REPEATED_PAIRS_SINGLE_TASK",
            "suite_id": suite_id,
            "task_id": task_id,
            "repeat_count": 2,
            "pair_reports": [relative_identity(path, directory) for path in pairs],
            "paired_medians": {},
            "arm_medians": {"control": {}, "community_augmented": {}},
            "paired_wins": {},
            "material_improvement_repeats": {"control": 1, "community_augmented": 2},
        },
    )
    return {
        "repository": repository,
        "suite_identity": relative_identity(suite_path, base),
        "suite_id": suite_id,
        "task_id": task_id,
        "repeat_summary": relative_identity(summary_path, base),
        "observations": observations,
        "metric_verdicts": {
            "TIME_TO_FIRST_CORRECT": "BETTER",
            "TIME_TO_FIRST_IMPROVEMENT": "NO_CHANGE",
            "VALIDATION_VALUE_PER_GPU_HOUR": "NO_CHANGE",
            "UPSTREAM_READY_OR_MERGE_RATE": "NO_CHANGE",
        },
        "non_regression_verdicts": {
            "CORRECTNESS": "NO_REGRESSION",
            "REGRESSION_RATE": "NO_REGRESSION",
            "WHOLE_MODEL_SPEEDUP": "NO_REGRESSION",
            "VALIDATION_COST": "NO_REGRESSION",
        },
        "qualification": {
            "improvement_metrics": ["TIME_TO_FIRST_CORRECT"],
            "regression_metrics": [],
            "treatment_realized_repeats": 2,
            "qualified_for_cross_framework_claim": True,
        },
    }


def build_suite(base: Path, primary: list[tuple[str, int, str]]) -> Path:
    null_identity = {"path": "synthetic-input.json", "sha256": "0" * 64}
    anchor_path = base / "preselection-anchor.json"
    atomic_json(
        anchor_path,
        build_preselection_anchor(
            ROOT / PREREGISTRATION_PATH,
            PROTOCOL_COMMIT,
            ROOT,
        ),
    )
    suite_path = base / "suite.json"
    atomic_json(
        suite_path,
        {
            "schema_version": "community-temporal-suite-v1",
            "suite_id": SUITE_ID,
            "cutoff_at": "2026-09-08T19:30:00Z",
            "claim_boundary": "EVALUATION_PROTOCOL_ONLY",
            "training_graph": null_identity,
            "preselection_anchor": relative_identity(anchor_path, base),
            "protocol": {
                "arms": ["CONTROL", "COMMUNITY_AUGMENTED"],
                "repeats": 2,
                "randomized_order": True,
                "random_seed": 20260908,
                "network_policy": "DISABLED_AFTER_MATERIALIZATION",
                "model_identity": "same-model-same-settings-within-pair",
                "prompt_identity": null_identity,
                "environment_identity": null_identity,
                "task_packet_contract": "STRICT_V2",
                "budgets": {
                    "wall_clock_seconds": 900,
                    "max_command_seconds": 180,
                    "max_candidates": 4,
                    "max_compile_attempts": 6,
                    "max_measurements": 6,
                    "max_technical_repairs": 2,
                    "max_causal_revisions": 2,
                },
                "minimum_material_speedup": 1.02,
                "metrics": [
                    "TIME_TO_FIRST_CORRECT",
                    "TIME_TO_FIRST_IMPROVEMENT",
                    "BEST_SPEEDUP",
                    "ARCHITECTURE_FAMILY_COVERAGE",
                    "HELDOUT_CORRECTNESS",
                    "WHOLE_MODEL_SPEEDUP",
                    "UPSTREAM_READINESS",
                ],
            },
            "tasks": [
                {
                    "task_id": f"{repository.replace('/', '-')}-task",
                    "available_at": "2026-09-08T19:31:00Z",
                    "repository": repository,
                    "pr_number": pr_number,
                    "base_revision": "1" * 40,
                    "target_hardware": "synthetic-gpu",
                    "packet": null_identity,
                    "hidden_oracle": null_identity,
                }
                for repository, pr_number, _ in primary
            ],
        },
    )
    return suite_path


def build_report(base: Path) -> dict:
    protocol = ROOT / PROTOCOL_PATH
    primary = [
        ("sgl-project/sglang", 38565, "sglang-38565"),
        ("vllm-project/vllm", 55967, "vllm-55967"),
    ]
    repositories = [repository for repository, _, _ in primary]
    suite_path = build_suite(base, primary)
    cohort_path = base / "cohort-freeze.json"
    schedule = []
    blocks = [(task_id, repeat_index) for _, _, task_id in primary for repeat_index in (1, 2)]
    blocks.sort(
        key=lambda item: hashlib.sha256(
            f"20260908:{item[0]}:{item[1]}".encode("utf-8")
        ).hexdigest()
    )
    for task_id, repeat_index in blocks:
        arms = sorted(
            ("CONTROL", "COMMUNITY_AUGMENTED"),
            key=lambda arm: hashlib.sha256(
                f"20260908:{task_id}:{repeat_index}:{arm}".encode("utf-8")
            ).hexdigest(),
        )
        for arm in arms:
                schedule_key = hashlib.sha256(
                    f"20260908:{task_id}:{repeat_index}:{arm}".encode("utf-8")
                ).hexdigest()
                schedule.append(
                    {
                        "task_id": task_id,
                        "repeat_index": repeat_index,
                        "arm": arm,
                        "schedule_key": schedule_key,
                    }
                )
    for order_index, entry in enumerate(schedule, start=1):
        entry["order_index"] = order_index
    atomic_json(
        cohort_path,
        {
            "schema_version": "meta-cycle-cross-framework-cohort-freeze-v1",
            "cycle_id": "cycle-1-theory-first-prior-gate-v1",
            "frozen_protocol": {
                "commit": PROTOCOL_COMMIT,
                "random_seed": 20260908,
                "repeats": 2,
            },
            "primary_tasks": [
                {"repository": repository, "pr_number": pr_number, "task_id": task_id}
                for repository, pr_number, task_id in primary
            ],
            "randomized_schedule": {"entries": schedule},
        },
    )
    return {
        "schema_version": "community-meta-cycle-report-v1",
        "generated_at": "2026-09-09T01:00:00Z",
        "claim_boundary": "FINAL_CROSS_FRAMEWORK_POLICY_DECISION",
        "cycle_id": "cycle-1-theory-first-prior-gate-v1",
        "protocol_commit": PROTOCOL_COMMIT,
        "protocol_identity": {"path": PROTOCOL_PATH.as_posix(), "sha256": sha256_file(protocol)},
        "cohort_identity": relative_identity(cohort_path, base),
        "evidence_root_label": "synthetic-test-evidence",
        "framework_results": [
            build_framework(base, repository, pr_number, suite_path, task_id)
            for repository, pr_number, task_id in primary
        ],
        "aggregate_gate": {
            "compared_frameworks": repositories,
            "qualified_frameworks": repositories,
            "improve_any_met": True,
            "must_not_regress_met": True,
            "promotion_eligible": True,
        },
        "decision": {
            "outcome": "PROMOTE_DEFAULT",
            "rationale": ["Synthetic passing evidence for validator coverage."],
            "shared_default_commit": SHARED_DEFAULT_COMMIT,
        },
    }


def test_final_report_and_fail_closed_recomputation() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        report_path = base / "report.json"
        report = build_report(base)
        atomic_json(report_path, report)
        assert validate_report(report_path, base)["decision"]["outcome"] == "PROMOTE_DEFAULT"

        broken = copy.deepcopy(report)
        framework = broken["framework_results"][0]
        framework["non_regression_verdicts"]["CORRECTNESS"] = "INCONCLUSIVE"
        framework["qualification"]["qualified_for_cross_framework_claim"] = False
        broken["aggregate_gate"]["qualified_frameworks"] = ["vllm-project/vllm"]
        broken["aggregate_gate"]["must_not_regress_met"] = False
        broken["aggregate_gate"]["promotion_eligible"] = False
        atomic_json(report_path, broken)
        try:
            validate_report(report_path, base)
        except ValueError as error:
            assert "recomputed observations" in str(error)
        else:
            raise AssertionError("declared verdicts must not override observed evidence")


def test_observation_rejects_unreconciled_regression_rate() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        report = build_report(base)
        identity = report["framework_results"][0]["observations"]["control"][0][
            "observation"
        ]
        observation_path = base / identity["path"]
        observation = json.loads(observation_path.read_text(encoding="utf-8"))
        observation["regression"]["rate"] = 0.5
        atomic_json(observation_path, observation)
        try:
            validate_observation(observation_path)
        except ValueError as error:
            assert "regression rate" in str(error)
        else:
            raise AssertionError("regression rate must be derived from measured counts")


def test_final_report_rejects_substituted_cohort_or_suite() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        report_path = base / "report.json"
        report = build_report(base)

        cohort_path = base / report["cohort_identity"]["path"]
        cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
        cohort["primary_tasks"][0]["pr_number"] = 38563
        atomic_json(cohort_path, cohort)
        report["cohort_identity"] = relative_identity(cohort_path, base)
        atomic_json(report_path, report)
        try:
            validate_report(report_path, base)
        except ValueError as error:
            assert "repository/task" in str(error)
        else:
            raise AssertionError("a substituted cohort PR must be rejected")

        report = build_report(base)
        alternate_suite = base / "alternate-suite.json"
        first_suite = base / report["framework_results"][0]["suite_identity"]["path"]
        alternate_suite.write_bytes(first_suite.read_bytes())
        report["framework_results"][0]["suite_identity"] = relative_identity(
            alternate_suite, base
        )
        atomic_json(report_path, report)
        try:
            validate_report(report_path, base)
        except ValueError as error:
            assert "same exact cohort suite" in str(error)
        else:
            raise AssertionError("framework results must not use different suite identities")


def test_final_report_maps_cohort_task_id_to_suite_by_repository_and_pr() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        report_path = base / "report.json"
        report = build_report(base)

        # The real Cycle 1 suite uses a descriptive executor task id while the
        # frozen cohort and observations use the stable PR-scoped id.  The
        # repository+PR pair is the explicit bridge; the cohort id remains the
        # observation identity.
        suite_path = base / report["framework_results"][0]["suite_identity"]["path"]
        suite = json.loads(suite_path.read_text(encoding="utf-8"))
        suite["tasks"][0]["task_id"] = "sglang-38565-tp-sampling-consistency"
        atomic_json(suite_path, suite)
        suite_identity = relative_identity(suite_path, base)
        for framework in report["framework_results"]:
            framework["suite_identity"] = suite_identity
        atomic_json(report_path, report)
        assert validate_report(report_path, base)["framework_results"][0][
            "task_id"
        ] == "sglang-38565"

        broken = copy.deepcopy(report)
        broken["framework_results"][0]["task_id"] = "foreign-task"
        atomic_json(report_path, broken)
        try:
            validate_report(report_path, base)
        except ValueError as error:
            assert "repository/task" in str(error)
        else:
            raise AssertionError("framework task id must remain bound to the cohort")


if __name__ == "__main__":
    test_final_report_and_fail_closed_recomputation()
    test_observation_rejects_unreconciled_regression_rate()
    test_final_report_rejects_substituted_cohort_or_suite()
    test_final_report_maps_cohort_task_id_to_suite_by_repository_and_pr()
