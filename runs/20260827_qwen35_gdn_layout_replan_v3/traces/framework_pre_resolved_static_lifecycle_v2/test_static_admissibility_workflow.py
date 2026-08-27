#!/usr/bin/env python3
"""Dependency-free tests for the static-admissibility control plane."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from advance_run import validate_experiment_queue
from schema_utils import validate_json_file
from supervision_utils import validate_admissibility_budget, validate_admissibility_contract


def write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ident(path: Path) -> dict:
    return {"path": str(path), "sha256": digest(path)}


def contract(run: Path, candidate: Path, evidence: Path) -> dict:
    return {
        "schema_version": "candidate-admissibility-contract-v1",
        "lifecycle": "PASS_REJECT_INVALID",
        "subdecision_id": "fixture-static",
        "status": "READY_FOR_SUPERVISOR",
        "issued_by": {"role": "GLOBAL_SCHEDULER", "owner_id": "scheduler"},
        "analysis_owner": {"role": "MICROARCHITECTURE_ANALYST", "analyst_id": "analyst"},
        "run_id": run.name,
        "phase": "MODELING",
        "candidate_binding": {"candidate_id": "N2", "artifact_identity": ident(candidate)},
        "predicate": {
            "quantity_id": "layout_view_feasible", "unit": "binary_pass",
            "domain": {"lower": 0, "upper": 1},
            "equation": "x=1 iff G1..G6 pass", "pass_condition": "x == 1",
            "fail_condition": "x == 0", "statistical_precision": "NOT_APPLICABLE_DETERMINISTIC",
        },
        "gates": [
            {"gate_id": gate, "requirement": "fixture exact requirement"}
            for gate in (
                "G1_EXACT_PATH_IDENTITY", "G2_SAME_ITERATOR", "G3_BIJECTIVE_MAPPING",
                "G4_SCOREV_FRAGMENT_COMPATIBILITY", "G5_NEGATIVE_CONTROL", "G6_ZERO_DYNAMIC_EXECUTION",
            )
        ],
        "explicit_non_claims": [
            "no latency", "no speedup", "no performance Top2", "no numerical correctness", "no K-loop proof",
        ],
        "observations": {
            "short": {"count": 1, "unit": "binary_pass"},
            "long": {"count": 1, "unit": "binary_pass"},
            "aggregate": "logical_and(short,long)", "duplicated_samples_forbidden": True,
        },
        "host_budget": {
            "max_configurations": 2, "max_samples_per_configuration": 1,
            "max_process_launches": 6, "max_wall_clock_minutes": 5, "max_revisions": 1,
        },
        "device_budget": {"cuda_kernel_launches": 0, "gpu_performance_samples": 0},
        "outcomes": [
            {"condition": "pass", "outcome": "ADMIT_PENDING_IMPLEMENTATION"},
            {"condition": "predicate false", "outcome": "REJECT_STATIC_LAYOUT"},
            {"condition": "tool failure", "outcome": "INVALID_BLOCK_NO_DISPOSITION"},
        ],
        "allowed_model_updates": ["admissibility status"],
        "forbidden_model_updates": ["latency interval", "Top2", "production source"],
        "evidence": [ident(evidence)],
    }


def benchmark_fixture(timer: str, unit: str, samples: list[float]) -> dict:
    return {
        "schema_version": "benchmark-result-v2", "request_id": "r",
        "experiment_identity": {}, "hardware_identity": {}, "workload_identity": {},
        "benchmark": "b", "question": "q", "environment": {}, "source_identity": {},
        "measurement": {"metric": "m", "semantics": "s", "unit": unit, "timer": timer},
        "raw_samples": samples, "raw_samples_identity": {},
        "correctness": {"status": "PASS", "checks": ["c"], "evidence_identity": {}},
        "static_evidence": {}, "runtime_evidence": {}, "measurement_system": {"p0_receipt": {}},
        "validity": {"status": "VALID", "dce_guard": "g", "known_pollution": [], "claims_allowed": [], "claims_forbidden": []},
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        run = Path(temporary) / "runs/static-fixture"
        candidate = run / "models/architecture_candidates/n2.json"
        evidence = run / "traces/review.json"
        write(candidate, {"candidate_id": "N2"})
        write(evidence, {"review": "PASS"})
        write(run / "models/optimization_plan.json", {
            "screening_budget": {
                "max_configurations": 3, "max_samples_per_configuration": 1,
                "max_process_launches": 6, "max_wall_clock_minutes": 15,
            }
        })
        contract_path = run / "models/admissibility_contracts/n2.json"
        write(contract_path, contract(run, candidate, evidence))
        assert validate_admissibility_contract(contract_path, run) == []
        pass_only = contract(run, candidate, evidence)
        pass_only["lifecycle"] = "PASS_ONLY_INVALID"
        pass_only["outcomes"] = [
            {"condition": "all gates pass", "outcome": "ADMIT_PENDING_IMPLEMENTATION"},
            {"condition": "any failure", "outcome": "INVALID_BLOCK_NO_DISPOSITION"},
        ]
        pass_only_path = run / "models/admissibility_contracts/n2_pass_only.json"
        write(pass_only_path, pass_only)
        assert validate_admissibility_contract(pass_only_path, run) == []

        request = {
            "request_id": "req-static", "status": "PROPOSED", "issued_by_role": "GLOBAL_SCHEDULER",
            "workload_cases": ["s"], "model_field": "N2.admissibility",
            "candidate_decision": "admit or reject static layout", "causal_question": "is the view feasible?",
            "experiment_kind": "STATIC_ADMISSIBILITY", "admissibility_contract": ident(contract_path),
            "experiment_class": "SCREENING", "tested_candidate_ids": ["N2"],
            "implementation_owner": {"role": "EXPERIMENT_AGENT", "actor_id": "experimenter"},
            "resource_ids": ["register_storage"], "affected_stage_ids": ["s3"], "priority": 0,
            "controls": ["zero GPU", "positive control", "negative control", "live output"],
            "measurement_contract": {
                "timer": "none_compiler_typecheck", "unit": "binary_pass",
                "gpu_launches": 0, "performance_samples": 0,
            },
            "expected_sass": ["static marker only"],
            "catalog_resolution": {
                "catalog_queried": False, "query": {"resources": ["register_storage"]},
                "decision": "PENDING", "package_id": None, "reason": "pending query",
            },
            "result_binding": {"status": "PENDING"},
            "promotion_disposition": {"status": "PENDING"},
        }
        queue = {
            "schema_version": "experiment-request-queue-v3", "status": "ACTIVE",
            "ranking_policy": {"formula": "NO_PERFORMANCE_RANKING_SINGLE_STATIC_GATE"},
            "requests": [request], "catalog_snapshot": {"status": "PENDING_QUERY"}, "promotion_review": [],
        }
        workload = {"cases": [{"id": "s"}]}
        write(run / "workload.json", workload)
        errors: list[str] = []
        validate_experiment_queue(queue, workload, errors)
        assert errors == [], errors
        queue_path = run / "models/experiment_queue.json"
        write(queue_path, queue)
        completed = subprocess.run([
            sys.executable, str(ROOT / "scripts/rank_experiments.py"), "--run", str(run),
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert completed.returncode == 0, (completed.stdout, completed.stderr)
        ranked = json.loads(queue_path.read_text())
        assert ranked["ranking_policy"]["formula"] == "NO_PERFORMANCE_RANKING_SINGLE_STATIC_GATE"
        assert "sensitivity" not in ranked["requests"][0]

        experiment = {
            "experiment_kind": "STATIC_ADMISSIBILITY", "experiment_class": "SCREENING",
            "tested_candidate_ids": ["N2"],
            "parameter_matrix": [{"production_path": "short"}, {"production_path": "long"}],
            "commands": {phase: [["python", phase]] for phase in ("clean_build", "static_audit", "correctness", "warmup", "measure", "analyze")},
            "execution_budget": {"samples_per_configuration": 1, "process_launches": 6, "max_wall_clock_minutes": 5},
        }
        assert validate_admissibility_budget(experiment, json.loads(contract_path.read_text()), run) == []

        static_result = run / "static_result.json"
        timed_result = run / "timed_result.json"
        write(static_result, benchmark_fixture("none_compiler_typecheck", "binary_pass", [1.0]))
        write(timed_result, benchmark_fixture("cuda_event", "us", [1.0]))
        schema = ROOT / "schemas/benchmark_result.schema.json"
        assert validate_json_file(static_result, schema) == []
        assert validate_json_file(timed_result, schema), "timed performance result incorrectly accepted fewer than nine samples"

    print("static-admissibility workflow test: PASS")


if __name__ == "__main__":
    main()
