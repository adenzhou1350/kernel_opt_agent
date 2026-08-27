#!/usr/bin/env python3
"""Compute a limit certificate from per-case lower/upper bounds and production evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from evidence_utils import validate_evidence_references


LOWER_KINDS = {
    "silicon_lower": "SILICON_LOWER",
    "resource_service": "RESOURCE_SERVICE_LOWER",
    "dag_lower": "DEPENDENCY_DAG_LOWER",
}


def load(path: Path) -> dict:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain an object")
    return data


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def indexed_cases(data: dict, path: Path) -> dict[str, dict]:
    result = {}
    for case in data.get("cases", []):
        case_id = str(case.get("case_id", ""))
        if not case_id or case_id in result:
            raise ValueError(f"{path}: missing or duplicate case_id")
        result[case_id] = case
    return result


def validate_bound(path: Path, kind: str, run: Path, workload_hash: str, expected_cases: set[str]) -> tuple[dict, dict[str, dict]]:
    data = load(path)
    if data.get("schema_version") != "limit-bound-v1" or data.get("kind") != kind or data.get("status") != "VALID":
        raise ValueError(f"{path}: invalid {kind} bound")
    if data.get("workload_identity", {}).get("sha256") != workload_hash:
        raise ValueError(f"{path}: workload identity mismatch")
    objective = data.get("objective", {})
    if objective.get("direction") != "minimize" or objective.get("unit") != "us":
        raise ValueError(f"{path}: limit bounds require a minimize objective measured in us")
    cases = indexed_cases(data, path)
    if set(cases) != expected_cases:
        raise ValueError(f"{path}: workload case coverage mismatch")
    for case_id, case in cases.items():
        value = float(case["bound_us"])
        confidence = case.get("confidence", {})
        lower = float(confidence["lower_us"])
        upper = float(confidence["upper_us"])
        if not (math.isfinite(value) and 0 <= lower <= value <= upper):
            raise ValueError(f"{path}/{case_id}: invalid bound confidence interval")
        if not case.get("derivation"):
            raise ValueError(f"{path}/{case_id}: derivation is required")
        errors = validate_evidence_references(run, case.get("evidence"), f"{path}/{case_id} evidence")
        if errors:
            raise ValueError("; ".join(errors))
    return data, cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--achieved", type=Path, required=True)
    parser.add_argument("--silicon-bound", type=Path)
    parser.add_argument("--resource-bound", type=Path)
    parser.add_argument("--dag-bound", type=Path)
    parser.add_argument("--schedule-bound", type=Path)
    parser.add_argument("--architecture-explanation", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run = args.run.resolve()
    if run.parent.name != "runs":
        raise ValueError("--run must be a direct child of this repository's runs/")
    if load(run / "run_state.json").get("current_phase") != "CERTIFICATION":
        raise ValueError("run must reach CERTIFICATION before certificate emission")
    project_root = run.parent.parent
    script_dir = Path(__file__).resolve().parent
    harvest = subprocess.run([sys.executable, str(script_dir / "harvest_microbenches.py"), "--root", str(project_root), "--run", str(run), "--promote"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if harvest.returncode:
        raise RuntimeError(harvest.stdout + harvest.stderr)
    purity = subprocess.run([sys.executable, str(script_dir / "audit_repository.py"), "--root", str(project_root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if purity.returncode:
        raise RuntimeError(purity.stdout + purity.stderr)

    canonical = {
        "intake": run / "00_intake.json",
        "operator": run / "operator.json",
        "workload": run / "workload.json",
        "hardware": run / "hardware.json",
        "hardware_evidence": run / "hardware_evidence.json",
        "resource_discovery": run / "models/resource_discovery.json",
        "optimization_plan": run / "models/optimization_plan.json",
        "microarchitecture_model": run / "models/microarchitecture_model.json",
        "mandatory_work": run / "models/work_ledger.json",
        "dag": run / "models/dag.json",
        "instruction_audit": run / "static/instruction_audit.json",
        "microbenchmark_plan": run / "models/microbenchmark_plan.json",
        "schedule_model": run / "models/schedule_model.json",
        "resource_balance": run / "models/resource_balance.json",
        "tradeoff_frontier": run / "models/tradeoff_frontier.json",
        "experiment_queue": run / "models/experiment_queue.json",
        "model_validation": run / "models/model_validation.json",
        "production_validation": run / "models/production_validation.json",
    }
    for path in (*canonical.values(), args.achieved):
        if not path.is_file():
            raise FileNotFoundError(path)
    workload = load(canonical["workload"])
    workload_hash = identity(canonical["workload"])["sha256"]
    weights = {str(case["id"]): float(case.get("weight", 0.0)) for case in workload.get("cases", [])}
    if not weights or sum(weights.values()) <= 0:
        raise ValueError("workload has no positive weighted cases")
    expected_cases = set(weights)
    achieved = load(args.achieved)
    if achieved.get("schema_version") != "achieved-performance-v1" or achieved.get("correctness", {}).get("status") != "PASS":
        raise ValueError("achieved performance must have schema achieved-performance-v1 and correctness PASS")
    if achieved.get("workload_identity", {}).get("sha256") != workload_hash:
        raise ValueError("achieved performance workload identity mismatch")
    achieved_cases = indexed_cases(achieved, args.achieved)
    if set(achieved_cases) != expected_cases:
        raise ValueError("achieved performance workload case coverage mismatch")
    for case_id, case in achieved_cases.items():
        errors = validate_evidence_references(run, case.get("evidence"), f"achieved/{case_id} evidence")
        if errors:
            raise ValueError("; ".join(errors))
        measured = float(case["measured_us"])
        upper = float(case.get("confidence", {})["upper_us"])
        if not (0 < measured <= upper and math.isfinite(upper)):
            raise ValueError(f"achieved/{case_id}: invalid measured upper bound")

    lower_paths = {
        "silicon_lower": args.silicon_bound,
        "resource_service": args.resource_bound,
        "dag_lower": args.dag_bound,
    }
    lower_cases = {}
    bounds = {}
    missing = []
    for name, path in lower_paths.items():
        if path is None:
            missing.append(name)
            bounds[name] = None
            continue
        data, cases = validate_bound(path.resolve(), LOWER_KINDS[name], run, workload_hash, expected_cases)
        bounds[name] = {"identity": identity(path), "data": data}
        lower_cases[name] = cases
    feasible_cases = None
    if args.schedule_bound is not None:
        data, feasible_cases = validate_bound(args.schedule_bound.resolve(), "FEASIBLE_SCHEDULE_UPPER", run, workload_hash, expected_cases)
        bounds["feasible_schedule"] = {"identity": identity(args.schedule_bound), "data": data}
    else:
        bounds["feasible_schedule"] = None
        missing.append("feasible_schedule")

    proof_cases = []
    weighted_lower = weighted_upper = 0.0
    total_weight = sum(weights.values())
    if not missing:
        for case_id in sorted(expected_cases):
            lower_components = {
                name: float(cases[case_id]["confidence"]["lower_us"])
                for name, cases in lower_cases.items()
            }
            lower = max(lower_components.values())
            production_upper = float(achieved_cases[case_id]["confidence"]["upper_us"])
            feasible_upper = float(feasible_cases[case_id]["confidence"]["upper_us"])
            upper = min(production_upper, feasible_upper)
            if upper < lower:
                raise ValueError(f"{case_id}: upper bound is below lower bound; evidence/model is inconsistent")
            gap = upper - lower
            gap_percent = gap / upper * 100.0
            weight = weights[case_id]
            weighted_lower += weight * lower
            weighted_upper += weight * upper
            proof_cases.append({
                "case_id": case_id, "weight": weight,
                "lower_components_us": lower_components, "proven_lower_us": lower,
                "production_upper_us": production_upper, "feasible_upper_us": feasible_upper,
                "proven_upper_us": upper, "gap_us": gap, "gap_percent": gap_percent,
            })
        weighted_lower /= total_weight
        weighted_upper /= total_weight
    weighted_gap = weighted_upper - weighted_lower if not missing else None
    weighted_gap_percent = weighted_gap / weighted_upper * 100.0 if not missing and weighted_upper > 0 else None
    tolerance = float(load(canonical["optimization_plan"]).get("model_error_tolerances_percent", {}).get("achieved_to_feasible_bound", -1))
    proven = not missing and tolerance >= 0 and weighted_gap_percent is not None and weighted_gap_percent <= tolerance

    explanation = load(args.architecture_explanation) if args.architecture_explanation else None
    explanation_valid = bool(
        explanation
        and explanation.get("schema_version") == "architecture-explanation-v1"
        and explanation.get("status") == "VALID"
        and all(explanation.get(field) for field in ("sass_findings", "microarchitecture_findings", "bounded_residuals", "falsification_tests"))
    )
    status = "PROVEN_WITHIN_MODEL" if proven else ("ARCHITECTURALLY_EXPLAINED" if explanation_valid else "INCOMPLETE")
    if not proven and not missing:
        missing.append(f"weighted gap {weighted_gap_percent:.6f}% exceeds frozen tolerance {tolerance:.6f}%")
    certificate = {
        "schema_version": "limit-certificate-v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "identities": {name: identity(path) for name, path in canonical.items()} | {"achieved": identity(args.achieved)},
        "correctness": achieved["correctness"],
        "bounds": bounds,
        "achieved": {"identity": identity(args.achieved), "data": achieved},
        "proof": {
            "objective": {"direction": "minimize", "unit": "us", "aggregation": "normalized workload-weighted mean"},
            "lower_formula": "max(silicon_lower, resource_service_lower, dependency_dag_lower)",
            "upper_formula": "min(production_confidence_upper, feasible_schedule_confidence_upper)",
            "gap_formula": "upper - lower",
            "cases": proof_cases,
            "weighted_lower_us": weighted_lower if not missing or proof_cases else None,
            "weighted_upper_us": weighted_upper if not missing or proof_cases else None,
            "weighted_gap_us": weighted_gap,
            "weighted_gap_percent": weighted_gap_percent,
            "frozen_tolerance_percent": tolerance,
            "status": "PASS" if proven else "FAIL",
        },
        "missing_evidence": missing,
        "claims": ["The achieved upper bound is within the frozen tolerance of the strongest validated model lower bound."] if proven else [],
        "forbidden_claims": ["An absolute undocumented hardware limit has been proven."],
        "architecture_explanation": explanation,
    }
    output = args.output or run / "limit_certificate.json"
    output.write_text(json.dumps(certificate, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "status": status, "weighted_gap_percent": weighted_gap_percent, "missing": missing}, sort_keys=True))
    return 0 if status in {"PROVEN_WITHIN_MODEL", "ARCHITECTURALLY_EXPLAINED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
