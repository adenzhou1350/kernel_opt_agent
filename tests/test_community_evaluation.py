#!/usr/bin/env python3
"""Exercise temporal isolation and fixed-budget community A/B scoring."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from community_evaluation import (
    audit_task_packets,
    audit_codex_execution,
    assess_trial,
    build_ab_meta_analysis,
    build_prior_outcome_ledger,
    build_feasibility_screen,
    build_heldout_queue,
    build_prior_shortlist,
    compare_trials,
    exact_two_sided_sign_p,
    materialize_suite,
    materialize_trial,
    prepare_trial_source,
    prior_scalar_text,
    prior_term_in_text,
    summarize_pair_rows,
    summarize_schedule_run,
    validate_source_receipt,
    validate_schedule,
    validate_qualification_checkpoint,
    validate_feasibility_screen,
    validate_ab_meta_analysis,
    validate_prior_outcome_ledger,
    validate_heldout_queue,
    validate_suite,
)
from community_trial_runner import commit_finalizer_draft, valid_result
from community_knowledge import (
    atomic_json,
    build_graph,
    capture_pr,
    sha256_file,
    sync_repository,
)
from community_trial_runner import command_for
from test_community_knowledge import FakeGitHubClient, event_for
from method_library import build_snapshot
from schema_utils import validate_instance


def identity(path: Path, base: Path) -> dict:
    return {
        "path": path.relative_to(base).as_posix(),
        "sha256": sha256_file(path),
    }


def test_qualification_checkpoint() -> None:
    trial = {"success_thresholds": {"minimum_material_speedup": 1.1}}
    contract = {
        "policy": {
            "qualification_checkpoint": (
                "FIRST_MATERIAL_CORRECT_BEFORE_NEXT_CANDIDATE"
            )
        }
    }
    candidates = [
        {
            "candidate_id": "first",
            "proposed_at_seconds": 10.0,
            "correctness": "PASS",
            "speedup": 1.2,
            "heldout_correctness": "NOT_RUN",
        },
        {
            "candidate_id": "later",
            "proposed_at_seconds": 20.0,
            "correctness": "PASS",
            "speedup": 1.3,
            "heldout_correctness": "PASS",
        },
    ]
    try:
        validate_qualification_checkpoint(trial, {"candidates": candidates}, contract)
    except ValueError as error:
        assert "qualification checkpoint bypassed" in str(error)
    else:
        raise AssertionError("a skipped qualification checkpoint was accepted")
    candidates[0]["heldout_correctness"] = "PASS"
    validate_qualification_checkpoint(trial, {"candidates": candidates}, contract)


def candidate(
    candidate_id: str,
    proposed: float,
    evaluated: float,
    family: str,
    speedup: float,
    whole_model_speedup: float,
    evidence: dict,
    upstream_ready: bool,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "proposed_at_seconds": proposed,
        "evaluated_at_seconds": evaluated,
        "architecture_family": family,
        "compile_attempts": 1,
        "measurement_attempts": 1,
        "correctness": "PASS",
        "speedup": speedup,
        "heldout_correctness": "PASS",
        "whole_model_speedup": whole_model_speedup,
        "upstream_ready": upstream_ready,
        "evidence": [evidence],
    }


def write_result(trial_dir: Path, rows: list[dict], elapsed: float) -> None:
    trial = json.loads((trial_dir / "trial.json").read_text(encoding="utf-8"))
    ranking_path = trial_dir / "evidence" / "opportunity-ranking.json"
    closure_path = trial_dir / "evidence" / "frontier-closure.json"
    architectures = [
        {
            "architecture_id": "launch-fusion",
            "rank": 1,
            "name": "remove launch and materialization overhead",
            "dimension_ids": ["launch-materialization"],
            "partition_axis": "output rows",
            "upper_bound": {
                "kind": "UNKNOWN",
                "maximum_speedup": None,
                "rationale": "Must be measured before implementation evidence exists.",
            },
        },
        {
            "architecture_id": "work-partition",
            "rank": 2,
            "name": "change the work partition",
            "dimension_ids": ["work-decomposition"],
            "partition_axis": "hidden tiles",
            "upper_bound": {
                "kind": "STRUCTURAL",
                "maximum_speedup": None,
                "rationale": "Adds a required intermediate for this synthetic case.",
            },
        },
        {
            "architecture_id": "shape-specialized",
            "rank": 3,
            "name": "specialize the dominant shape",
            "dimension_ids": ["shape-path-specialization"],
            "partition_axis": "dominant batch shape",
            "upper_bound": {
                "kind": "STRUCTURAL",
                "maximum_speedup": None,
                "rationale": "The workload contains only one frozen shape.",
            },
        },
    ]
    atomic_json(
        ranking_path,
        {
            "schema_version": "community-opportunity-ranking-v1",
            "created_at_seconds": 0,
            "claim_boundary": "PRE_IMPLEMENTATION_HYPOTHESES_ONLY",
            "contract_identity": trial["frontier_contract"],
            "diagnosis": "Synthetic test ranking.",
            "architectures": architectures,
            "prior_gate": {
                "diagnosis_confidence": "high",
                "leading_local_candidate": "launch-fusion",
                "expected_ceiling": "unknown before measurement",
                "largest_unresolved_risk": "correctness",
                "knowledge_positive_expected_value": False,
            },
        },
    )
    selected = max(rows, key=lambda row: row["speedup"] or 0)
    shared_evidence = [rows[0]["evidence"][0]]
    atomic_json(
        closure_path,
        {
            "schema_version": "community-frontier-closure-v1",
            "generated_at_seconds": elapsed,
            "claim_boundary": "SEARCH_FRONTIER_ACCOUNTING_ONLY",
            "contract_identity": trial["frontier_contract"],
            "opportunity_ranking_identity": identity(ranking_path, trial_dir),
            "selected_candidate_id": selected["candidate_id"],
            "selected_speedup": selected["speedup"],
            "architectures": [
                {
                    "architecture_id": "launch-fusion",
                    "status": "SELECTED",
                    "candidate_ids": [row["candidate_id"] for row in rows],
                    "current_upper_bound": {
                        "kind": "QUANTIFIED",
                        "maximum_speedup": selected["speedup"] * 1.01,
                        "rationale": "The synthetic bound is within one material margin.",
                    },
                    "evidence": shared_evidence,
                },
                {
                    "architecture_id": "work-partition",
                    "status": "DOMINATED",
                    "candidate_ids": [],
                    "current_upper_bound": {
                        "kind": "QUANTIFIED",
                        "maximum_speedup": selected["speedup"] * 1.01,
                        "rationale": "The synthetic model bounds this within one margin.",
                    },
                    "evidence": shared_evidence,
                },
                {
                    "architecture_id": "shape-specialized",
                    "status": "INFEASIBLE",
                    "candidate_ids": [],
                    "current_upper_bound": {
                        "kind": "STRUCTURAL",
                        "maximum_speedup": None,
                        "rationale": "There is no second shape or optional path.",
                    },
                    "evidence": shared_evidence,
                },
            ],
            "stop_reason": "Synthetic closure for validation tests.",
        },
    )
    method_realization = None
    if trial.get("method_snapshot") is not None:
        methods = json.loads(
            (trial_dir / "knowledge" / "methods.json").read_text(encoding="utf-8")
        )
        selected_method_id = methods["included_method_ids"][0]
        method_realization = {
            "inspected_method_ids": [selected_method_id],
            "selected_method_id": selected_method_id,
            "disposition": "REALIZED_IN_CANDIDATE",
            "instantiation": {
                "partition_axis": "output rows",
                "local_state": "one row tile",
                "combine_rule": "independent tiles",
                "finalization": "write one output tile",
            },
            "candidate_ids": [row["candidate_id"] for row in rows],
            "rationale": "The listed candidates instantiate the selected decomposition.",
            "evidence": [rows[0]["evidence"][0]],
        }
    result = {
        "schema_version": "community-trial-result-v1",
        "trial_id": trial["trial_id"],
        "task_id": trial["task_id"],
        "arm": trial["arm"],
        "agent_identity": "fixed-agent-and-prompt",
        "completion_status": "COMPLETE",
        "elapsed_seconds": elapsed,
        "technical_repair_attempts": 1,
        "causal_revisions": 1,
        "candidates": rows,
        "frontier_closure": identity(closure_path, trial_dir),
        "notes": [],
    }
    if method_realization is not None:
        result["method_realization"] = method_realization
    if trial.get("knowledge_realization_required"):
        shortlist = json.loads(
            (trial_dir / "knowledge" / "prior_shortlist.json").read_text(
                encoding="utf-8"
            )
        )
        if shortlist["events"]:
            selected_event_id = shortlist["events"][0]["id"]
            result["knowledge_realization"] = {
                "inspected_event_ids": [selected_event_id],
                "selected_event_ids": [selected_event_id],
                "disposition": "REALIZED_IN_CANDIDATE",
                "candidate_ids": [row["candidate_id"] for row in rows],
                "rationale": "The synthetic event changed the tested candidate plan.",
                "evidence": [rows[0]["evidence"][0]],
            }
        else:
            result["knowledge_realization"] = {
                "inspected_event_ids": [],
                "selected_event_ids": [],
                "disposition": "NO_RELEVANT_COMMUNITY_PRIOR",
                "candidate_ids": [],
                "rationale": "No event passed the frozen prior shortlist.",
                "evidence": [],
            }
    atomic_json(
        trial_dir / "result.json",
        result,
    )


def main() -> None:
    test_qualification_checkpoint()
    ranking_schema = json.loads(
        (ROOT / "schemas" / "community_opportunity_ranking.schema.json").read_text(
            encoding="utf-8"
        )
    )
    bad_bound = {
        "kind": "STRUCTURAL",
        "maximum_speedup": 5.0,
        "rationale": "A qualitative bound cannot carry a numeric maximum.",
    }
    bound_errors = validate_instance(
        bad_bound, ranking_schema["$defs"]["bound"]
    )
    assert bound_errors, "schema accepted a numeric STRUCTURAL bound"
    assert prior_term_in_text("row", "row-wise reduction")
    assert "prefix" not in prior_scalar_text({"windows_prefix": "/mnt/d"})
    assert not prior_term_in_text("io", "materialization")
    runner_command = command_for("codex", Path("trial"), "test-model", "high")
    assert "--json" in runner_command
    assert "--output-schema" not in runner_command
    assert "--dangerously-bypass-approvals-and-sandbox" in runner_command

    assert exact_two_sided_sign_p(3, 0) == 0.25
    repeated = summarize_pair_rows(
        [
            {
                "control_elapsed_seconds": 30,
                "community_augmented_elapsed_seconds": 20,
                "elapsed_seconds_saved": 10,
                "control_first_correct_seconds": 20,
                "community_augmented_first_correct_seconds": 10,
                "first_correct_seconds_saved": 10,
                "control_architecture_family_count": 2,
                "community_augmented_architecture_family_count": 4,
                "architecture_family_gain": 2,
                "control_best_speedup": 1.01,
                "community_augmented_best_speedup": 1.03,
                "best_speedup_gain": 0.02,
                "control_material_improvement": 0,
                "community_augmented_material_improvement": 1,
            },
            {
                "control_elapsed_seconds": 40,
                "community_augmented_elapsed_seconds": 35,
                "elapsed_seconds_saved": 5,
                "control_first_correct_seconds": 30,
                "community_augmented_first_correct_seconds": 25,
                "first_correct_seconds_saved": 5,
                "control_architecture_family_count": 3,
                "community_augmented_architecture_family_count": 4,
                "architecture_family_gain": 1,
                "control_best_speedup": 1.02,
                "community_augmented_best_speedup": 1.01,
                "best_speedup_gain": -0.01,
                "control_material_improvement": 1,
                "community_augmented_material_improvement": 0,
            },
        ]
    )
    assert repeated["paired_medians"]["elapsed_seconds_saved"] == 7.5
    assert repeated["paired_wins"]["faster_time_to_first_correct"]["community"] == 2

    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        corpus = base / "corpus"
        captured = capture_pr(
            "example/project", 7, corpus, FakeGitHubClient(), ROOT
        )
        event_path = corpus / "events" / "training-event.json"
        event_path.parent.mkdir(parents=True)
        event_path.write_text(
            json.dumps(event_for(Path(captured["manifest"])), indent=2) + "\n",
            encoding="utf-8",
        )
        graph = build_graph(corpus, ["example/project", "other/project"], ROOT)

        selection_cutoff = "2026-01-03T12:00:00Z"
        selection_graph_path = base / "selection-graph.json"
        atomic_json(
            selection_graph_path,
            build_graph(
                corpus,
                ["example/project", "other/project"],
                ROOT,
                selection_cutoff,
            ),
        )
        selection_methods_path = base / "selection-methods.json"
        atomic_json(
            selection_methods_path,
            build_snapshot(selection_cutoff, ROOT),
        )
        selection_receipt_path = base / "selection-sync-v2.json"
        selection_receipt = sync_repository(
            "example/project",
            "2026-01-01T00:00:00Z",
            "2026-01-05T00:00:00Z",
            corpus,
            selection_receipt_path,
            FakeGitHubClient(),
            max_captures=4,
            dry_run=True,
            root=ROOT,
        )
        eligible_candidate = json.loads(
            json.dumps(selection_receipt["candidates"][0])
        )
        eligible_candidate.update(
            {
                "pr_number": 9,
                "title": "Optimize a future unseen kernel path",
                "created_at": "2026-01-04T00:00:00Z",
                "earliest_public_at": "2026-01-04T00:00:00Z",
                "updated_at": "2026-01-04T01:00:00Z",
            }
        )
        same_group_candidate = json.loads(json.dumps(eligible_candidate))
        same_group_candidate.update(
            {
                "pr_number": 10,
                "title": "Optimize another future regression path",
                "created_at": "2026-01-04T02:00:00Z",
                "earliest_public_at": "2026-01-04T02:00:00Z",
                "updated_at": "2026-01-04T03:00:00Z",
                "selection_score": eligible_candidate["selection_score"] - 1,
            }
        )
        diverse_candidate = json.loads(json.dumps(eligible_candidate))
        diverse_candidate.update(
            {
                "pr_number": 11,
                "title": "Reduce movement in a future unseen path",
                "created_at": "2026-01-04T04:00:00Z",
                "earliest_public_at": "2026-01-04T04:00:00Z",
                "updated_at": "2026-01-04T05:00:00Z",
                "classifications": ["DATA_MOVEMENT"],
                "selection_score": 1,
            }
        )
        selection_receipt["candidates"].extend(
            [eligible_candidate, same_group_candidate, diverse_candidate]
        )
        selection_receipt["candidate_count"] += 3
        atomic_json(selection_receipt_path, selection_receipt)
        heldout_queue_path = base / "heldout-queue.json"
        heldout_queue = build_heldout_queue(
            [selection_receipt_path],
            selection_graph_path,
            selection_methods_path,
            corpus,
            selection_cutoff,
            2,
            20260907,
            ROOT,
        )
        atomic_json(heldout_queue_path, heldout_queue)

        feasibility_queue = build_heldout_queue(
            [selection_receipt_path],
            selection_graph_path,
            selection_methods_path,
            corpus,
            selection_cutoff,
            3,
            20260907,
            ROOT,
        )
        atomic_json(heldout_queue_path, feasibility_queue)
        feasibility_policy_path = base / "feasibility-policy.json"
        atomic_json(
            feasibility_policy_path,
            {
                "schema_version": "community-feasibility-policy-v1",
                "policy_id": "test-metadata-policy",
                "declared_at": "2027-01-01T00:00:00Z",
                "claim_boundary": "DISCOVERY_METADATA_FEASIBILITY_ONLY",
                "default_rule": {
                    "task_family": "GENERAL_KERNEL",
                    "requirements": {
                        "vendors_any": ["NVIDIA"],
                        "capabilities_all": ["CUDA"],
                        "minimum_gpu_count": 1,
                        "minimum_memory_gib_per_gpu": 1,
                    },
                    "reason": "DECLARED_RESOURCE_AND_HARNESS_READY",
                },
                "rules": [
                    {
                        "rule_id": "amd-only",
                        "priority": 1,
                        "match": {"title_regex": "another future regression"},
                        "task_family": "AMD_KERNEL",
                        "requirements": {
                            "vendors_any": ["AMD"],
                            "capabilities_all": ["ROCM"],
                            "minimum_gpu_count": 1,
                            "minimum_memory_gib_per_gpu": 1,
                        },
                        "reason": "REQUIRES_AMD_ROCM",
                    },
                    {
                        "rule_id": "analysis-only",
                        "priority": 2,
                        "match": {"classifications_any": ["DATA_MOVEMENT"]},
                        "task_family": "ANALYSIS_VISUALIZATION",
                        "requirements": {
                            "vendors_any": [],
                            "capabilities_all": [],
                            "minimum_gpu_count": 1,
                            "minimum_memory_gib_per_gpu": 0,
                        },
                        "forced_status": "HARNESS_BLOCKED",
                        "reason": "NO_RUNTIME_PERFORMANCE_TARGET",
                    },
                ],
            },
        )
        feasibility_profile_path = base / "execution-profile.json"
        atomic_json(
            feasibility_profile_path,
            {
                "schema_version": "community-execution-profile-v1",
                "profile_id": "test-local-nvidia",
                "observed_at": "2026-01-03T13:00:00Z",
                "claim_boundary": "DECLARED_AVAILABILITY_NOT_LIVE_PROOF",
                "resources": [
                    {
                        "resource_id": "local-sm89",
                        "availability": "AVAILABLE",
                        "vendor": "NVIDIA",
                        "architecture": "sm89",
                        "gpu_count": 1,
                        "memory_gib_per_gpu": 8,
                        "capabilities": ["CUDA"],
                        "constraints": [],
                    }
                ],
                "harnesses": [
                    {
                        "repository": "example/project",
                        "task_family": "GENERAL_KERNEL",
                        "status": "READY",
                        "reason": "TEST_HARNESS_READY",
                    }
                ],
            },
        )
        feasibility_screen_path = base / "feasibility-screen.json"
        feasibility_screen = build_feasibility_screen(
            heldout_queue_path,
            feasibility_policy_path,
            feasibility_profile_path,
            corpus,
            ROOT,
        )
        atomic_json(feasibility_screen_path, feasibility_screen)
        assert feasibility_screen["registration"] == "POST_SELECTION_PILOT"
        assert feasibility_screen["inventory"] == {
            "selected_queue_count": 3,
            "eligible_count": 1,
            "infeasible_count": 1,
            "harness_blocked_count": 1,
        }
        assert {row["status"] for row in feasibility_screen["items"]} == {
            "ELIGIBLE",
            "INFEASIBLE",
            "HARNESS_BLOCKED",
        }
        assert validate_feasibility_screen(
            feasibility_screen_path, corpus, ROOT
        )["status"] == "PASS"
        tampered_screen = json.loads(json.dumps(feasibility_screen))
        tampered_screen["items"][0]["reason"] = "EDITED"
        atomic_json(feasibility_screen_path, tampered_screen)
        try:
            validate_feasibility_screen(feasibility_screen_path, corpus, ROOT)
        except ValueError as error:
            assert "stale or was edited" in str(error)
        else:
            raise AssertionError("edited feasibility screen was accepted")
        atomic_json(feasibility_screen_path, feasibility_screen)
        assert heldout_queue["inventory"] == {
            "receipt_candidate_count": 4,
            "deduplicated_count": 4,
            "eligible_count": 3,
            "selected_count": 2,
            "backlog_count": 1,
            "excluded_pre_cutoff_count": 1,
            "excluded_training_source_count": 0,
        }
        selected_prs = {
            row["pr_number"]
            for row in heldout_queue["items"]
            if row["selection"] == "SELECTED"
        }
        assert selected_prs == {9, 11}
        assert next(
            row for row in heldout_queue["items"] if row["pr_number"] == 10
        )["selection"] == "BACKLOG"
        assert heldout_queue["excluded"][0]["pr_number"] == 7
        assert heldout_queue["excluded"][0]["reason"] == "PRE_CUTOFF_PUBLIC"
        assert validate_heldout_queue(heldout_queue_path, corpus, ROOT)[
            "status"
        ] == "PASS"
        legacy_selection_path = base / "selection-sync-v1.json"
        legacy_selection = json.loads(json.dumps(selection_receipt))
        legacy_selection["schema_version"] = "community-sync-receipt-v1"
        atomic_json(legacy_selection_path, legacy_selection)
        try:
            build_heldout_queue(
                [legacy_selection_path],
                selection_graph_path,
                selection_methods_path,
                corpus,
                selection_cutoff,
                2,
                20260907,
                ROOT,
            )
        except ValueError as error:
            assert "requires community-sync-receipt-v2" in str(error)
        else:
            raise AssertionError("legacy sync receipt was accepted for held-out selection")
        future_methods_path = base / "future-methods.json"
        future_methods = json.loads(
            selection_methods_path.read_text(encoding="utf-8")
        )
        future_methods["cards"][0]["source"]["available_at"] = (
            "2026-01-04T00:00:00Z"
        )
        atomic_json(future_methods_path, future_methods)
        try:
            build_heldout_queue(
                [selection_receipt_path],
                selection_graph_path,
                future_methods_path,
                corpus,
                selection_cutoff,
                2,
                20260907,
                ROOT,
            )
        except ValueError as error:
            assert "leaks future method" in str(error)
        else:
            raise AssertionError("future method was accepted for held-out selection")
        tampered_heldout = json.loads(json.dumps(heldout_queue))
        tampered_heldout["items"][0]["discovery_score"] += 1
        atomic_json(heldout_queue_path, tampered_heldout)
        try:
            validate_heldout_queue(heldout_queue_path, corpus, ROOT)
        except ValueError as error:
            assert "stale or was edited" in str(error)
        else:
            raise AssertionError("edited held-out queue was accepted")
        atomic_json(heldout_queue_path, heldout_queue)

        suite_dir = base / "suite"
        assets = suite_dir / "assets"
        assets.mkdir(parents=True)
        graph_path = assets / "community_graph.json"
        methods_path = assets / "methods.json"
        task_path = assets / "task.json"
        oracle_path = assets / "oracle.json"
        prompt_path = assets / "prompt.md"
        environment_path = assets / "environment.json"
        support_path = assets / "baseline_harness.py"
        atomic_json(graph_path, graph)
        atomic_json(
            task_path,
            {
                "schema_version": "community-heldout-task-v2",
                "task_id": "heldout.logits",
                "information_policy": "SYMPTOM_CONTRACT_AND_BASELINE_ONLY",
                "objective": "Reduce held-out logits projection latency.",
                "operator": {
                    "equation": "output = hidden @ weight.T",
                    "input_shapes": ["hidden[B,K]", "weight[V,K]"],
                    "input_dtype": "bfloat16",
                    "output_dtype": "bfloat16",
                    "layout": "contiguous row major",
                    "numerical_contract": "Match the reference tolerance.",
                    "aliasing": "Inputs are read-only and output does not alias.",
                },
                "workload": {
                    "primary_mode": "single-GPU decode",
                    "shape_weights": {"B=1": 1.0},
                    "integration": "held-out projection path",
                    "latency_objective": "Minimize CUDA-event latency.",
                    "required_controls": ["reference output"],
                },
                "hardware": {
                    "device": "test GPU",
                    "compute_capability": "test capability",
                    "memory_gib": 1,
                    "software": "test stack",
                    "allowed_programming_models": ["PyTorch"],
                },
                "baseline": {
                    "implementation": "historical matrix multiply",
                    "observed_symptom": "small-batch latency is material",
                    "bottleneck_status": "UNKNOWN_MUST_BE_MEASURED",
                    "claim_boundary": "TASK_INPUT_NOT_RESULT",
                },
                "acceptance": {
                    "correctness": ["reference agreement"],
                    "performance": ["interleaved CUDA-event median"],
                    "upstream": "A generic guarded implementation.",
                },
            },
        )
        atomic_json(
            oracle_path,
            {
                "schema_version": "community-hidden-oracle-v1",
                "task_id": "heldout.logits",
                "visibility": "HIDDEN_UNTIL_BOTH_ARMS_COMPLETE",
                "reference_pr": "https://github.com/other/project/pull/8",
                "reference_commit": "a" * 40,
                "snapshot_id": "b" * 20,
                "snapshot_manifest_sha256": "c" * 64,
                "solution_families": ["operator-fusion"],
                "key_mechanism": "Fuse the projection with its consumer.",
                "known_risks": ["numerical tolerance"],
                "observed_reference": {"claim_boundary": "TEST_FIXTURE_ONLY"},
            },
        )
        prompt_path.write_text("Optimize the frozen task under its budget.\n")
        support_path.write_text(
            "def baseline(value):\n    return value\n", encoding="utf-8"
        )
        atomic_json(
            environment_path,
            {
                "claim_boundary": "PRE_TRIAL_READ_ONLY_ENVIRONMENT_FACTS",
                "device": "test GPU",
            },
        )

        source_repository = base / "source-repository"
        source_repository.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=source_repository, check=True)
        subprocess.run(
            ["git", "config", "user.name", "Community Evaluation Test"],
            cwd=source_repository,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=source_repository,
            check=True,
        )
        (source_repository / "operator.py").write_text(
            "def project(hidden, weight):\n    return hidden @ weight.T\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "add", "operator.py"], cwd=source_repository, check=True
        )
        subprocess.run(
            ["git", "commit", "-q", "-m", "historical baseline"],
            cwd=source_repository,
            check=True,
        )
        base_revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=source_repository,
            check=True,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
        ).stdout.strip()

        captured_at = datetime.fromisoformat(
            json.loads(Path(captured["manifest"]).read_text())["captured_at"]
        )
        cutoff = captured_at + timedelta(hours=1)
        atomic_json(methods_path, build_snapshot(cutoff.isoformat(), ROOT))
        prior_outcomes_path = assets / "prior-outcomes.json"
        atomic_json(
            prior_outcomes_path,
            {
                "schema_version": "community-prior-outcome-ledger-v1",
                "generated_at": (cutoff - timedelta(minutes=1)).isoformat(),
                "claim_boundary": "ROUTING_FEEDBACK_NOT_TARGET_PERFORMANCE_PROOF",
                "meta_analysis_identity": {
                    "path": "meta-analysis.json",
                    "sha256": "d" * 64,
                },
                "policy": {
                    "learn_from": "PRIMARY_REALIZED_ONLY",
                    "heldout_loss_action": "REQUIRE_CONTEXT_GUARD",
                    "minimum_directional_observations": 2,
                },
                "inventory": {
                    "primary_pair_count": 1,
                    "prior_observation_count": 1,
                    "event_prior_count": 1,
                    "method_prior_count": 0,
                    "guarded_prior_count": 1,
                    "downranked_prior_count": 0,
                    "upranked_prior_count": 0,
                },
                "observations": [
                    {
                        "pair_identity": {
                            "path": "past-pair.json",
                            "sha256": "e" * 64,
                        },
                        "suite_id": "past-suite",
                        "task_id": "past.logits",
                        "repeat_index": 1,
                        "prior_kind": "EVENT",
                        "prior_id": "example.fused-dequant-logits",
                        "candidate_ids": ["past-candidate"],
                        "deltas": {
                            "time_to_first_correct_seconds_saved": -2.0,
                            "best_speedup_gain": -0.01,
                            "heldout_pass_count_gain": -1.0,
                        },
                    }
                ],
                "aggregates": [
                    {
                        "prior_kind": "EVENT",
                        "prior_id": "example.fused-dequant-logits",
                        "observation_count": 1,
                        "task_count": 1,
                        "ttfc": {"wins": 0, "losses": 1, "ties": 0, "missing": 0},
                        "best_speedup": {"wins": 0, "losses": 1, "ties": 0, "missing": 0},
                        "heldout_loss_count": 1,
                        "routing_adjustment": "REQUIRE_CONTEXT_GUARD",
                    }
                ],
            },
        )
        prior_context_path = assets / "prior-context-distinction.json"
        atomic_json(
            prior_context_path,
            {
                "schema_version": "community-prior-context-distinction-v1",
                "generated_at": (cutoff + timedelta(hours=1)).isoformat(),
                "claim_boundary": "ROUTING_EXCEPTION_NOT_PERFORMANCE_EVIDENCE",
                "task_id": "heldout.logits",
                "prior_outcome_ledger_sha256": sha256_file(prior_outcomes_path),
                "exceptions": [
                    {
                        "prior_kind": "EVENT",
                        "prior_id": "example.fused-dequant-logits",
                        "failed_task_ids": ["past.logits"],
                        "material_differences": [
                            {
                                "dimension": "NUMERICAL_CONTRACT",
                                "failed_context": "Exact equality was required.",
                                "current_context": "A frozen reference tolerance is allowed.",
                                "causal_rationale": "The prior failure was caused by exact-rounding divergence, which this task can test under its explicit tolerance.",
                            }
                        ],
                    }
                ],
            },
        )
        modulation_task_path = assets / "modulation-task.json"
        atomic_json(
            modulation_task_path,
            {
                "objective": "Fuse a strided modulation and residual path.",
                "operator": {
                    "equation": "rms = rsqrt(sum of squares); output = residual + normalized * affine",
                    "input_shapes": ["x[S,2048]", "scale[S,1]", "shift[S,1]"],
                    "input_dtype": "bfloat16",
                    "output_dtype": "bfloat16",
                    "layout": "row activation with strided modulation views",
                    "numerical_contract": "Preserve the residual rounding boundary.",
                },
                "workload": {"primary_mode": "row reduction normalization"},
                "baseline": {"implementation": "materialized eager launches"},
            },
        )
        shortlist_path = assets / "modulation-shortlist.json"
        shortlist = build_prior_shortlist(
            modulation_task_path,
            environment_path,
            graph_path,
            methods_path,
            shortlist_path,
            ROOT,
        )
        shortlisted_methods = [row["id"] for row in shortlist["methods"]]
        assert shortlisted_methods[0] == "triton-row-reduction-fusion"
        assert "cuda-hierarchical-scan-decomposition" not in shortlisted_methods
        assert shortlist["policy"]["max_methods"] == 3
        assert shortlist["routing"]["recommendation"] == "CONSULT_BEFORE_FIRST_CANDIDATE"
        assert shortlist["routing"]["top_method_id"] == "triton-row-reduction-fusion"
        assert shortlist["rejections"]["method_provenance_gate"] > 0
        guarded_shortlist_path = assets / "guarded-shortlist.json"
        guarded_shortlist = build_prior_shortlist(
            task_path,
            environment_path,
            graph_path,
            methods_path,
            guarded_shortlist_path,
            ROOT,
            prior_outcomes_path,
        )
        assert not guarded_shortlist["events"]
        assert guarded_shortlist["rejections"]["event_prior_guard"] == 1
        exception_shortlist_path = assets / "exception-shortlist.json"
        exception_shortlist = build_prior_shortlist(
            task_path,
            environment_path,
            graph_path,
            methods_path,
            exception_shortlist_path,
            ROOT,
            prior_outcomes_path,
            prior_context_path,
        )
        assert exception_shortlist["events"][0]["id"] == (
            "example.fused-dequant-logits"
        )
        assert exception_shortlist["events"][0]["prior_outcome"] == {
            "routing_adjustment": "REQUIRE_CONTEXT_GUARD",
            "score_delta": 0.0,
            "observation_count": 1,
            "task_count": 1,
            "heldout_loss_count": 1,
            "context_distinction_applied": True,
        }
        suite = {
            "schema_version": "community-temporal-suite-v1",
            "suite_id": "example.temporal-v1",
            "cutoff_at": cutoff.isoformat(),
            "claim_boundary": "EVALUATION_PROTOCOL_ONLY",
            "training_graph": identity(graph_path, suite_dir),
            "training_methods": identity(methods_path, suite_dir),
            "training_prior_outcomes": identity(prior_outcomes_path, suite_dir),
            "protocol": {
                "arms": ["CONTROL", "COMMUNITY_AUGMENTED"],
                "repeats": 2,
                "randomized_order": True,
                "random_seed": 20260906,
                "network_policy": "DISABLED_AFTER_MATERIALIZATION",
                "model_identity": "same-model-same-settings",
                "prompt_identity": identity(prompt_path, suite_dir),
                "environment_identity": identity(environment_path, suite_dir),
                "task_packet_contract": "STRICT_V2",
                "budgets": {
                    "wall_clock_seconds": 900,
                    "max_command_seconds": 120,
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
                    "task_id": "heldout.logits",
                    "available_at": (cutoff + timedelta(hours=1)).isoformat(),
                    "repository": "other/project",
                    "pr_number": 8,
                    "base_revision": base_revision,
                    "target_hardware": "test GPU",
                    "packet": identity(task_path, suite_dir),
                    "hidden_oracle": identity(oracle_path, suite_dir),
                    "prior_context_distinction": identity(
                        prior_context_path, suite_dir
                    ),
                    "support": [
                        {
                            "source": identity(support_path, suite_dir),
                            "target": "baseline.py",
                        }
                    ],
                }
            ],
        }
        suite_path = suite_dir / "suite.json"
        atomic_json(suite_path, suite)
        assert validate_suite(suite_path, corpus, ROOT)["status"] == "PASS"
        late_prior_path = assets / "late-prior-outcomes.json"
        late_prior = json.loads(prior_outcomes_path.read_text(encoding="utf-8"))
        late_prior["generated_at"] = (cutoff + timedelta(seconds=1)).isoformat()
        atomic_json(late_prior_path, late_prior)
        late_suite = json.loads(json.dumps(suite))
        late_suite["training_prior_outcomes"] = identity(
            late_prior_path, suite_dir
        )
        late_suite["tasks"][0].pop("prior_context_distinction")
        atomic_json(suite_path, late_suite)
        try:
            validate_suite(suite_path, corpus, ROOT)
        except ValueError as error:
            assert "prior outcome ledger was generated after cutoff" in str(error)
        else:
            raise AssertionError("post-cutoff prior outcomes were accepted")
        bad_context_path = assets / "bad-prior-context-distinction.json"
        bad_context = json.loads(prior_context_path.read_text(encoding="utf-8"))
        bad_context["exceptions"][0]["failed_task_ids"] = ["invented-task"]
        atomic_json(bad_context_path, bad_context)
        bad_context_suite = json.loads(json.dumps(suite))
        bad_context_suite["tasks"][0]["prior_context_distinction"] = identity(
            bad_context_path, suite_dir
        )
        atomic_json(suite_path, bad_context_suite)
        try:
            validate_suite(suite_path, corpus, ROOT)
        except ValueError as error:
            assert "omits or invents failed tasks" in str(error)
        else:
            raise AssertionError("invalid prior context exception was accepted")
        atomic_json(suite_path, suite)

        prospective_oracle_path = assets / "prospective-oracle.json"
        prospective_task = suite["tasks"][0]
        atomic_json(
            prospective_oracle_path,
            {
                "schema_version": "community-hidden-oracle-v1",
                "task_id": "heldout.logits",
                "visibility": "HIDDEN_UNTIL_BOTH_ARMS_COMPLETE",
                "prospective_seal": {
                    "sealed_at": prospective_task["available_at"],
                    "baseline_revision": base_revision,
                    "task_packet_sha256": prospective_task["packet"]["sha256"],
                    "solution_status": "UNKNOWN_AT_SEAL",
                },
                "solution_families": ["UNKNOWN_AT_SEAL"],
                "key_mechanism": "UNKNOWN_AT_SEAL",
                "known_risks": ["The winning architecture is unknown."],
                "observed_reference": {
                    "claim_boundary": "NO_RESULT_AVAILABLE_AT_SEAL"
                },
            },
        )
        prospective_suite = json.loads(json.dumps(suite))
        prospective_suite["tasks"][0].pop("pr_number")
        prospective_suite["tasks"][0]["prospective_id"] = "local-seal-v1"
        prospective_suite["tasks"][0]["hidden_oracle"] = identity(
            prospective_oracle_path, suite_dir
        )
        atomic_json(suite_path, prospective_suite)
        assert validate_suite(suite_path, corpus, ROOT)["status"] == "PASS"
        prospective_audit = audit_task_packets(
            suite_path, base / "prospective-task-audit.json", ROOT
        )
        assert prospective_audit["tasks"][0]["risk"] == "LOW"
        assert prospective_audit["tasks"][0]["key_mechanism_token_recall"] == 0.0
        atomic_json(suite_path, suite)

        valid_task_packet = json.loads(task_path.read_text(encoding="utf-8"))
        invalid_task_packet = json.loads(task_path.read_text(encoding="utf-8"))
        invalid_task_packet["workload"]["shape_weights"]["B=1"] = 0.9
        atomic_json(task_path, invalid_task_packet)
        suite["tasks"][0]["packet"] = identity(task_path, suite_dir)
        atomic_json(suite_path, suite)
        try:
            validate_suite(suite_path, corpus, ROOT)
        except ValueError as error:
            assert "shape weights sum" in str(error)
        else:
            raise AssertionError("strict task weights not summing to one were accepted")
        atomic_json(task_path, valid_task_packet)
        suite["tasks"][0]["packet"] = identity(task_path, suite_dir)
        atomic_json(suite_path, suite)

        schedule_dir = base / "scheduled"
        schedule_result = materialize_suite(
            suite_path, corpus, schedule_dir, ROOT
        )
        assert schedule_result["entry_count"] == 4
        schedule_path = schedule_dir / "schedule.json"
        assert validate_schedule(schedule_path, ROOT)["status"] == "PASS"
        schedule_summary = summarize_schedule_run(
            schedule_path, base / "schedule-summary.json", ROOT
        )
        assert schedule_summary["counts"]["CONTROL"]["INCOMPLETE"] == 2
        assert schedule_summary["counts"]["COMMUNITY_AUGMENTED"]["INCOMPLETE"] == 2
        packet_audit = audit_task_packets(
            suite_path, base / "task-packet-audit.json", ROOT
        )
        assert packet_audit["counts"]["LOW"] == 1
        scheduled = json.loads(schedule_path.read_text(encoding="utf-8"))
        assert {
            (entry["repeat_index"], entry["arm"])
            for entry in scheduled["entries"]
        } == {
            (1, "CONTROL"),
            (1, "COMMUNITY_AUGMENTED"),
            (2, "CONTROL"),
            (2, "COMMUNITY_AUGMENTED"),
        }
        assert all(
            not (schedule_dir / entry["trial_directory"] / "input" / "oracle.json").exists()
            for entry in scheduled["entries"]
        )

        control_dir = base / "control"
        community_dir = base / "community"
        materialize_trial(
            suite_path,
            corpus,
            "heldout.logits",
            "CONTROL",
            1,
            control_dir,
            ROOT,
        )
        materialize_trial(
            suite_path,
            corpus,
            "heldout.logits",
            "COMMUNITY_AUGMENTED",
            1,
            community_dir,
            ROOT,
        )
        assert not (control_dir / "knowledge").exists()
        assert (community_dir / "knowledge" / "community_graph.json").is_file()
        assert (community_dir / "knowledge" / "methods.json").is_file()
        assert (community_dir / "knowledge" / "prior_outcomes.json").is_file()
        assert (
            community_dir / "knowledge" / "prior_context_distinction.json"
        ).is_file()
        shortlist_path = community_dir / "knowledge" / "prior_shortlist.json"
        assert shortlist_path.is_file()
        shortlist = json.loads(shortlist_path.read_text(encoding="utf-8"))
        assert shortlist["schema_version"] == "community-prior-shortlist-v1"
        assert shortlist["policy"]["hard_gate_policy"] == "FAIL_CLOSED"
        assert len(shortlist["events"]) <= 2
        assert len(shortlist["methods"]) <= 2
        community_manifest = json.loads(
            (community_dir / "trial.json").read_text(encoding="utf-8")
        )
        assert community_manifest["prior_shortlist"] == identity(
            shortlist_path, community_dir
        )
        assert community_manifest["prior_outcome_ledger"] == identity(
            community_dir / "knowledge" / "prior_outcomes.json", community_dir
        )
        assert community_manifest["access_policy"]["prior_outcome_knowledge"] == (
            "FROZEN_LEDGER_ONLY"
        )
        assert community_manifest["knowledge_realization_required"] is True
        assert not (control_dir / "input" / "oracle.json").exists()
        assert not (community_dir / "input" / "oracle.json").exists()
        assert (control_dir / "input" / "result.schema.json").is_file()
        assert (control_dir / "input" / "executor.md").is_file()
        assert (control_dir / "input" / "frontier_contract.json").is_file()
        frontier_contract = json.loads(
            (control_dir / "input" / "frontier_contract.json").read_text(
                encoding="utf-8"
            )
        )
        assert frontier_contract["policy"]["qualification_checkpoint"] == (
            "FIRST_MATERIAL_CORRECT_BEFORE_NEXT_CANDIDATE"
        )
        assert (control_dir / "input" / "opportunity-ranking.schema.json").is_file()
        assert (control_dir / "input" / "frontier-closure.schema.json").is_file()
        executor_text = (control_dir / "input" / "executor.md").read_text(
            encoding="utf-8"
        )
        assert "causal screening result" in executor_text
        assert "exit zero" in executor_text
        assert "FIRST_MATERIAL_CORRECT_BEFORE_NEXT_CANDIDATE" in executor_text
        assert (control_dir / "input" / "environment.json").is_file()
        assert (control_dir / "harness" / "baseline.py").is_file()
        assert (community_dir / "harness" / "baseline.py").is_file()
        assert control_dir.joinpath("harness", "baseline.py").read_bytes() == (
            community_dir / "harness" / "baseline.py"
        ).read_bytes()
        assert (control_dir / "evidence").is_dir()
        assert (community_dir / "evidence").is_dir()
        assert base_revision in control_dir.joinpath("trial.json").read_text(
            encoding="utf-8"
        )

        source_receipt = prepare_trial_source(control_dir, source_repository, ROOT)
        assert source_receipt["status"] == "PASS"
        assert source_receipt["revision"] == base_revision
        assert source_receipt["file_count"] == 1
        assert validate_source_receipt(control_dir, ROOT) == source_receipt
        (control_dir / "source" / "operator.py").write_text(
            "tampered\n", encoding="utf-8"
        )
        try:
            validate_source_receipt(control_dir, ROOT)
        except ValueError as error:
            assert "changed after binding" in str(error)
        else:
            raise AssertionError("tampered historical source tree was accepted")

        invalid_execution = base / "invalid-execution"
        materialize_trial(
            suite_path,
            corpus,
            "heldout.logits",
            "CONTROL",
            2,
            invalid_execution,
            ROOT,
        )
        events = [
            {"type": "thread.started", "thread_id": "isolated"},
            *[
                {
                    "type": "item.started",
                    "item": {
                        "type": "command_execution",
                        "command": f"python evidence/failure-{index}.py",
                    },
                }
                for index in range(3)
            ],
            *[
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "status": "completed",
                        "exit_code": 1,
                    },
                }
                for _ in range(3)
            ],
        ]
        (invalid_execution / "executor.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in events),
            encoding="utf-8",
        )
        (invalid_execution / "executor.stderr.log").write_text("", encoding="utf-8")
        execution_audit = audit_codex_execution(invalid_execution, root=ROOT)
        assert execution_audit["status"] == "FAIL"
        assert execution_audit["observations"]["technical_repair_lower_bound"] == 3
        assert "TECHNICAL_REPAIR_BUDGET_EXCEEDED" in execution_audit["violations"]
        assert "TURN_NOT_COMPLETED" in execution_audit["violations"]
        assert "RESULT_MISSING" in execution_audit["violations"]

        for trial_dir in (control_dir, community_dir):
            evidence_path = trial_dir / "evidence.json"
            atomic_json(evidence_path, {"correctness": "PASS"})
            evidence = identity(evidence_path, trial_dir)
            if trial_dir == control_dir:
                rows = [
                    candidate(
                        "control-one",
                        100,
                        420,
                        "schedule-tuning",
                        1.04,
                        1.01,
                        evidence,
                        False,
                    )
                ]
                elapsed = 700
            else:
                rows = [
                    candidate(
                        "community-one",
                        20,
                        140,
                        "operator-fusion",
                        1.18,
                        1.08,
                        evidence,
                        True,
                    ),
                    candidate(
                        "community-two",
                        60,
                        250,
                        "data-layout",
                        1.10,
                        1.03,
                        evidence,
                        False,
                    ),
                ]
                elapsed = 500
            write_result(trial_dir, rows, elapsed)

        draft_result = json.loads(
            (control_dir / "result.json").read_text(encoding="utf-8")
        )
        del draft_result["frontier_closure"]
        draft_path = control_dir / "finalizer_draft.json"
        atomic_json(
            draft_path,
            {
                "frontier_closure": json.loads(
                    (control_dir / "evidence" / "frontier-closure.json").read_text(
                        encoding="utf-8"
                    )
                ),
                "result": draft_result,
            },
        )
        commit_events = commit_finalizer_draft(control_dir, draft_path, 650.0, 1)
        committed_result = json.loads(
            (control_dir / "result.json").read_text(encoding="utf-8")
        )
        assert committed_result["completion_status"] == "BUDGET_EXHAUSTED"
        assert committed_result["technical_repair_attempts"] == 1
        assert committed_result["elapsed_seconds"] == 700
        assert committed_result["frontier_closure"] == identity(
            control_dir / "evidence" / "frontier-closure.json", control_dir
        )
        assert commit_events[0]["type"] == "runner.result_committed"
        assert commit_events[1]["item"]["type"] == "agent_message"

        try:
            assess_trial(control_dir, ROOT, require_execution_audit=True)
        except ValueError as error:
            assert "execution audit required" in str(error)
        else:
            raise AssertionError("unaudited trial was accepted by strict assessment")

        unicode_output_events = [
            {"type": "thread.started", "thread_id": "isolated"},
            {
                "type": "item.started",
                "item": {
                    "type": "command_execution",
                    "command": "python evidence/read_minified_js.py",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": "before\u2028after and before\u2029after",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": (control_dir / "result.json").read_text(encoding="utf-8"),
                },
            },
            {"type": "turn.completed"},
        ]
        (control_dir / "executor.jsonl").write_text(
            "".join(
                json.dumps(event, ensure_ascii=False) + "\n"
                for event in unicode_output_events
            ),
            encoding="utf-8",
        )
        (control_dir / "executor.stderr.log").write_text("", encoding="utf-8")
        unicode_audit = audit_codex_execution(control_dir, root=ROOT)
        assert unicode_audit["status"] == "PASS"
        assert unicode_audit["observations"]["malformed_line_count"] == 0
        assert unicode_audit["observations"][
            "ranking_preceded_production_edit"
        ] is None
        assess_trial(control_dir, ROOT, require_execution_audit=True)

        ranking_first_events = [
            {
                "type": "item.completed",
                "item": {
                    "type": "file_change",
                    "status": "completed",
                    "changes": [
                        {
                            "path": str(
                                control_dir
                                / "evidence"
                                / "opportunity-ranking.json"
                            ),
                            "kind": "add",
                        }
                    ],
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "type": "file_change",
                    "status": "completed",
                    "changes": [
                        {
                            "path": str(control_dir / "source" / "candidate.py"),
                            "kind": "add",
                        }
                    ],
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": (control_dir / "result.json").read_text(
                        encoding="utf-8"
                    ),
                },
            },
            {"type": "turn.completed"},
        ]
        (control_dir / "executor.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in ranking_first_events),
            encoding="utf-8",
        )
        ranking_first_audit = audit_codex_execution(control_dir, root=ROOT)
        assert ranking_first_audit["status"] == "PASS"
        assert ranking_first_audit["observations"][
            "ranking_preceded_production_edit"
        ] is True

        source_first_events = [
            ranking_first_events[1],
            ranking_first_events[0],
            *ranking_first_events[2:],
        ]
        (control_dir / "executor.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in source_first_events),
            encoding="utf-8",
        )
        source_first_audit = audit_codex_execution(control_dir, root=ROOT)
        assert source_first_audit["status"] == "FAIL"
        assert source_first_audit["observations"][
            "ranking_preceded_production_edit"
        ] is False
        assert "OPPORTUNITY_RANKING_NOT_FROZEN_BEFORE_SOURCE_EDIT" in (
            source_first_audit["violations"]
        )

        search_text = "".join(
            json.dumps(event) + "\n" for event in ranking_first_events[:2]
        )
        phase_marker = {
            "type": "runner.finalization_started",
            "search_transcript_sha256": hashlib.sha256(
                search_text.encode("utf-8")
            ).hexdigest(),
        }
        finalizer_tail = ranking_first_events[2:]
        finalized_events = (
            search_text
            + json.dumps(phase_marker, sort_keys=True)
            + "\n"
            + "".join(json.dumps(event) + "\n" for event in finalizer_tail)
        )
        (control_dir / "executor.jsonl").write_text(
            finalized_events, encoding="utf-8", newline="\n"
        )
        finalized_audit = audit_codex_execution(control_dir, root=ROOT)
        assert finalized_audit["status"] == "PASS"
        assert finalized_audit["observations"]["runner_prefix_hash_match"] is True
        assert finalized_audit["observations"][
            "source_change_after_finalization"
        ] is False

        committed_transcript = (
            search_text
            + json.dumps(phase_marker, sort_keys=True)
            + "\n"
            + json.dumps({"type": "turn.completed"})
            + "\n"
            + "".join(
                json.dumps(event, sort_keys=True) + "\n"
                for event in commit_events
            )
        )
        (control_dir / "executor.jsonl").write_text(
            committed_transcript, encoding="utf-8", newline="\n"
        )
        committed_audit = audit_codex_execution(control_dir, root=ROOT)
        assert committed_audit["status"] == "PASS"
        assert committed_audit["observations"]["result_commit_hash_match"] is True

        late_source_change = {
            "type": "item.completed",
            "item": {
                "type": "file_change",
                "status": "completed",
                "changes": [
                    {
                        "path": str(control_dir / "source" / "candidate.py"),
                        "kind": "update",
                    }
                ],
            },
        }
        finalized_with_late_edit = (
            search_text
            + json.dumps(phase_marker, sort_keys=True)
            + "\n"
            + json.dumps(late_source_change)
            + "\n"
            + "".join(json.dumps(event) + "\n" for event in finalizer_tail)
        )
        (control_dir / "executor.jsonl").write_text(
            finalized_with_late_edit, encoding="utf-8", newline="\n"
        )
        late_edit_audit = audit_codex_execution(control_dir, root=ROOT)
        assert late_edit_audit["status"] == "FAIL"
        assert late_edit_audit["observations"][
            "source_change_after_finalization"
        ] is True
        assert "PRODUCTION_SOURCE_EDIT_DURING_FINALIZATION" in (
            late_edit_audit["violations"]
        )

        control_assessment = assess_trial(control_dir, ROOT)
        community_assessment = assess_trial(community_dir, ROOT)
        assert control_assessment["metrics"]["best_speedup"] == 1.04
        assert control_assessment["success_thresholds"][
            "minimum_material_speedup"
        ] == 1.02
        assert community_assessment["metrics"]["upstream_ready_count"] == 1
        assert community_assessment["metrics"]["method_realization_disposition"] == (
            "REALIZED_IN_CANDIDATE"
        )
        assert community_assessment["metrics"]["method_realized_candidate_count"] == 2
        assert community_assessment["metrics"]["frontier_contract_passed"] is True

        original_trial_manifest = json.loads(
            (community_dir / "trial.json").read_text(encoding="utf-8")
        )
        original_shortlist = json.loads(
            shortlist_path.read_text(encoding="utf-8")
        )
        tampered_shortlist = json.loads(json.dumps(original_shortlist))
        tampered_shortlist["events"][0]["prior_outcome"][
            "context_distinction_applied"
        ] = False
        atomic_json(shortlist_path, tampered_shortlist)
        tampered_manifest = json.loads(json.dumps(original_trial_manifest))
        tampered_manifest["prior_shortlist"] = identity(
            shortlist_path, community_dir
        )
        atomic_json(community_dir / "trial.json", tampered_manifest)
        try:
            assess_trial(community_dir, ROOT)
        except ValueError as error:
            assert "guarded prior was selected without a context distinction" in str(
                error
            )
        else:
            raise AssertionError("a guarded prior bypass was accepted")
        atomic_json(shortlist_path, original_shortlist)
        atomic_json(community_dir / "trial.json", original_trial_manifest)

        # Exhausting either repair or causal-revision capacity is a real search
        # stop even when candidate/compile/measurement slots remain.  The
        # frontier may preserve unknown bounds without pretending they closed.
        original_result = json.loads(
            (community_dir / "result.json").read_text(encoding="utf-8")
        )
        trial_budget = json.loads(
            (community_dir / "trial.json").read_text(encoding="utf-8")
        )["budget"]
        for result_field, budget_field in (
            ("technical_repair_attempts", "max_technical_repairs"),
            ("causal_revisions", "max_causal_revisions"),
        ):
            exhausted = dict(original_result)
            exhausted[result_field] = trial_budget[budget_field]
            atomic_json(community_dir / "result.json", exhausted)
            assess_trial(community_dir, ROOT)
        write_result(community_dir, rows, elapsed)

        # A higher raw screen result is not necessarily selectable.  Only the
        # pre-selected candidate receives held-out validation, and a screen
        # point may also violate a public per-shape performance guard.
        raw_faster = json.loads(
            (community_dir / "result.json").read_text(encoding="utf-8")
        )
        raw_faster["candidates"][1]["speedup"] = 1.20
        raw_faster["candidates"][1]["heldout_correctness"] = "NOT_RUN"
        raw_faster["candidates"][1]["whole_model_speedup"] = None
        atomic_json(community_dir / "result.json", raw_faster)
        raw_faster_assessment = assess_trial(community_dir, ROOT)
        assert raw_faster_assessment["metrics"]["best_speedup"] == 1.18
        write_result(community_dir, rows, elapsed)

        # Transactional commit repairs only conservative, mechanically
        # decidable omissions: unknown bounds cannot prove domination, and an
        # absent treatment receipt means no recorded realization.
        repair_closure = json.loads(
            (community_dir / "evidence" / "frontier-closure.json").read_text(
                encoding="utf-8"
            )
        )
        repair_closure["architectures"][1]["status"] = "DOMINATED"
        repair_closure["architectures"][1]["current_upper_bound"] = {
            "kind": "UNKNOWN",
            "maximum_speedup": None,
            "rationale": "No numeric family-wide bound was established.",
        }
        repair_result = json.loads(
            (community_dir / "result.json").read_text(encoding="utf-8")
        )
        repair_result.pop("frontier_closure")
        repair_result.pop("knowledge_realization")
        repair_result.pop("method_realization")
        repair_draft = community_dir / "repair-finalizer-draft.json"
        atomic_json(
            repair_draft,
            {"frontier_closure": repair_closure, "result": repair_result},
        )
        commit_finalizer_draft(community_dir, repair_draft, elapsed, 0)
        committed_closure = json.loads(
            (community_dir / "evidence" / "frontier-closure.json").read_text(
                encoding="utf-8"
            )
        )
        committed_result = json.loads(
            (community_dir / "result.json").read_text(encoding="utf-8")
        )
        assert committed_closure["architectures"][1]["status"] == (
            "DEADLINE_UNTESTED"
        )
        assert committed_result["knowledge_realization"]["disposition"] == (
            "NO_RELEVANT_COMMUNITY_PRIOR"
        )
        assert committed_result["method_realization"]["disposition"] == (
            "NO_RELEVANT_METHOD_PRIOR"
        )
        assess_trial(community_dir, ROOT)
        valid, preflight_errors = valid_result(
            community_dir / "result.json",
            json.loads((community_dir / "trial.json").read_text(encoding="utf-8")),
        )
        assert valid, preflight_errors
        write_result(community_dir, rows, elapsed)

        timestamp_mismatch = json.loads(
            (community_dir / "result.json").read_text(encoding="utf-8")
        )
        timestamp_mismatch["elapsed_seconds"] = 1
        atomic_json(community_dir / "result.json", timestamp_mismatch)
        valid, preflight_errors = valid_result(
            community_dir / "result.json",
            json.loads((community_dir / "trial.json").read_text(encoding="utf-8")),
        )
        assert not valid
        assert "frontier_generated_after_elapsed" in preflight_errors
        write_result(community_dir, rows, elapsed)
        assert community_assessment["metrics"]["ranked_architecture_count"] == 3
        assert community_assessment["metrics"][
            "community_realization_disposition"
        ] == "REALIZED_IN_CANDIDATE"
        report = compare_trials(
            control_dir, community_dir, base / "comparison.json", ROOT
        )
        assert report["deltas"]["time_to_first_correct_seconds_saved"] == 280
        assert report["deltas"]["best_speedup_gain"] > 0
        assert report["treatment_fidelity"]["any_prior_realized"] is True
        assert report["treatment_fidelity"]["causal_interpretation"] == (
            "TREATMENT_REALIZED"
        )
        single_meta_path = base / "meta-single-realized.json"
        single_meta = build_ab_meta_analysis(base, ROOT)
        atomic_json(single_meta_path, single_meta)
        single_ledger_path = base / "prior-ledger-single-realized.json"
        single_ledger = build_prior_outcome_ledger(single_meta_path, ROOT)
        atomic_json(single_ledger_path, single_ledger)
        assert single_ledger["inventory"]["primary_pair_count"] == 1
        assert single_ledger["inventory"]["prior_observation_count"] == 2
        assert single_ledger["inventory"]["event_prior_count"] == 1
        assert single_ledger["inventory"]["method_prior_count"] == 1
        assert validate_prior_outcome_ledger(single_ledger_path, ROOT)[
            "status"
        ] == "PASS"

        no_treatment = json.loads(
            (community_dir / "result.json").read_text(encoding="utf-8")
        )
        no_treatment["knowledge_realization"] = {
            "inspected_event_ids": [],
            "selected_event_ids": [],
            "disposition": "NO_RELEVANT_COMMUNITY_PRIOR",
            "candidate_ids": [],
            "rationale": "No event changed the local candidate plan.",
            "evidence": [],
        }
        atomic_json(community_dir / "result.json", no_treatment)
        no_treatment_report = compare_trials(
            control_dir, community_dir, base / "comparison-no-treatment.json", ROOT
        )
        assert no_treatment_report["treatment_fidelity"]["any_prior_realized"] is True
        assert no_treatment_report["treatment_fidelity"]["method_prior_realized"] is True
        no_treatment["method_realization"] = {
            "inspected_method_ids": [],
            "selected_method_id": None,
            "disposition": "NO_RELEVANT_METHOD_PRIOR",
            "instantiation": None,
            "candidate_ids": [],
            "rationale": "No method changed the local candidate plan.",
            "evidence": [],
        }
        atomic_json(community_dir / "result.json", no_treatment)
        no_treatment_report = compare_trials(
            control_dir, community_dir, base / "comparison-no-realized-prior.json", ROOT
        )
        assert no_treatment_report["treatment_fidelity"]["any_prior_realized"] is False
        assert no_treatment_report["treatment_fidelity"]["causal_interpretation"] == (
            "ASSIGNMENT_WITHOUT_REALIZED_PRIOR"
        )
        meta_path = base / "meta-analysis.json"
        meta = build_ab_meta_analysis(base, ROOT)
        atomic_json(meta_path, meta)
        assert meta["inventory"]["report_count"] == 3
        assert meta["inventory"]["primary_realized_count"] == 2
        assert meta["inventory"]["assignment_only_count"] == 1
        assert meta["verdict"] == "INSUFFICIENT_PRIMARY_EVIDENCE"
        assert validate_ab_meta_analysis(meta_path, ROOT)["status"] == "PASS"
        write_result(community_dir, rows, elapsed)

        ranking_path = community_dir / "evidence" / "opportunity-ranking.json"
        closure_path = community_dir / "evidence" / "frontier-closure.json"
        result_path = community_dir / "result.json"
        incomplete_ranking = json.loads(ranking_path.read_text(encoding="utf-8"))
        incomplete_ranking["architectures"][2]["dimension_ids"] = [
            "launch-materialization"
        ]
        atomic_json(ranking_path, incomplete_ranking)
        closure = json.loads(closure_path.read_text(encoding="utf-8"))
        closure["opportunity_ranking_identity"] = identity(
            ranking_path, community_dir
        )
        atomic_json(closure_path, closure)
        invalid_frontier_result = json.loads(result_path.read_text(encoding="utf-8"))
        invalid_frontier_result["frontier_closure"] = identity(
            closure_path, community_dir
        )
        atomic_json(result_path, invalid_frontier_result)
        try:
            assess_trial(community_dir, ROOT)
        except ValueError as error:
            assert "omits required dimensions" in str(error)
        else:
            raise AssertionError("self-narrowed frontier was accepted")
        write_result(community_dir, rows, elapsed)

        open_frontier = json.loads(closure_path.read_text(encoding="utf-8"))
        open_frontier["architectures"][1]["current_upper_bound"] = {
            "kind": "UNKNOWN",
            "maximum_speedup": None,
            "rationale": "The untested bound is still unknown.",
        }
        atomic_json(closure_path, open_frontier)
        invalid_frontier_result = json.loads(result_path.read_text(encoding="utf-8"))
        invalid_frontier_result["frontier_closure"] = identity(
            closure_path, community_dir
        )
        atomic_json(result_path, invalid_frontier_result)
        try:
            assess_trial(community_dir, ROOT)
        except ValueError as error:
            assert "needs a quantified domination bound" in str(error)
        else:
            raise AssertionError("complete trial with an open unknown bound was accepted")
        write_result(community_dir, rows, elapsed)

        open_selected = json.loads(closure_path.read_text(encoding="utf-8"))
        open_selected["architectures"][0]["current_upper_bound"] = {
            "kind": "QUANTIFIED",
            "maximum_speedup": open_selected["selected_speedup"] * 2,
            "rationale": "A material same-family gap remains open.",
        }
        open_selected["generated_at_seconds"] = 480
        atomic_json(closure_path, open_selected)
        invalid_frontier_result = json.loads(result_path.read_text(encoding="utf-8"))
        invalid_frontier_result["elapsed_seconds"] = 480
        invalid_frontier_result["frontier_closure"] = identity(
            closure_path, community_dir
        )
        atomic_json(result_path, invalid_frontier_result)
        try:
            assess_trial(community_dir, ROOT)
        except ValueError as error:
            assert "selected architecture retains a material open bound" in str(error)
        else:
            raise AssertionError("early stop with an open selected family was accepted")
        write_result(community_dir, rows, elapsed)

        no_selection = json.loads(closure_path.read_text(encoding="utf-8"))
        no_selection["selected_candidate_id"] = None
        no_selection["selected_speedup"] = None
        no_selection["architectures"][0]["status"] = "EVALUATED"
        atomic_json(closure_path, no_selection)
        no_selection_result = json.loads(result_path.read_text(encoding="utf-8"))
        no_selection_result["frontier_closure"] = identity(
            closure_path, community_dir
        )
        atomic_json(result_path, no_selection_result)
        no_selection_assessment = assess_trial(community_dir, ROOT)
        assert no_selection_assessment["metrics"]["best_speedup"] is None
        assert no_selection_assessment["metrics"][
            "time_to_first_improvement_seconds"
        ] is None
        assert no_selection_assessment["metrics"][
            "time_to_first_correct_seconds"
        ] is not None
        write_result(community_dir, rows, elapsed)

        invalid_method = json.loads(
            (community_dir / "result.json").read_text(encoding="utf-8")
        )
        invalid_method["method_realization"]["selected_method_id"] = "unknown-method"
        atomic_json(community_dir / "result.json", invalid_method)
        try:
            assess_trial(community_dir, ROOT)
        except ValueError as error:
            assert "selected method" in str(error)
        else:
            raise AssertionError("unknown selected method was accepted")
        write_result(community_dir, rows, elapsed)

        over_budget = json.loads(
            (community_dir / "result.json").read_text(encoding="utf-8")
        )
        over_budget["elapsed_seconds"] = 901
        atomic_json(community_dir / "result.json", over_budget)
        try:
            assess_trial(community_dir, ROOT)
        except ValueError as error:
            assert "frozen budget" in str(error)
        else:
            raise AssertionError("over-budget trial was accepted")

        leaking = json.loads(suite_path.read_text(encoding="utf-8"))
        leaking["cutoff_at"] = "2025-12-31T00:00:00+00:00"
        atomic_json(suite_path, leaking)
        try:
            validate_suite(suite_path, corpus, ROOT)
        except ValueError as error:
            assert "available after cutoff" in str(error)
        else:
            raise AssertionError("post-cutoff training evidence was accepted")

    print("community evaluation test: PASS")


if __name__ == "__main__":
    main()
