#!/usr/bin/env python3
"""Exercise repairable discovery, screening and qualification promotion."""

from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from optimizer_step import discovery_action


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_cli(run: Path, *args: str, expected: int = 0) -> dict:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/kernel_opt.py"), "candidate", *args, "--run", str(run)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.returncode == expected, (completed.stdout, completed.stderr)
    if expected == 0:
        assert completed.stdout.strip(), (args, completed.returncode, completed.stdout, completed.stderr)
    else:
        assert completed.stderr.strip(), (args, completed.returncode, completed.stdout, completed.stderr)
    return json.loads(completed.stdout) if completed.stdout.strip() else {}


def opportunity_cli(run: Path, *args: str, expected: int = 0) -> dict:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/kernel_opt.py"), "opportunity", *args, "--run", str(run)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert completed.returncode == expected, (completed.stdout, completed.stderr)
    return json.loads(completed.stdout) if completed.stdout.strip() else {}


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        run = Path(temporary) / "runs" / "discovery"
        (run / "models").mkdir(parents=True)
        workspace = run / "candidates" / "c1" / "workspace"
        workspace.mkdir(parents=True)
        write(run / "models/baseline.json", {
            "schema_version": "production-baseline-v1",
            "status": "VALID",
            "correctness": {"status": "PASS", "evidence": []},
        })
        write(run / "models/experiment_queue.json", {"requests": []})
        write(workspace / "kernel.py", "VALUE = 1\n")
        kernel_hash = hashlib.sha256((workspace / "kernel.py").read_bytes()).hexdigest()
        write(workspace / "build.py", "from pathlib import Path\nraise SystemExit(0 if Path('ready.flag').exists() else 3)\n")
        write(workspace / "correctness.py", "raise SystemExit(0)\n")
        write(workspace / "smoke.py", """
import json
import hashlib
import os
from pathlib import Path
run = Path(os.environ["KERNEL_OPT_RUN"])
plan_path = run / "models/candidate-execution/c1.json"
plan = json.loads(plan_path.read_text())
plan_hash = hashlib.sha256(plan_path.read_bytes()).hexdigest()
receipt_paths = [Path(value) for value in json.loads(os.environ["KERNEL_OPT_PERSISTENT_RECEIPTS"])]
session_receipts = [
    {
        "path": path.relative_to(run).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    for path in receipt_paths
]
result = {
    "schema_version": "candidate-smoke-result-v6",
    "status": "PASS",
    "candidate_id": "c1",
    "objective": {"direction": "minimize", "baseline": 10.0, "candidate": 8.0, "unit": "us_weighted", "measurement_window": "STEADY_STATE_ONLY"},
    "cases": [{"case_id": "anchor", "role": "ANCHOR"}, {"case_id": "edge", "role": "EDGE"}],
    "correctness": {
        "status": "PASS",
        "contract": "EXACT_IDENTITY",
        "oracle": "fixture output bytes",
        "case_results": [
            {"case_id": case_id, "role": role, "status": "PASS",
             "baseline_digest": hashlib.sha256(case_id.encode()).hexdigest(),
             "candidate_digest": hashlib.sha256(case_id.encode()).hexdigest(),
             "evidence": [{"path": "candidates/c1/workspace/kernel.py",
                           "sha256": hashlib.sha256(Path("kernel.py").read_bytes()).hexdigest()}]}
            for case_id, role in (("anchor", "ANCHOR"), ("edge", "EDGE"))
        ],
    },
    "reachability": {
        "status": "PASS",
        "expected_path": "test-candidate-kernel",
        "observed_path": "test-candidate-kernel",
        "compile_cache_policy": "NOT_COMPILED",
        "execution_proof": {
            "kind": "DIRECT_SENTINEL",
            "scope": "test-candidate-kernel direct smoke invocation",
            "observed_count": 1,
            "minimum_count": 1,
            "evidence_index": 0,
        },
        "evidence": [
            {
                "path": "candidates/c1/workspace/kernel.py",
                "sha256": hashlib.sha256(Path("kernel.py").read_bytes()).hexdigest(),
            },
            {"path": "models/candidate-execution/c1.json", "sha256": plan_hash},
            *session_receipts,
        ],
    },
    "runtime_contract": {
        "production_execution_mode": "EAGER",
        "observed_execution_mode": "EAGER",
        "treatment_materialization": "DIRECT_CALL",
        "compile_cache_key_includes_treatment": False,
        "requires_logical_extent": False,
        "logical_extent_source": "NOT_APPLICABLE",
        "treatment_identity_evidence_index": 0,
    },
    "timing_accounting": {
        "setup_seconds": 0.1,
        "compile_seconds": 0.0,
        "warmup_seconds": 0.1,
        "steady_state_seconds": 0.1,
        "steady_state_samples": 2,
        "objective_window": "STEADY_STATE_ONLY",
        "process_model": plan["selection"]["process_model"],
        "persistent_session_eligible": plan["selection"]["persistent_session_eligible"],
        "switching_preserves_treatment_identity": plan["selection"]["switching_preserves_treatment_identity"],
        "execution_plan_evidence_index": 1,
        "persistent_session_receipt_evidence_indices": [2, 3],
    },
}
Path('../smoke.json').write_text(json.dumps(result))
""".lstrip())
        write(run / "models/phase-timing.json", {
            "schema_version": "candidate-phase-timing-fixture-v1",
            "timing_accounting": {
                "setup_seconds": 9.0,
                "compile_seconds": 0.5,
                "warmup_seconds": 0.5,
                "steady_state_seconds": 0.1,
                "steady_state_samples": 2,
            },
        })
        plan = run_cli(
            run,
            "plan-execution",
            "--candidate-id", "c1",
            "--phase-timing", "models/phase-timing.json",
            "--output", "models/candidate-execution/c1.json",
            "--arm-count", "2",
            "--requests-per-arm", "3",
        )
        assert plan["selection"]["process_model"] == "PERSISTENT_PER_ARM"
        assert plan["selection"]["session_scope"] == "SINGLE_TREATMENT"
        run_cli(
            run,
            "plan-execution",
            "--candidate-id", "c1",
            "--phase-timing", "models/phase-timing.json",
            "--output", "models/candidate-execution/c1.json",
            expected=1,
        )
        write(run / "models/low-fixed-phase-timing.json", {
            "setup_seconds": 0.01,
            "compile_seconds": 0.0,
            "warmup_seconds": 0.0,
            "steady_state_seconds": 1.0,
            "steady_state_samples": 1,
        })
        cold_plan = run_cli(
            run,
            "plan-execution",
            "--candidate-id", "low-fixed",
            "--phase-timing", "models/low-fixed-phase-timing.json",
            "--output", "models/candidate-execution/low-fixed.json",
            "--arm-count", "2",
            "--requests-per-arm", "3",
        )
        assert cold_plan["selection"]["process_model"] == "COLD_PER_ARM"

        write(run / "models/shared-switch.stdout.ndjson", "ready\nresult-a\nresult-b\n")
        write(run / "models/shared-switch.stderr.txt", "")
        shared_stdout = run / "models/shared-switch.stdout.ndjson"
        shared_stderr = run / "models/shared-switch.stderr.txt"
        treatment_a = hashlib.sha256(b"a").hexdigest()
        treatment_b = hashlib.sha256(b"b").hexdigest()
        shared_receipt_path = run / "models/shared-switch-receipt.json"
        shared_receipt = {
            "schema_version": "persistent-session-receipt-v1",
            "status": "PASS",
            "failure": None,
            "session_scope": "SHARED_TREATMENTS",
            "switching_supported": True,
            "process_launches": 1,
            "engine_init_count": 1,
            "session_identity": hashlib.sha256(b"shared-worker").hexdigest(),
            "request_count": 2,
            "requests": [
                {
                    "treatment_identity": treatment_a,
                    "output_digest": hashlib.sha256(b"output-a").hexdigest(),
                },
                {
                    "treatment_identity": treatment_b,
                    "output_digest": hashlib.sha256(b"output-b").hexdigest(),
                },
            ],
            "stdout": {
                "path": "models/shared-switch.stdout.ndjson",
                "sha256": hashlib.sha256(shared_stdout.read_bytes()).hexdigest(),
            },
            "stderr": {
                "path": "models/shared-switch.stderr.txt",
                "sha256": hashlib.sha256(shared_stderr.read_bytes()).hexdigest(),
            },
        }
        write(shared_receipt_path, shared_receipt)
        shared_plan = run_cli(
            run,
            "plan-execution",
            "--candidate-id", "shared-safe",
            "--phase-timing", "models/phase-timing.json",
            "--output", "models/candidate-execution/shared-safe.json",
            "--arm-count", "2",
            "--requests-per-arm", "3",
            "--shared-switching-receipt", "models/shared-switch-receipt.json",
        )
        assert shared_plan["selection"]["process_model"] == "PERSISTENT_SHARED_ENGINE"
        assert shared_plan["estimates"]["selected_session_count"] == 1
        shared_receipt["switching_supported"] = False
        write(run / "models/unsafe-switch-receipt.json", shared_receipt)
        run_cli(
            run,
            "plan-execution",
            "--candidate-id", "shared-unsafe",
            "--phase-timing", "models/phase-timing.json",
            "--output", "models/candidate-execution/shared-unsafe.json",
            "--shared-switching-receipt", "models/unsafe-switch-receipt.json",
            expected=1,
        )
        execution_plan_path = run / "models/candidate-execution/c1.json"
        execution_plan_hash = hashlib.sha256(execution_plan_path.read_bytes()).hexdigest()
        persistent_worker = ROOT / "tests/fixtures/persistent_worker.py"
        session_identity = hashlib.sha256(persistent_worker.read_bytes()).hexdigest()
        persistent_session_specs = []
        for label in ("baseline", "candidate"):
            treatment_identity = hashlib.sha256(label.encode()).hexdigest()
            session_spec_path = (
                run / "candidates" / "c1" / "sessions" / f"{label}.json"
            )
            write(session_spec_path, {
                "schema_version": "persistent-session-spec-v1",
                "argv": [
                    sys.executable,
                    str(persistent_worker),
                    "--session-identity",
                    session_identity,
                ],
                "cwd": ".",
                "session_scope": "SINGLE_TREATMENT",
                "expected_session_identity": session_identity,
                "startup_timeout_seconds": 5.0,
                "request_timeout_seconds": 5.0,
                "shutdown_timeout_seconds": 2.0,
                "requests": [
                    {
                        "request_id": f"{label}-{index}",
                        "treatment_identity": treatment_identity,
                        "payload": {"value": index},
                    }
                    for index in range(3)
                ],
            })
            persistent_session_specs.append({
                "path": session_spec_path.relative_to(run).as_posix(),
                "sha256": hashlib.sha256(session_spec_path.read_bytes()).hexdigest(),
            })
        spec_path = run / "candidates" / "c1" / "spec.json"
        candidate_spec = {
            "candidate_id": "c1",
            "opportunity_id": "fuse-transfer",
            "name": "repairable candidate",
            "family": "layout-redesign",
            "change_axes": ["layout", "warp-ownership"],
            "hypothesis": "remove a materialized transfer",
            "expected_global_effect": "reduce weighted production latency",
            "predicted_global_gain_us": {"lower": 1.0, "upper": 3.0},
            "dependency_contract": {
                "status": "PROVEN_LEGAL",
                "preserved_dependencies": ["the output still depends on the same input values"],
                "changed_boundaries": ["the candidate changes only the implementation boundary"],
                "prohibited_rewrites": ["cached or constant outputs are forbidden"],
                "numerical_ordering": "The fixture preserves its scalar operation order.",
                "evidence": [{
                    "path": "candidates/c1/workspace/kernel.py",
                    "sha256": kernel_hash,
                    "claim": "candidate implementation used by the dependency audit",
                }],
            },
            "source_paths": ["candidates/c1/workspace/kernel.py"],
            "commands": {
                "build": {"argv": ["{python}", "build.py"], "cwd": "candidates/c1/workspace", "timeout_seconds": 30},
                "correctness": {"argv": ["{python}", "correctness.py"], "cwd": "candidates/c1/workspace", "timeout_seconds": 30},
                "smoke": {"argv": ["{python}", "smoke.py"], "cwd": "candidates/c1/workspace", "timeout_seconds": 30}
            },
            "smoke_result_path": "candidates/c1/smoke.json",
            "execution_plan": {
                "path": "models/candidate-execution/c1.json",
                "sha256": execution_plan_hash,
            },
            "persistent_session_specs": persistent_session_specs,
            "development_budget": {"max_technical_attempts": 3}
        }
        forged_plan = json.loads(json.dumps(plan))
        forged_plan["selection"]["process_model"] = "PERSISTENT_SHARED_ENGINE"
        forged_plan["selection"]["session_scope"] = "SHARED_TREATMENTS"
        forged_plan_path = run / "models/candidate-execution/forged.json"
        write(forged_plan_path, forged_plan)
        forged_spec = dict(candidate_spec)
        forged_spec["execution_plan"] = {
            "path": "models/candidate-execution/forged.json",
            "sha256": hashlib.sha256(forged_plan_path.read_bytes()).hexdigest(),
        }
        forged_spec_path = run / "candidates" / "c1" / "forged-plan-spec.json"
        write(forged_spec_path, forged_spec)
        missing_dependency = dict(candidate_spec)
        missing_dependency.pop("dependency_contract")
        missing_dependency_path = run / "candidates" / "c1" / "missing-dependency.json"
        write(missing_dependency_path, missing_dependency)
        missing_plan = dict(candidate_spec)
        missing_plan.pop("execution_plan")
        missing_plan_path = run / "candidates" / "c1" / "missing-plan.json"
        write(missing_plan_path, missing_plan)
        missing_sessions = dict(candidate_spec)
        missing_sessions.pop("persistent_session_specs")
        missing_sessions_path = run / "candidates" / "c1" / "missing-sessions.json"
        write(missing_sessions_path, missing_sessions)
        write(spec_path, candidate_spec)
        run_cli(
            run, "init", "--min-candidates", "1", "--max-candidates", "2",
            "--min-families", "1", "--max-technical-attempts", "3",
            "--max-candidate-wall-clock-minutes", "5", "--max-total-wall-clock-minutes", "10",
            "--promotion-threshold-percent", "1.0",
        )
        opportunity_cli(
            run, "init", "--min-opportunities", "1", "--max-opportunities", "2",
            "--min-rewrite-families", "1", "--min-candidate-opportunities", "1",
        )
        opportunity_spec = run / "models" / "opportunity-spec.json"
        baseline_hash = hashlib.sha256((run / "models/baseline.json").read_bytes()).hexdigest()
        write(opportunity_spec, {
            "opportunity_id": "fuse-transfer",
            "name": "fuse materialized transfer",
            "model_scope": "DECOMPOSITION_CONDITIONAL",
            "source_model_term": "raw_o write plus read",
            "affected_stages": ["S3", "post"],
            "current_contribution_us": 4.0,
            "optimistic_gain_ceiling_us": 3.0,
            "likely_gain_interval_us": {"lower": 1.0, "upper": 2.5},
            "confidence": "HIGH",
            "rewrite_families": ["layout-redesign", "persistent-grid"],
            "implementation_budget_minutes": 10,
            "hypothesis": "fusion removes a materialized global-memory boundary",
            "derivation": "stage timing minus the mandatory semantic output store",
            "evidence": [{"path": "models/baseline.json", "sha256": baseline_hash, "claim": "current objective contribution"}],
            "production_impact_gate": {
                "measurement_scope": "FROZEN_WORKLOAD_DECOMPOSITION",
                "baseline_end_to_end_us": 8.0,
                "target_component_us": 4.0,
                "candidate_component_speedup_ceiling": 4.0,
                "derived_amdahl_speedup_ceiling": 1.6,
                "material_speedup_floor": 1.01,
                "decision": "CLEARS_MATERIALITY_FLOOR",
                "derivation": "The frozen baseline assigns half of end-to-end time to this transfer.",
                "evidence": [{"path": "models/baseline.json", "sha256": baseline_hash, "claim": "representative end-to-end decomposition"}],
            },
        })
        opportunity_cli(run, "add", "--spec", str(opportunity_spec))
        opportunity_cli(run, "rank")
        run_cli(run, "add", "--spec", str(missing_dependency_path), expected=1)
        run_cli(run, "add", "--spec", str(missing_plan_path), expected=1)
        run_cli(run, "add", "--spec", str(missing_sessions_path), expected=1)
        run_cli(run, "add", "--spec", str(forged_spec_path), expected=1)
        run_cli(run, "add", "--spec", str(spec_path))

        # Candidate execution must fail closed if ranked evidence is edited
        # after registration. Reranking repairs the derived score and digest.
        opportunity_map_path = run / "models/opportunity_map.json"
        opportunity_map = json.loads(opportunity_map_path.read_text(encoding="utf-8"))
        opportunity_map["opportunities"][0]["priority_score"] = 999.0
        write(opportunity_map_path, opportunity_map)
        run_cli(run, "run", "--candidate-id", "c1", expected=1)
        pool = json.loads((run / "models/candidate_pool.json").read_text(encoding="utf-8"))
        assert pool["candidates"][0]["attempts"] == []
        opportunity_cli(run, "rank")

        failed = run_cli(run, "run", "--candidate-id", "c1")
        assert failed.get("status") == "DEVELOPING", failed
        pool = json.loads((run / "models/candidate_pool.json").read_text(encoding="utf-8"))
        item = pool["candidates"][0]
        assert item["attempts"][0]["status"] == "TECHNICAL_FAILURE"
        assert item["status"] != "REJECTED"
        repair = discovery_action(run, ROOT / "scripts")
        assert repair and repair["action"] == "REPAIR_DISCOVERY_CANDIDATE"

        write(workspace / "ready.flag", "ready\n")
        screened = run_cli(run, "run", "--candidate-id", "c1")
        assert screened["status"] == "QUALIFICATION_READY"
        assert abs(screened["improvement_percent"] - 20.0) < 1e-9
        pool = json.loads((run / "models/candidate_pool.json").read_text(encoding="utf-8"))
        successful_attempt = pool["candidates"][0]["attempts"][1]
        assert [stage["stage"] for stage in successful_attempt["stages"]] == [
            "build",
            "correctness",
            "persistent-session-01",
            "persistent-session-02",
            "smoke",
        ]
        for index in (1, 2):
            receipt = (
                run
                / "candidates/c1/attempts/attempt-02"
                / f"persistent-session-{index:02d}.json"
            )
            assert json.loads(receipt.read_text())["engine_init_count"] == 1
        opportunity_map = json.loads((run / "models/opportunity_map.json").read_text(encoding="utf-8"))
        observation = opportunity_map["opportunities"][0]["observations"][0]
        assert observation["observed_global_gain_us"] == 2.0
        assert observation["residual_us"] == 0.0
        pool = json.loads((run / "models/candidate_pool.json").read_text(encoding="utf-8"))
        pool["candidates"].append({
            "candidate_id": "c2",
            "opportunity_id": "fuse-transfer",
            "family": "persistent-grid",
            "status": "QUALIFICATION_READY",
            "screening": {"improvement_percent": 30.0},
        })
        write(run / "models/candidate_pool.json", pool)
        strongest = discovery_action(run, ROOT / "scripts")
        assert strongest and strongest["action"] == "PROMOTE_DISCOVERY_CANDIDATE"
        assert strongest["commands"][0][-1] == "c2"
        pool["candidates"].pop()
        write(run / "models/candidate_pool.json", pool)

        # Direct promotion is also evidence-gated, even if the candidate was
        # screened while the opportunity map was valid.
        opportunity_map = json.loads(opportunity_map_path.read_text(encoding="utf-8"))
        opportunity_map["opportunities"][0]["priority_score"] = 999.0
        write(opportunity_map_path, opportunity_map)
        run_cli(run, "promote", "--candidate-id", "c1", expected=1)
        opportunity_cli(run, "rank")

        promoted = run_cli(run, "promote", "--candidate-id", "c1")
        assert promoted["status"] == "PROMOTED_TO_QUALIFICATION"
        qualification = discovery_action(run, ROOT / "scripts")
        assert qualification and qualification["action"] == "BUILD_QUALIFICATION_CONTRACT"
        promotion_path = run / promoted["promotion"]["path"]
        promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
        assert "production acceptance" in promotion["claims_forbidden"]
        pool = json.loads((run / "models/candidate_pool.json").read_text(encoding="utf-8"))
        pool["status"] = "PAUSED"
        write(run / "models/candidate_pool.json", pool)
        paused = discovery_action(run, ROOT / "scripts")
        assert paused and paused["action"] == "DISCOVERY_BUDGET_REVIEW"
    print("candidate discovery loop test: PASS")


if __name__ == "__main__":
    main()
