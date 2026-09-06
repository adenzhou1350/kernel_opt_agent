#!/usr/bin/env python3
"""Exercise temporal isolation and fixed-budget community A/B scoring."""

from __future__ import annotations

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
    validate_suite,
)
from community_knowledge import (
    atomic_json,
    build_graph,
    capture_pr,
    sha256_file,
)
from community_trial_runner import command_for
from test_community_knowledge import FakeGitHubClient, event_for
from method_library import build_snapshot


def identity(path: Path, base: Path) -> dict:
    return {
        "path": path.relative_to(base).as_posix(),
        "sha256": sha256_file(path),
    }


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
        method_realization = {
            "inspected_method_ids": [methods["included_method_ids"][0]],
            "selected_method_id": methods["included_method_ids"][0],
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
        graph = json.loads(
            (trial_dir / "knowledge" / "community_graph.json").read_text(
                encoding="utf-8"
            )
        )
        result["knowledge_realization"] = {
            "inspected_event_ids": [graph["nodes"][0]["event_id"]],
            "selected_event_ids": [graph["nodes"][0]["event_id"]],
            "disposition": "REALIZED_IN_CANDIDATE",
            "candidate_ids": [row["candidate_id"] for row in rows],
            "rationale": "The synthetic event changed the tested candidate plan.",
            "evidence": [rows[0]["evidence"][0]],
        }
    atomic_json(
        trial_dir / "result.json",
        result,
    )


def main() -> None:
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
        suite = {
            "schema_version": "community-temporal-suite-v1",
            "suite_id": "example.temporal-v1",
            "cutoff_at": cutoff.isoformat(),
            "claim_boundary": "EVALUATION_PROTOCOL_ONLY",
            "training_graph": identity(graph_path, suite_dir),
            "training_methods": identity(methods_path, suite_dir),
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
        assert community_manifest["knowledge_realization_required"] is True
        assert not (control_dir / "input" / "oracle.json").exists()
        assert not (community_dir / "input" / "oracle.json").exists()
        assert (control_dir / "input" / "result.schema.json").is_file()
        assert (control_dir / "input" / "executor.md").is_file()
        assert (control_dir / "input" / "frontier_contract.json").is_file()
        assert (control_dir / "input" / "opportunity-ranking.schema.json").is_file()
        assert (control_dir / "input" / "frontier-closure.schema.json").is_file()
        executor_text = (control_dir / "input" / "executor.md").read_text(
            encoding="utf-8"
        )
        assert "causal screening result" in executor_text
        assert "exit zero" in executor_text
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
        assess_trial(control_dir, ROOT, require_execution_audit=True)

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
        atomic_json(closure_path, open_selected)
        invalid_frontier_result = json.loads(result_path.read_text(encoding="utf-8"))
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
