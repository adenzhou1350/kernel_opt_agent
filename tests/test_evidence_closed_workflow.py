#!/usr/bin/env python3
"""Forward-test the rank -> plan -> dispatch -> bind -> reconcile loop."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path), "sha256": digest(path)}


def run(*args: str) -> dict:
    completed = subprocess.run([sys.executable, *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode:
        raise AssertionError((args, completed.stdout, completed.stderr))
    return json.loads(completed.stdout)


def run_failure(*args: str) -> dict:
    completed = subprocess.run([sys.executable, *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert completed.returncode != 0, (args, completed.stdout, completed.stderr)
    return json.loads(completed.stdout)


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        run_dir = root / "runs/strict-loop"
        for child in ("models", "traces", "experiments", "microbench_candidates"):
            (run_dir / child).mkdir(parents=True)
        write(run_dir / "workload.json", {
            "schema_version": "workload-v1", "name": "strict-loop",
            "cases": [{"id": "c", "parameters": {}, "weight": 1.0}],
            "objective": {"metric": "gpu_active_us", "statistic": "median", "direction": "minimize"},
        })
        write(run_dir / "hardware.json", json.loads((ROOT / "tests/fixtures/hardware.json").read_text()))
        resource_row = {
            "resource_id": "s.kernel_dispatch",
            "matched_saturation": {"status": "UNKNOWN"},
            "utilization": {"status": "UNKNOWN", "value_percent": 0.0},
            "critical_path": {"status": "UNKNOWN", "probability": 0.8},
            "unresolved_request_ids": ["req-launch"],
        }
        write(run_dir / "models/resource_balance.json", {
            "schema_version": "resource-balance-ledger-v1", "status": "INITIALIZED",
            "cases": [{
                "case_id": "c", "resource_rows": [resource_row],
                "critical_path": {"stage_gpu_active_us": {"s": 10.0}, "total_us": 10.0},
            }],
        })
        write(run_dir / "models/schedule_model.json", {"schema_version": "resource-schedule-model-v1", "revision": 0})
        frontier_path = run_dir / "models/tradeoff_frontier.json"
        write(frontier_path, {"schema_version": "tradeoff-frontier-v1", "revision": 0})
        frontier_snapshot = run_dir / "models/decisions/launch-frontier-snapshot.json"
        write(frontier_snapshot, json.loads(frontier_path.read_text()))
        write(run_dir / "models/global_schedule_state.json", {
            "schema_version": "global-schedule-state-v2",
            "owner": {"role": "GLOBAL_SCHEDULER", "owner_id": "scheduler", "exclusive_authority": ["ACCEPT_GLOBAL_CANDIDATE"]},
            "supervisor": {"role": "GLOBAL_SUPERVISOR", "owner_id": "supervisor", "exclusive_authority": ["APPROVE_EXPERIMENT_DISPATCH"]},
        })
        write(run_dir / "models/optimization_plan.json", {
            "screening_budget": {"max_configurations": 2, "max_samples_per_configuration": 9, "max_process_launches": 8, "max_wall_clock_minutes": 5.0},
            "qualification_budget": {"max_configurations": 2, "max_samples_per_configuration": 30, "max_process_launches": 12, "max_wall_clock_minutes": 10.0},
            "max_revisions_per_decision": 1,
        })
        candidate_paths = []
        for candidate_id, interval in (("candidate-a", [8.0, 10.0]), ("candidate-b", [8.5, 10.5])):
            path = run_dir / f"candidates/{candidate_id}.json"
            write(path, {"candidate_id": candidate_id, "schedule": "synthetic"})
            candidate_paths.append((candidate_id, path, interval))
        decision_path = run_dir / "models/decisions/launch-decision.json"
        write(decision_path, {
            "schema_version": "decision-contract-v1", "decision_id": "launch-decision",
            "status": "READY_FOR_SUPERVISOR", "issued_by": {"role": "GLOBAL_SCHEDULER", "owner_id": "scheduler"},
            "objective_identity": identity(run_dir / "workload.json"), "frontier_identity": identity(frontier_snapshot),
            "candidate_bindings": [
                {"candidate_id": candidate_id, "artifact_identity": identity(path), "predicted_objective": {"lower": interval[0], "upper": interval[1], "unit": "us"}}
                for candidate_id, path, interval in candidate_paths
            ],
            "top_two_candidate_ids": ["candidate-a", "candidate-b"],
            "decision_metric": {"name": "gpu_active_us", "unit": "us", "direction": "minimize"},
            "measurement_need": {
                "quantity_id": "launch-envelope-us", "model_location": "schedule.launch_envelope_us",
                "equation": "delta = candidate_a_us - candidate_b_us", "current_interval": {"lower": 0.0, "upper": 1.0, "unit": "us"},
                "top_two_delta_interval": {"lower": -0.5, "upper": 0.5, "unit": "us"},
                "decision_boundary": {"value": 0.5, "unit": "us"}, "required_precision": {"value": 0.1, "unit": "us"},
                "outcome_mapping": [{"when": "below 0.5", "select": "candidate-a"}, {"when": "above 0.5", "select": "candidate-b"}],
                "maximum_decision_value": {"value": 2.0, "unit": "us"}, "decision_flip_probability": 0.5,
                "expected_uncertainty_reduction": 0.8,
            },
            "experiment_budget": {
                "screening": {"max_configurations": 2, "max_samples_per_configuration": 9, "max_process_launches": 8, "max_wall_clock_minutes": 5.0},
                "qualification": {"max_configurations": 2, "max_samples_per_configuration": 30, "max_process_launches": 12, "max_wall_clock_minutes": 10.0},
                "max_revisions": 1,
            },
            "stop_rules": ["stop when the top-two ordering cannot flip"], "evidence": [],
        })
        measurability_path = run_dir / "models/decisions/launch-measurability.json"
        write(measurability_path, {
            "schema_version": "measurability-contract-v1", "status": "READY_FOR_SUPERVISOR",
            "issued_by": {"role": "MICROARCHITECTURE_ANALYST", "analyst_id": "analyst"},
            "decision_contract_identity": identity(decision_path), "quantity_id": "launch-envelope-us",
            "identifiability": "ATOMIC_IDENTIFIABLE", "selected_method": "ATOMIC_MICROBENCH",
            "observable": {"name": "gpu active duration", "unit": "us", "measurement_window": "one matched launch"},
            "causal_mapping": {"formula": "observable = launch envelope", "assumptions": [], "confounders": [],
                "controls": ["zero", "positive", "negative", "live"], "falsification_condition": "A/B prediction error exceeds 0.1 us"},
            "expected_precision": {"absolute": 0.05, "unit": "us"}, "required_tier": "SCREENING", "evidence": [],
        })
        request = {
            "request_id": "req-launch", "status": "PROPOSED", "issued_by_role": "GLOBAL_SCHEDULER",
            "workload_cases": ["c"], "model_field": "s.kernel_dispatch.utilization",
            "candidate_decision": "choose launch schedule", "causal_question": "What is the launch envelope?",
            "resource_ids": ["s.kernel_dispatch"], "priority": 0,
            "affected_stage_ids": ["s"],
            "decision_contract": identity(decision_path), "measurability_contract": identity(measurability_path),
            "experiment_class": "SCREENING", "tested_candidate_ids": ["candidate-a", "candidate-b"],
            "implementation_owner": {"role": "EXPERIMENT_AGENT", "actor_id": "experimenter"},
            "execution_budget": {"samples_per_configuration": 9, "process_launches": 7, "max_wall_clock_minutes": 5.0},
            "sensitivity": {"candidate_specific_decision_value_us": 2.0, "decision_flip_probability": 0.5, "expected_uncertainty_reduction": 0.8, "experiment_cost": "LOW"},
            "controls": ["zero work", "positive control", "negative control", "live sink"],
            "measurement_contract": {"timer": "native GPU timer", "cache": "declared", "geometry": "matched", "correctness": "live result"},
            "expected_sass": ["launch target instructions present"],
            "parameter_matrix": [{"grid": 1}, {"grid": 2}],
            "catalog_resolution": {"catalog_queried": False, "query": {
                "resources": ["kernel_dispatch"], "mechanisms": ["kernel_launch"],
                "boundaries": ["launch"], "qualification": "STATIC_VALIDATED"
            }},
            "result_binding": {"status": "PENDING", "evidence": []},
            "promotion_disposition": {"status": "PENDING", "reason": "review after validation"},
        }
        write(run_dir / "models/experiment_queue.json", {
            "schema_version": "experiment-request-queue-v2", "status": "EXECUTABLE",
            "ranking_policy": {"issued_by_role": "GLOBAL_SCHEDULER"},
            "requests": [request], "catalog_snapshot": {}, "promotion_review": [],
        })

        ranked = run(str(ROOT / "scripts/rank_experiments.py"), "--run", str(run_dir))
        assert ranked["status"] == "PASS"
        planned = run(
            str(ROOT / "scripts/materialize_experiment.py"), "--run", str(run_dir),
            "--request-id", "req-launch", "--catalog", str(ROOT / "microbench/catalog.json"),
        )
        assert planned["status"] == "PLANNED" and planned["catalog_decision"] == "REUSE"
        experiment_path = run_dir / "experiments/req-launch/experiment.json"
        experiment = json.loads(experiment_path.read_text())
        experiment["status"] = "MATERIALIZED"
        experiment["model_update_contract"]["summary_fields"] = ["median_us"]
        writer = ROOT / "tests/fixtures/write_synthetic_experiment.py"
        experiment["source"]["identities"].append(identity(writer))
        base = [sys.executable, str(writer), "--run", str(run_dir), "--request-id", "req-launch", "--mode"]
        experiment["commands"] = {
            "clean_build": [[*base, "build"]],
            "static_audit": [[*base, "static"]],
            "correctness": [[*base, "correctness"]],
            "warmup": [[*base, "warmup"]],
            "measure": [
                [*base, "measure"],
                [sys.executable, str(ROOT / "scripts/calibrate_p0.py"),
                 "--input", str(run_dir / "experiments/req-launch/raw/p0_input.json"),
                 "--output", str(run_dir / "experiments/req-launch/p0_receipt.json")],
            ],
            "analyze": [[*base, "analyze"]],
        }
        write(experiment_path, experiment)
        rejected = run_failure(str(ROOT / "scripts/dispatch_experiment.py"), "--run", str(run_dir), "--request-id", "req-launch")
        assert rejected["status"] == "FAIL" and any("supervisor approval is missing" in item for item in rejected["errors"])
        over_budget = json.loads(experiment_path.read_text())
        over_budget["execution_budget"]["samples_per_configuration"] = 10
        write(experiment_path, over_budget)
        rejected_budget = run_failure(
            str(ROOT / "scripts/approve_experiment.py"), "--run", str(run_dir), "--request-id", "req-launch",
            "--supervisor-id", "supervisor", "--rationale", "must reject an over-budget package",
        )
        assert rejected_budget["status"] == "REJECTED" and any("max_samples_per_configuration" in item for item in rejected_budget["errors"])
        write(experiment_path, experiment)
        approved = run(
            str(ROOT / "scripts/approve_experiment.py"), "--run", str(run_dir), "--request-id", "req-launch",
            "--supervisor-id", "supervisor", "--rationale", "candidate ordering can flip and the screening budget is bounded",
        )
        assert approved["status"] == "APPROVED"
        stale = json.loads(experiment_path.read_text())
        stale["question"] = "mutated after supervisor review"
        write(experiment_path, stale)
        rejected_stale = run_failure(str(ROOT / "scripts/dispatch_experiment.py"), "--run", str(run_dir), "--request-id", "req-launch")
        assert rejected_stale["status"] == "FAIL" and any("changed after approval" in item for item in rejected_stale["errors"])
        write(experiment_path, experiment)
        dispatched = run(str(ROOT / "scripts/dispatch_experiment.py"), "--run", str(run_dir), "--request-id", "req-launch")
        assert dispatched["status"] == "DISPATCHED"
        executed = run(str(ROOT / "scripts/execute_experiment.py"), "--run", str(run_dir), "--request-id", "req-launch")
        assert executed["status"] == "PASS"
        result_path = run_dir / "experiments/req-launch/result.json"
        bound = run(
            str(ROOT / "scripts/bind_experiment_result.py"), "--run", str(run_dir),
            "--request-id", "req-launch", "--result", str(result_path),
        )
        assert bound["status"] == "BOUND"

        result_identity = identity(result_path)
        model_plan = run_dir / "experiments/req-launch/model_update_plan.json"
        write(model_plan, {
            "schema_version": "model-update-plan-v1", "request_id": "req-launch", "result_identity": result_identity,
            "updates": [
                {
                    "artifact": "resource_balance", "target_pointer": "/cases/0/resource_rows/0/utilization/value_percent",
                    "before": 0.0, "after": 50.0,
                    "calculation": {"op": "COPY_RESULT", "result_pointer": "/summary/utilization_percent"},
                    "units": "percent", "uncertainty": {"kind": "synthetic exact"}, "reason": "bind measured utilization"
                },
                {
                    "artifact": "resource_balance", "target_pointer": "/cases/0/resource_rows/0/unresolved_request_ids",
                    "before": ["req-launch"], "after": [],
                    "calculation": {"op": "COPY_RESULT", "result_pointer": "/summary/resolved_request_ids"},
                    "units": "request ids", "uncertainty": {"kind": "none"}, "reason": "close answered uncertainty"
                },
                {
                    "artifact": "schedule_model", "target_pointer": "/revision", "before": 0, "after": 1.0,
                    "calculation": {"op": "COPY_RESULT", "result_pointer": "/summary/revision"},
                    "units": "revision", "uncertainty": {"kind": "none"}, "reason": "record schedule calibration"
                },
                {
                    "artifact": "tradeoff_frontier", "target_pointer": "/revision", "before": 0, "after": 1.0,
                    "calculation": {"op": "COPY_RESULT", "result_pointer": "/summary/revision"},
                    "units": "revision", "uncertainty": {"kind": "none"}, "reason": "record frontier calibration"
                }
            ]
        })
        applied = run(str(ROOT / "scripts/apply_model_updates.py"), "--run", str(run_dir), "--request-id", "req-launch", "--plan", str(model_plan))
        semantic_receipt = Path(applied["receipt"])
        reconciled = run(
            str(ROOT / "scripts/reconcile_experiment_result.py"), "--run", str(run_dir),
            "--request-id", "req-launch", "--decision", "ACCEPT", "--explanation", "matched launch envelope applied",
            "--model-update-receipt", str(semantic_receipt),
        )
        assert reconciled["status"] == "APPLIED"
        queue = json.loads((run_dir / "models/experiment_queue.json").read_text())
        assert queue["requests"][0]["result_binding"]["model_reconciliation"]["status"] == "APPLIED"
    print("evidence-closed workflow test: PASS")


if __name__ == "__main__":
    main()
