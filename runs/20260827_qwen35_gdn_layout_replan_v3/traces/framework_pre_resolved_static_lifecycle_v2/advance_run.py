#!/usr/bin/env python3
"""Validate and advance one optimization run through non-skippable phases."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from evidence_utils import (
    resolve_evidence_path,
    sha256 as evidence_sha256,
    validate_evidence_references,
    validate_hardware_evidence,
    validate_identity,
    validate_p0_receipt,
)
from experiment_utils import (
    validate_benchmark_result,
    validate_catalog_receipt,
    validate_execution_receipt,
    validate_materialized_experiment,
)
from supervision_utils import (
    artifact_path,
    validate_admissibility_contract,
    validate_decision_contract,
    validate_measurability_contract,
    validate_supervisor_approval,
)
from discover_resources import CLASS_RULES, observed_classes
from count_sass import validate_disassembly_receipt
from schema_utils import validate_json_file


PHASES = (
    "PLANNING",
    "BASELINE",
    "MODELING",
    "EXPERIMENT",
    "PRODUCTION_VALIDATION",
    "CERTIFICATION",
    "COMPLETE",
)

NEXT_ACTIONS = {
    "PLANNING": "Complete an executable plan with workload priorities, P0-P4 requirements, evidence gates, model-error tolerances and stop criteria.",
    "BASELINE": "Capture correct production-exact CPU dispatch, GPU-active and end-to-end baselines for every weighted workload case.",
    "MODELING": "Populate mandatory work, mathematical/current DAGs, the target resource graph, initial SASS schedule and executable microbenchmark plan.",
    "EXPERIMENT": "Calibrate P0-P3, validate cross-layer component predictions, and accept only correct candidates whose final SASS matches the hypothesis.",
    "PRODUCTION_VALIDATION": "Run P4 production-exact correctness, timing and end-to-end validation for every weighted workload case.",
    "CERTIFICATION": "Harvest reusable probes, audit repository purity, and emit a proven or architecture-explained limit certificate.",
    "COMPLETE": "Run is complete; start a new run for a changed computation, workload or hardware identity.",
}


# ---------------------------------------------------------------------------
# Shared artifact and numeric validation primitives
# ---------------------------------------------------------------------------


def read_object(path: Path, errors: list[str]) -> dict:
    if not path.exists():
        errors.append(f"missing artifact: {path}")
        return {}
    try:
        data = json.loads(path.read_text())
    except Exception as error:
        errors.append(f"invalid JSON {path}: {error}")
        return {}
    if not isinstance(data, dict):
        errors.append(f"artifact must be a JSON object: {path}")
        return {}
    return data


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def present(value) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def finite_number(value, *, minimum: float | None = None, maximum: float | None = None) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and (minimum is None or number >= minimum) and (maximum is None or number <= maximum)


def validate_quantity(record: dict, label: str, errors: list[str], *, positive: bool = False) -> None:
    require(isinstance(record, dict), f"{label}: quantity must be an object", errors)
    if not isinstance(record, dict):
        return
    require(finite_number(record.get("value"), minimum=(1e-300 if positive else 0.0)), f"{label}: value must be finite and {'positive' if positive else 'non-negative'}", errors)
    require(present(record.get("unit")), f"{label}: unit is required", errors)


def validate_schema_artifacts(run: Path, pairs: tuple[tuple[str, str], ...], errors: list[str]) -> None:
    schema_root = Path(__file__).resolve().parents[1] / "schemas"
    for relative, schema_name in pairs:
        instance = run / relative
        schema = schema_root / schema_name
        if not instance.is_file() or not schema.is_file():
            errors.append(f"schema gate: missing {instance if not instance.is_file() else schema}")
            continue
        try:
            errors.extend(f"schema gate {relative}: {item}" for item in validate_json_file(instance, schema))
        except Exception as error:
            errors.append(f"schema gate {relative}: {error}")


def case_ids(workload: dict) -> set[str]:
    return {str(case.get("id")) for case in workload.get("cases", []) if case.get("id")}


def evidence_closed_contract(run: Path) -> bool:
    try:
        state = json.loads((run / "run_state.json").read_text())
    except Exception:
        return False
    return state.get("framework_contract_version") == "evidence-closed-v2"


def validate_framework_contract(run: Path, state: dict, errors: list[str]) -> None:
    hardware = read_object(run / "hardware.json", errors)
    synthetic_legacy = (
        state.get("schema_version") == "optimization-run-state-v2"
        and str(hardware.get("target", {}).get("vendor", "")).upper() == "TEST"
    )
    if not synthetic_legacy:
        require(state.get("schema_version") == "optimization-run-state-v4", "run state: production runs require optimization-run-state-v4", errors)
        require(state.get("framework_contract_version") == "evidence-closed-v2", "run state: missing/unknown framework contract is a hard failure; legacy fallback is forbidden", errors)
        validate_schema_artifacts(run, (("run_state.json", "run_state.schema.json"),), errors)


def resource_node_ids(architecture: dict) -> set[str]:
    result = set()
    for node in architecture.get("resource_nodes", []):
        if isinstance(node, str):
            result.add(node)
        elif isinstance(node, dict):
            value = node.get("resource_id") or node.get("id")
            if value:
                result.add(str(value))
    return result


def indexed_cases(data: dict, artifact: str, errors: list[str]) -> dict[str, dict]:
    cases = data.get("cases", [])
    require(isinstance(cases, list) and cases, f"{artifact}: cases must not be empty", errors)
    indexed: dict[str, dict] = {}
    if isinstance(cases, list):
        for case in cases:
            if not isinstance(case, dict) or not case.get("case_id"):
                errors.append(f"{artifact}: every case requires case_id")
                continue
            key = str(case["case_id"])
            if key in indexed:
                errors.append(f"{artifact}: duplicate case_id {key}")
            indexed[key] = case
    return indexed


def require_coverage(indexed: dict[str, dict], expected: set[str], artifact: str, errors: list[str]) -> None:
    missing = sorted(expected - set(indexed))
    extra = sorted(set(indexed) - expected)
    require(not missing, f"{artifact}: missing workload cases {missing}", errors)
    require(not extra, f"{artifact}: unknown workload cases {extra}", errors)


def validate_prediction(record: dict, label: str, errors: list[str], run: Path | None = None) -> None:
    for field in ("predicted_us", "measured_us", "threshold_percent", "status", "evidence"):
        require(present(record.get(field)), f"{label}: missing {field}", errors)
    try:
        predicted = float(record["predicted_us"])
        measured = float(record["measured_us"])
        threshold = float(record["threshold_percent"])
        require(predicted >= 0 and measured > 0 and threshold >= 0, f"{label}: invalid numeric prediction fields", errors)
        computed = abs(predicted - measured) / measured * 100.0
        if "error_percent" in record:
            require(
                math.isclose(float(record["error_percent"]), computed, rel_tol=1e-3, abs_tol=1e-3),
                f"{label}: recorded error_percent does not match predicted/measured values",
                errors,
            )
        require(computed <= threshold, f"{label}: model error {computed:.4f}% exceeds threshold {threshold:.4f}%", errors)
        require(record.get("status") == "PASS", f"{label}: status must be PASS when used as a gate", errors)
    except (KeyError, TypeError, ValueError):
        errors.append(f"{label}: prediction fields must be numeric")
    if run is not None and evidence_closed_contract(run):
        errors.extend(validate_evidence_references(run, record.get("evidence"), f"{label} evidence"))


GLOBAL_AUTHORITIES = {
    "RANK_EXPERIMENTS",
    "CLOSE_RESOURCE_MODEL",
    "ACCEPT_GLOBAL_CANDIDATE",
    "AUTHORIZE_LIMIT_REPORT",
}

GLOBAL_SUPERVISOR_AUTHORITIES = {
    "VETO_EXPERIMENT",
    "APPROVE_EXPERIMENT_DISPATCH",
    "ENFORCE_BUDGET",
    "HALT_AND_REPLAN",
}

RESOURCE_STATES = {"MEASURED", "BOUNDED", "UNKNOWN", "NOT_APPLICABLE"}

NON_SATURATION_CAUSES = {
    "DEVICE_COVERAGE",
    "PAYLOAD_TOO_SMALL",
    "INSUFFICIENT_ILP",
    "RESIDENCY_LIMIT",
    "REQUEST_AMPLIFICATION",
    "TRANSACTION_INEFFICIENCY",
    "CACHE_BOUNDARY_MISMATCH",
    "SYNC_TRUNCATION",
    "TAIL_IMBALANCE",
    "RESOURCE_CONTENTION",
    "NOT_ESTABLISHED",
}


# ---------------------------------------------------------------------------
# Global-scheduler artifacts and cross-artifact coverage
# ---------------------------------------------------------------------------


def global_artifacts(run: Path, workload: dict, errors: list[str]) -> tuple[dict, dict, dict, dict]:
    state = read_object(run / "models/global_schedule_state.json", errors)
    balance = read_object(run / "models/resource_balance.json", errors)
    frontier = read_object(run / "models/tradeoff_frontier.json", errors)
    queue = read_object(run / "models/experiment_queue.json", errors)
    owner = state.get("owner", {})
    require(owner.get("role") == "GLOBAL_SCHEDULER", "global scheduler: owner.role must be GLOBAL_SCHEDULER", errors)
    require(present(owner.get("owner_id")), "global scheduler: owner.owner_id is required", errors)
    authorities = set(owner.get("exclusive_authority", []))
    require(GLOBAL_AUTHORITIES <= authorities, "global scheduler: exclusive decision authorities are incomplete", errors)
    if state.get("schema_version") == "global-schedule-state-v2":
        supervisor = state.get("supervisor", {})
        require(supervisor.get("role") == "GLOBAL_SUPERVISOR", "global supervisor: role must be GLOBAL_SUPERVISOR", errors)
        require(present(supervisor.get("owner_id")), "global supervisor: owner_id is required", errors)
        require(supervisor.get("owner_id") != owner.get("owner_id"), "global supervisor: must be independent from the global scheduler", errors)
        require(GLOBAL_SUPERVISOR_AUTHORITIES <= set(supervisor.get("exclusive_authority", [])), "global supervisor: veto, approval, budget and replan authorities are incomplete", errors)
    material = state.get("material_resources", [])
    require(isinstance(material, list) and bool(material), "global scheduler: material_resources must not be empty", errors)
    require(len(material) == len(set(material)), "global scheduler: material_resources must be unique", errors)
    owned = state.get("owned_artifacts", {})
    expected_paths = {
        "resource_balance": "models/resource_balance.json",
        "tradeoff_frontier": "models/tradeoff_frontier.json",
        "experiment_queue": "models/experiment_queue.json",
        "schedule_model": "models/schedule_model.json",
    }
    require(owned == expected_paths, "global scheduler: owned_artifacts must name the canonical model paths", errors)
    validate_experiment_queue(queue, workload, errors)
    for request in queue.get("requests", []):
        requested_resources = {str(item) for item in request.get("resource_ids", [])}
        require(requested_resources <= set(material), f"experiment request {request.get('request_id')}: resource outside global material set", errors)
    validate_resource_balance(balance, workload, set(material), queue, errors)
    validate_tradeoff_frontier(frontier, workload, errors)
    return state, balance, frontier, queue


def validate_experiment_queue(queue: dict, workload: dict, errors: list[str]) -> None:
    version = queue.get("schema_version")
    require(version in {"experiment-request-queue-v1", "experiment-request-queue-v2", "experiment-request-queue-v3"}, "experiment queue: invalid schema_version", errors)
    require(present(queue.get("ranking_policy")), "experiment queue: ranking_policy is required", errors)
    require(present(queue.get("catalog_snapshot")), "experiment queue: catalog_snapshot is required", errors)
    requests = queue.get("requests", [])
    require(isinstance(requests, list) and bool(requests), "experiment queue: requests must not be empty", errors)
    seen: set[str] = set()
    valid_cases = case_ids(workload)
    for index, request in enumerate(requests if isinstance(requests, list) else []):
        label = f"experiment request {index}"
        request_id = request.get("request_id")
        require(present(request_id), f"{label}: request_id is required", errors)
        if present(request_id):
            require(str(request_id) not in seen, f"{label}: duplicate request_id {request_id}", errors)
            seen.add(str(request_id))
        require(request.get("issued_by_role") == "GLOBAL_SCHEDULER", f"{label}: must be issued by GLOBAL_SCHEDULER", errors)
        for field in ("model_field", "candidate_decision", "causal_question", "resource_ids", "affected_stage_ids", "controls", "measurement_contract", "expected_sass"):
            require(present(request.get(field)), f"{label}: missing {field}", errors)
        if version == "experiment-request-queue-v2":
            for field in ("decision_contract", "measurability_contract", "experiment_class", "tested_candidate_ids", "implementation_owner"):
                require(present(request.get(field)), f"{label}: missing candidate-supervision field {field}", errors)
            require(request.get("experiment_class") in {"SCREENING", "QUALIFICATION"}, f"{label}: invalid experiment_class", errors)
            owner = request.get("implementation_owner", {})
            require(owner.get("role") == "EXPERIMENT_AGENT" and present(owner.get("actor_id")), f"{label}: implementation owner must identify EXPERIMENT_AGENT", errors)
        elif version == "experiment-request-queue-v3":
            for field in ("admissibility_contract", "experiment_class", "tested_candidate_ids", "implementation_owner"):
                require(present(request.get(field)), f"{label}: missing static-admissibility field {field}", errors)
            require(request.get("experiment_kind") == "STATIC_ADMISSIBILITY", f"{label}: v3 request must be STATIC_ADMISSIBILITY", errors)
            require(request.get("experiment_class") == "SCREENING", f"{label}: static-admissibility must use SCREENING", errors)
            require(not any(field in request for field in ("decision_contract", "measurability_contract", "sensitivity")), f"{label}: static-admissibility request contains forbidden performance-decision fields", errors)
            owner = request.get("implementation_owner", {})
            require(owner.get("role") == "EXPERIMENT_AGENT" and present(owner.get("actor_id")), f"{label}: implementation owner must identify EXPERIMENT_AGENT", errors)
        request_cases = {str(item) for item in request.get("workload_cases", [])}
        require(bool(request_cases) and request_cases <= valid_cases, f"{label}: workload_cases must be a non-empty workload subset", errors)
        sensitivity = request.get("sensitivity", {})
        if version == "experiment-request-queue-v2":
            sensitivity_fields = ("candidate_specific_decision_value_us", "decision_flip_probability", "expected_uncertainty_reduction", "experiment_cost")
        elif version == "experiment-request-queue-v3":
            sensitivity_fields = ()
        else:
            sensitivity_fields = ("max_weighted_benefit_us", "critical_path_probability", "uncertainty", "experiment_cost")
        for field in sensitivity_fields:
            require(present(sensitivity.get(field)), f"{label}: sensitivity.{field} is required", errors)
        status = request.get("status")
        require(status in {"PROPOSED", "PLANNED", "DISPATCHED", "RUNNING", "RESOLVED", "REJECTED", "BLOCKED", "AWAITING_SUPERVISOR_REVIEW", "HALT_AND_REPLAN", "STOPPED"}, f"{label}: invalid status", errors)
        catalog = request.get("catalog_resolution", {})
        require(present(catalog.get("query")), f"{label}: catalog_resolution.query is required", errors)
        if status != "PROPOSED":
            require(catalog.get("catalog_queried") is True, f"{label}: reusable catalog must have a deterministic receipt before planning/dispatch", errors)
            for field in ("decision", "reason"):
                require(present(catalog.get(field)), f"{label}: catalog_resolution.{field} is required", errors)
            require(catalog.get("decision") in {"REUSE", "CREATE_RUN_LOCAL", "BLOCKED"}, f"{label}: invalid catalog decision", errors)
            if catalog.get("decision") == "REUSE":
                require(present(catalog.get("package_id")), f"{label}: REUSE requires package_id", errors)
        require(present(request.get("result_binding")), f"{label}: result_binding is required", errors)
        promotion = request.get("promotion_disposition", {})
        require(present(promotion), f"{label}: promotion_disposition is required", errors)
        if request.get("status") == "RESOLVED":
            require(request.get("result_binding", {}).get("status") == "BOUND", f"{label}: RESOLVED requires a BOUND result", errors)
            require(present(request.get("result_binding", {}).get("evidence")), f"{label}: RESOLVED requires immutable evidence", errors)
            if catalog.get("decision") == "CREATE_RUN_LOCAL":
                require(promotion.get("status") in {"RUN_LOCAL", "PROMOTED", "REJECTED"}, f"{label}: resolved run-local probe requires promotion review", errors)
                require(present(promotion.get("reason")), f"{label}: promotion review requires a reason", errors)
    if version == "experiment-request-queue-v3":
        active = [request for request in requests if request.get("status") in {"PROPOSED", "PLANNED", "DISPATCHED", "RUNNING"}]
        require(len(active) == 1, "static-admissibility queue must contain exactly one active gate", errors)


# ---------------------------------------------------------------------------
# Evidence-closed strict hardware, binary, experiment and P0 gates
# ---------------------------------------------------------------------------


def validate_strict_hardware_and_resources(run: Path, architecture: dict, global_state: dict, errors: list[str]) -> None:
    hardware_evidence_path = run / "hardware_evidence.json"
    if not hardware_evidence_path.exists():
        errors.append("evidence-closed contract: hardware_evidence.json is required")
        return
    errors.extend(f"evidence-closed contract: {item}" for item in validate_hardware_evidence(hardware_evidence_path))
    discovery_path = run / "models/resource_discovery.json"
    discovery = read_object(discovery_path, errors)
    require(discovery.get("schema_version") == "resource-discovery-v2", "evidence-closed contract: resource discovery must use v2", errors)
    require(discovery.get("status") == "READY", "evidence-closed contract: resource discovery must be READY", errors)
    require(not discovery.get("unresolved_mappings"), "evidence-closed contract: resource discovery has unresolved mappings", errors)
    validate_identity(run, discovery.get("binary_identity", {}), "resource discovery binary identity", errors, containment_root=run)
    validate_identity(run, discovery.get("sass_input_identity", {}), "resource discovery SASS input identity", errors, containment_root=run)
    validate_identity(run, discovery.get("sass_summary_identity", {}), "resource discovery SASS summary identity", errors, containment_root=run)
    validate_identity(run, discovery.get("disassembly_receipt_identity", {}), "resource discovery disassembly identity", errors, containment_root=run)
    detector = discovery.get("detector_identity", {})
    expected_detector = Path(__file__).with_name("discover_resources.py")
    require(detector.get("sha256") == evidence_sha256(expected_detector), "evidence-closed contract: resource discovery detector identity is stale or forged", errors)
    validate_identity(run, discovery.get("hardware_evidence_identity", {}), "resource discovery hardware evidence identity", errors, containment_root=run)
    sass_path = resolve_evidence_path(run, str(discovery.get("sass_summary_identity", {}).get("path", "")))
    sass = read_object(sass_path, errors)
    require(sass.get("schema_version") == "sass-instruction-count-v2" and sass.get("status") == "PASS", "evidence-closed contract: SASS classification must PASS v2", errors)
    require(sass.get("coverage", {}).get("site_coverage_fraction") == 1.0, "evidence-closed contract: SASS mnemonic coverage must be exactly 100%", errors)
    require(not sass.get("unclassified_mnemonics") and not sass.get("ambiguous_mnemonics"), "evidence-closed contract: unknown/ambiguous SASS mnemonics remain", errors)
    try:
        binary_path = resolve_evidence_path(run, str(discovery.get("binary_identity", {}).get("path", "")))
        sass_input_path = resolve_evidence_path(run, str(discovery.get("sass_input_identity", {}).get("path", "")))
        receipt_path = resolve_evidence_path(run, str(discovery.get("disassembly_receipt_identity", {}).get("path", "")))
        _, receipt_errors = validate_disassembly_receipt(receipt_path, binary_path, sass_input_path)
        errors.extend(f"evidence-closed contract: {item}" for item in receipt_errors)
    except Exception as error:
        errors.append(f"evidence-closed contract: cannot reproduce disassembly receipt: {error}")
    required = set(map(str, discovery.get("required_resource_ids", [])))
    expected_required = {resource for instruction_class in observed_classes(sass) for resource in CLASS_RULES.get(instruction_class, ([], []))[0]}
    if observed_classes(sass):
        expected_required |= {"kernel_dispatch", "cta_allocation"}
    require(required == expected_required, f"evidence-closed contract: discovered resource set is not reproducible; expected={sorted(expected_required)}, observed={sorted(required)}", errors)
    manifest = read_object(hardware_evidence_path, errors)
    official_available = {
        str(fact.get("field")).split(".")[1]
        for fact in manifest.get("facts", [])
        if str(fact.get("field", "")).startswith("resource.")
        and str(fact.get("field")).endswith(".available")
        and fact.get("value") is True
        and len(str(fact.get("field")).split(".")) >= 3
    }
    observed_available = set(map(str, discovery.get("official_available_resource_ids", [])))
    require(observed_available == official_available, "evidence-closed contract: officially available resource set is not reproducible from reviewed facts", errors)
    candidates = set(map(str, discovery.get("candidate_resource_ids", required)))
    require(candidates == required | official_available, "evidence-closed contract: candidate resource set must equal required union officially available", errors)
    material = set(map(str, global_state.get("material_resources", [])))
    require(bool(required), "evidence-closed contract: discovered resource set must not be empty", errors)
    require(material == required, f"evidence-closed contract: global material resources must exactly match discovery; missing={sorted(required-material)}, extra={sorted(material-required)}", errors)
    modeled = resource_node_ids(architecture)
    require(candidates <= modeled, f"evidence-closed contract: microarchitecture model omits observed or officially available resources {sorted(candidates-modeled)}", errors)


def validate_strict_ranking(run: Path, queue: dict, errors: list[str]) -> None:
    formula = queue.get("ranking_policy", {}).get("formula")
    queue_version = queue.get("schema_version")
    if queue_version == "experiment-request-queue-v3":
        require(formula == "NO_PERFORMANCE_RANKING_SINGLE_STATIC_GATE", "static-admissibility contract: performance ranking is forbidden", errors)
        active = [request for request in queue.get("requests", []) if request.get("status") in {"PROPOSED", "PLANNED", "DISPATCHED", "RUNNING"}]
        require(len(active) == 1 and int(active[0].get("priority", -1)) == 0, "static-admissibility contract: exactly one priority-zero active gate is required", errors)
        for request in queue.get("requests", []):
            require("sensitivity" not in request, f"static-admissibility request {request.get('request_id')}: performance sensitivity is forbidden", errors)
        return
    if queue_version == "experiment-request-queue-v2":
        value_field = "candidate_specific_decision_value_us"
        expected_formula = f"{value_field} * decision_flip_probability * expected_uncertainty_reduction / experiment_cost_weight"
        require(formula == expected_formula, "candidate-supervised contract: decision-value ranking formula is missing or changed", errors)
        ranked = []
        for request in queue.get("requests", []):
            if request.get("status") not in {"PROPOSED", "PLANNED"}:
                continue
            sensitivity = request.get("sensitivity", {})
            decision_path = artifact_path(run, request.get("decision_contract", {}))
            if not decision_path.is_file():
                errors.append(f"candidate-supervised request {request.get('request_id')}: decision contract is missing")
                continue
            decision = read_object(decision_path, errors)
            need = decision.get("measurement_need", {})
            try:
                value = float(need["maximum_decision_value"]["value"])
                probability = float(need["decision_flip_probability"])
                reduction = float(need["expected_uncertainty_reduction"])
                cost_weight = float(sensitivity["experiment_cost_weight"])
                expected = value * probability * reduction / cost_weight
                require(math.isclose(value, float(sensitivity[value_field]), rel_tol=1e-12), f"candidate-supervised request {request.get('request_id')}: stale decision value", errors)
                require(math.isclose(probability, float(sensitivity["decision_flip_probability"]), rel_tol=1e-12), f"candidate-supervised request {request.get('request_id')}: stale flip probability", errors)
                require(math.isclose(reduction, float(sensitivity["expected_uncertainty_reduction"]), rel_tol=1e-12), f"candidate-supervised request {request.get('request_id')}: stale uncertainty reduction", errors)
                require(math.isclose(expected, float(sensitivity["ranking_score"]), rel_tol=1e-12), f"candidate-supervised request {request.get('request_id')}: ranking score mismatch", errors)
                ranked.append((int(request.get("priority", -1)), -expected, str(request.get("request_id"))))
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                errors.append(f"candidate-supervised request {request.get('request_id')}: incomplete ranking inputs")
        require([item[0] for item in sorted(ranked, key=lambda item: (item[1], item[2]))] == list(range(len(ranked))), "candidate-supervised contract: priority differs from candidate-specific decision value", errors)
        return
    require(formula == "max_weighted_benefit_us * critical_path_probability * uncertainty_weight / experiment_cost_weight", "evidence-closed contract: experiment ranking formula is missing or changed", errors)
    workload = read_object(run / "workload.json", errors)
    balance = read_object(run / "models/resource_balance.json", errors)
    weights = {str(case.get("id")): float(case.get("weight", 0.0)) for case in workload.get("cases", [])}
    balance_cases = {str(case.get("case_id")): case for case in balance.get("cases", [])}
    scores = []
    for request in queue.get("requests", []):
        sensitivity = request.get("sensitivity", {})
        derivation = sensitivity.get("benefit_derivation", {})
        require(present(derivation.get("case_contributions")), f"evidence-closed contract: {request.get('request_id')} lacks model-derived benefit contributions", errors)
        try:
            contributions = derivation["case_contributions"]
            require({str(item.get("case_id")) for item in contributions} == set(map(str, request.get("workload_cases", []))), f"evidence-closed contract: {request.get('request_id')} ranking case coverage mismatch", errors)
            for item in contributions:
                case = balance_cases[str(item["case_id"])]
                stage_times = case.get("critical_path", {}).get("stage_gpu_active_us", {})
                stages = set(map(str, request.get("affected_stage_ids", [])))
                expected_removable = min(float(case.get("critical_path", {}).get("total_us", sum(stage_times.values()))), sum(float(stage_times[stage]) for stage in stages))
                require(set(map(str, item.get("stages", []))) == stages and math.isclose(expected_removable, float(item["max_removable_us"]), rel_tol=1e-12, abs_tol=1e-12), f"evidence-closed contract: {request.get('request_id')} stage benefit window mismatch", errors)
            upper = sum(float(item["max_removable_us"]) * weights[str(item["case_id"])] for item in contributions)
            require(math.isclose(upper, float(sensitivity["max_weighted_benefit_us"]), rel_tol=1e-12, abs_tol=1e-12), f"evidence-closed contract: {request.get('request_id')} benefit bound mismatch", errors)
            probability = sum(float(item["max_removable_us"]) * weights[str(item["case_id"])] * float(item["critical_path_probability"]) for item in contributions) / upper if upper > 0 else 0.0
            require(math.isclose(probability, float(sensitivity["critical_path_probability"]), rel_tol=1e-12, abs_tol=1e-12), f"evidence-closed contract: {request.get('request_id')} critical-path probability is not model-derived", errors)
            expected = (
                float(sensitivity["max_weighted_benefit_us"])
                * float(sensitivity["critical_path_probability"])
                * float(sensitivity["uncertainty_weight"])
                / float(sensitivity["experiment_cost_weight"])
            )
            require(math.isclose(expected, float(sensitivity["ranking_score"]), rel_tol=1e-9, abs_tol=1e-12), f"evidence-closed contract: {request.get('request_id')} ranking score is not derived from policy", errors)
            scores.append((int(request.get("priority", -1)), -expected, str(request.get("request_id"))))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            errors.append(f"evidence-closed contract: {request.get('request_id')} ranking fields are incomplete")
    expected_order = sorted(scores, key=lambda item: (item[1], item[2]))
    require([item[0] for item in expected_order] == list(range(len(expected_order))), "evidence-closed contract: queue priority does not match reproducible score order", errors)


def validate_strict_p0(run: Path, microbench: dict, errors: list[str]) -> None:
    p0 = microbench.get("levels", {}).get("P0", {})
    if p0.get("status") != "PASS":
        return
    evidence = p0.get("evidence", [])
    errors.extend(validate_evidence_references(run, evidence, "P0 level evidence"))
    for record in evidence if isinstance(evidence, list) else []:
        path = resolve_evidence_path(run, str(record.get("path", "")))
        errors.extend(validate_p0_receipt(path, run))


def validate_strict_requests(run: Path, queue: dict, errors: list[str]) -> None:
    project_root = run.parent.parent
    catalog_path = project_root / "microbench/catalog.json"
    for request in queue.get("requests", []):
        status = request.get("status")
        label = f"evidence-closed request {request.get('request_id')}"
        catalog = request.get("catalog_resolution", {})
        if queue.get("schema_version") == "experiment-request-queue-v2":
            decision_path = artifact_path(run, request.get("decision_contract", {}))
            measurability_path = artifact_path(run, request.get("measurability_contract", {}))
            if decision_path.is_file():
                errors.extend(f"{label}: {item}" for item in validate_decision_contract(decision_path, run))
            else:
                errors.append(f"{label}: decision contract is missing")
            if decision_path.is_file() and measurability_path.is_file():
                errors.extend(f"{label}: {item}" for item in validate_measurability_contract(measurability_path, run, decision_path))
            else:
                errors.append(f"{label}: measurability contract is missing")
        elif queue.get("schema_version") == "experiment-request-queue-v3":
            contract_path = artifact_path(run, request.get("admissibility_contract", {}))
            if contract_path.is_file():
                errors.extend(f"{label}: {item}" for item in validate_admissibility_contract(contract_path, run))
            else:
                errors.append(f"{label}: admissibility contract is missing")
        if status in {"PLANNED", "DISPATCHED", "RUNNING", "RESOLVED", "REJECTED"}:
            receipt = catalog.get("receipt", {})
            validate_identity(run, receipt, f"{label} catalog receipt", errors)
            if receipt.get("path"):
                receipt_path = resolve_evidence_path(run, str(receipt["path"]))
                errors.extend(validate_catalog_receipt(receipt_path, catalog_path, catalog.get("query", {})))
        experiment_path = None
        if status in {"DISPATCHED", "RUNNING", "RESOLVED"}:
            identity = request.get("materialized_experiment", {})
            validate_identity(run, identity, f"{label} materialized experiment", errors)
            if identity.get("path"):
                experiment_path = resolve_evidence_path(run, str(identity["path"]))
                errors.extend(validate_materialized_experiment(experiment_path, run))
                if queue.get("schema_version") == "experiment-request-queue-v2":
                    approval_path = artifact_path(run, request.get("supervisor_approval", {}))
                    errors.extend(f"{label}: {item}" for item in validate_supervisor_approval(approval_path, run, request, experiment_path))
                elif queue.get("schema_version") == "experiment-request-queue-v3":
                    approval_path = artifact_path(run, request.get("supervisor_approval", {}))
                    errors.extend(f"{label}: {item}" for item in validate_supervisor_approval(approval_path, run, request, experiment_path))
        if status in {"RUNNING", "RESOLVED"} and experiment_path is not None:
            execution = request.get("execution_receipt", {})
            validate_identity(run, execution, f"{label} execution receipt", errors)
            if execution.get("path"):
                execution_path = resolve_evidence_path(run, str(execution["path"]))
                errors.extend(validate_execution_receipt(execution_path, run, experiment_path, str(request.get("request_id"))))
        if status == "RESOLVED":
            binding = request.get("result_binding", {})
            result_evidence = binding.get("evidence", [])
            errors.extend(validate_evidence_references(run, result_evidence, f"{label} result"))
            for record in result_evidence if isinstance(result_evidence, list) else []:
                path = resolve_evidence_path(run, str(record.get("path", "")))
                errors.extend(validate_benchmark_result(
                    path, run,
                    request_id=str(request.get("request_id")),
                    experiment_path=experiment_path,
                ))
            reconciliation = binding.get("model_reconciliation", {})
            validate_identity(run, reconciliation, f"{label} reconciliation receipt", errors)
            require(reconciliation.get("status") == "APPLIED", f"{label}: result must be reconciled into the global model before closure", errors)
            require(present(reconciliation.get("model_revision_identities")), f"{label}: applied reconciliation requires model revision identities", errors)
            if reconciliation.get("path"):
                reconciliation_path = resolve_evidence_path(run, str(reconciliation["path"]))
                reconciliation_data = read_object(reconciliation_path, errors)
                semantic = reconciliation_data.get("semantic_update_identity", {})
                validate_identity(run, semantic, f"{label} semantic model update", errors)
                for name, identity in reconciliation.get("model_revision_identities", {}).items():
                    canonical = run / "models" / f"{name}.json"
                    require(canonical.is_file() and identity.get("sha256") == evidence_sha256(canonical), f"{label}: reconciled model identity is stale for {name}", errors)
        if status == "BLOCKED":
            errors.extend(validate_evidence_references(run, request.get("blocking_evidence"), f"{label} blocking evidence"))


def validate_strict_resource_rows(run: Path, balance: dict, errors: list[str]) -> None:
    for case in balance.get("cases", []):
        for row in case.get("resource_rows", []):
            states = {
                row.get("matched_saturation", {}).get("status"),
                row.get("utilization", {}).get("status"),
                row.get("critical_path", {}).get("status"),
            }
            if states & {"MEASURED", "BOUNDED"}:
                errors.extend(validate_evidence_references(
                    run,
                    row.get("evidence"),
                    f"resource {case.get('case_id')}/{row.get('resource_id')} measured/bounded evidence",
                ))


# ---------------------------------------------------------------------------
# Resource balance, tradeoff frontier and model-closure semantics
# ---------------------------------------------------------------------------


def validate_resource_balance(balance: dict, workload: dict, material: set[str], queue: dict, errors: list[str]) -> None:
    version = balance.get("schema_version")
    require(version in {"resource-balance-ledger-v1", "resource-balance-ledger-v2"}, "resource balance: invalid schema_version", errors)
    indexed = indexed_cases(balance, "resource balance", errors)
    require_coverage(indexed, case_ids(workload), "resource balance", errors)
    request_ids = {str(item.get("request_id")) for item in queue.get("requests", []) if isinstance(item, dict) and item.get("request_id")}
    for case_id, case in indexed.items():
        rows = case.get("resource_rows", [])
        require(isinstance(rows, list) and bool(rows), f"resource balance {case_id}: resource_rows must not be empty", errors)
        by_id = {str(row.get("resource_id")): row for row in rows if isinstance(row, dict) and row.get("resource_id")}
        require(material <= set(by_id), f"resource balance {case_id}: missing material resources {sorted(material - set(by_id))}", errors)
        for resource_id in material:
            row = by_id.get(resource_id, {})
            require(row.get("material") is True, f"resource balance {case_id}/{resource_id}: material must be true", errors)
            for field in ("resource_kind", "mandatory_work", "actual_work", "production_point", "matched_saturation", "utilization", "critical_path", "non_saturation_causes", "evidence", "unresolved_request_ids"):
                require(field in row, f"resource balance {case_id}/{resource_id}: missing {field}", errors)
            saturation = row.get("matched_saturation", {})
            utilization = row.get("utilization", {})
            critical = row.get("critical_path", {})
            causes = set(row.get("non_saturation_causes", []))
            require(bool(causes), f"resource balance {case_id}/{resource_id}: non_saturation_causes must not be empty", errors)
            require(causes <= NON_SATURATION_CAUSES, f"resource balance {case_id}/{resource_id}: invalid non-saturation cause", errors)
            require(saturation.get("status") in RESOURCE_STATES, f"resource balance {case_id}/{resource_id}: invalid saturation status", errors)
            require(utilization.get("status") in RESOURCE_STATES, f"resource balance {case_id}/{resource_id}: invalid utilization status", errors)
            require(critical.get("status") in RESOURCE_STATES, f"resource balance {case_id}/{resource_id}: invalid critical-path status", errors)
            validate_quantity(row.get("mandatory_work", {}), f"resource balance {case_id}/{resource_id} mandatory_work", errors)
            validate_quantity(row.get("actual_work", {}), f"resource balance {case_id}/{resource_id} actual_work", errors)
            mandatory = row.get("mandatory_work", {})
            actual = row.get("actual_work", {})
            if mandatory.get("unit") == actual.get("unit") and finite_number(mandatory.get("value"), minimum=0) and finite_number(actual.get("value"), minimum=0):
                require(float(actual["value"]) >= float(mandatory["value"]), f"resource balance {case_id}/{resource_id}: actual work cannot be below mandatory work", errors)
            for field in ("numerator", "denominator", "time_window", "boundary"):
                require(field in utilization, f"resource balance {case_id}/{resource_id}: utilization.{field} is required", errors)
            require(finite_number(critical.get("probability"), minimum=0.0, maximum=1.0), f"resource balance {case_id}/{resource_id}: critical_path.probability must be in [0,1]", errors)
            if critical.get("status") in {"MEASURED", "BOUNDED"}:
                require(finite_number(critical.get("contribution_us"), minimum=0.0), f"resource balance {case_id}/{resource_id}: critical contribution must be non-negative", errors)
            if saturation.get("status") in {"MEASURED", "BOUNDED"}:
                require(finite_number(saturation.get("value"), minimum=1e-300) and present(saturation.get("unit")) and present(saturation.get("conditions")), f"resource balance {case_id}/{resource_id}: closed saturation requires a positive value, unit and conditions", errors)
            if utilization.get("status") in {"MEASURED", "BOUNDED"}:
                validate_quantity(utilization.get("numerator", {}), f"resource balance {case_id}/{resource_id} utilization numerator", errors)
                validate_quantity(utilization.get("denominator", {}), f"resource balance {case_id}/{resource_id} utilization denominator", errors, positive=True)
                numerator = utilization.get("numerator", {})
                denominator = utilization.get("denominator", {})
                require(numerator.get("unit") == denominator.get("unit"), f"resource balance {case_id}/{resource_id}: utilization numerator/denominator units differ", errors)
                require(finite_number(utilization.get("value_percent"), minimum=0.0, maximum=100.0), f"resource balance {case_id}/{resource_id}: utilization percent must be in [0,100]", errors)
                if finite_number(numerator.get("value"), minimum=0) and finite_number(denominator.get("value"), minimum=1e-300) and finite_number(utilization.get("value_percent"), minimum=0):
                    expected_percent = float(numerator["value"]) / float(denominator["value"]) * 100.0
                    require(math.isclose(expected_percent, float(utilization["value_percent"]), rel_tol=1e-6, abs_tol=1e-6), f"resource balance {case_id}/{resource_id}: utilization ratio does not match numerator/denominator", errors)
            if row.get("resource_kind") == "TENSOR_CORE":
                compute = row.get("compute_efficiency", {})
                for field in ("device_coverage", "eligible_time_fraction", "eligible_window_issue_efficiency", "composition_status"):
                    require(field in compute, f"resource balance {case_id}/{resource_id}: compute_efficiency.{field} is required", errors)
                tensor_states = {
                    saturation.get("status"),
                    utilization.get("status"),
                    critical.get("status"),
                }
                efficiency_fields = ("device_coverage", "eligible_time_fraction", "eligible_window_issue_efficiency")
                if tensor_states & {"MEASURED", "BOUNDED"}:
                    for field in efficiency_fields:
                        require(finite_number(compute.get(field), minimum=0.0, maximum=1.0), f"resource balance {case_id}/{resource_id}: compute_efficiency.{field} must be in [0,1] once Tensor Core service is measured or bounded", errors)
                    require(compute.get("composition_status") in {"MEASURED", "BOUNDED"}, f"resource balance {case_id}/{resource_id}: compute_efficiency.composition_status must close with its numeric factors", errors)
                else:
                    for field in efficiency_fields:
                        require(compute.get(field) is None, f"resource balance {case_id}/{resource_id}: UNKNOWN Tensor Core efficiency must keep compute_efficiency.{field} null", errors)
                    require(compute.get("composition_status") == "UNKNOWN", f"resource balance {case_id}/{resource_id}: unresolved Tensor Core efficiency must use composition_status=UNKNOWN", errors)
            if row.get("resource_kind") in {"L2", "DEVICE_MEMORY"} and utilization.get("status") in {"MEASURED", "BOUNDED"}:
                require(utilization.get("boundary") == row.get("resource_kind"), f"resource balance {case_id}/{resource_id}: memory utilization boundary mismatch", errors)
            unresolved = {str(item) for item in row.get("unresolved_request_ids", [])}
            require(unresolved <= request_ids, f"resource balance {case_id}/{resource_id}: unresolved request is not in global queue", errors)
            if "UNKNOWN" in {saturation.get("status"), utilization.get("status"), critical.get("status")}:
                if version == "resource-balance-ledger-v2":
                    relevance = row.get("decision_relevance", {})
                    require(relevance.get("status") in {"TOP_TWO_SENSITIVE", "NOT_TOP_TWO_SENSITIVE"}, f"resource balance {case_id}/{resource_id}: UNKNOWN must be assessed against the top-two candidate decision", errors)
                    if relevance.get("status") == "TOP_TWO_SENSITIVE":
                        require(bool(unresolved) and bool(relevance.get("decision_contract_ids")), f"resource balance {case_id}/{resource_id}: top-two-sensitive UNKNOWN requires a decision-bound request", errors)
                    else:
                        require(not unresolved and present(relevance.get("explanation")), f"resource balance {case_id}/{resource_id}: non-sensitive UNKNOWN requires an explanation and no experiment", errors)
                else:
                    require(bool(unresolved), f"resource balance {case_id}/{resource_id}: UNKNOWN requires a dispatched experiment request", errors)
            else:
                require(present(row.get("evidence")), f"resource balance {case_id}/{resource_id}: closed row requires evidence", errors)
        for field in ("device_coverage", "critical_path", "model_residual"):
            require(present(case.get(field)), f"resource balance {case_id}: missing {field}", errors)


def validate_tradeoff_frontier(frontier: dict, workload: dict, errors: list[str]) -> None:
    require(frontier.get("schema_version") == "tradeoff-frontier-v1", "tradeoff frontier: invalid schema_version", errors)
    indexed = indexed_cases(frontier, "tradeoff frontier", errors)
    require_coverage(indexed, case_ids(workload), "tradeoff frontier", errors)
    required_point_fields = (
        "schedule_id", "correctness", "valid_compute", "padded_compute",
        "bytes_by_boundary", "allocation", "device_coverage", "synchronization",
        "predicted_dag_us", "measured_us", "uncertainty", "decision",
    )
    for case_id, case in indexed.items():
        require(present(case.get("legal_minimum")), f"tradeoff frontier {case_id}: legal_minimum is required", errors)
        current = case.get("current_schedule", {})
        for field in required_point_fields:
            require(field in current, f"tradeoff frontier {case_id}: current_schedule.{field} is required", errors)
        require(isinstance(case.get("candidates"), list), f"tradeoff frontier {case_id}: candidates must be a list", errors)
        require(isinstance(case.get("pareto_frontier"), list), f"tradeoff frontier {case_id}: pareto_frontier must be a list", errors)


def require_terminal_global_model(balance: dict, queue: dict, errors: list[str]) -> None:
    terminal = {"RESOLVED", "REJECTED", "BLOCKED"}
    for request in queue.get("requests", []):
        require(request.get("status") in terminal, f"experiment request {request.get('request_id')}: must be terminal before production validation", errors)
    for case in balance.get("cases", []):
        for row in case.get("resource_rows", []):
            if row.get("material"):
                for field in ("matched_saturation", "utilization", "critical_path"):
                    require(row.get(field, {}).get("status") != "UNKNOWN", f"resource balance {case.get('case_id')}/{row.get('resource_id')}: {field} remains UNKNOWN", errors)


# ---------------------------------------------------------------------------
# Non-skippable phase gates
# ---------------------------------------------------------------------------


def planning_gate(run: Path, workload: dict, errors: list[str]) -> None:
    plan = read_object(run / "models/optimization_plan.json", errors)
    architecture = read_object(run / "models/microarchitecture_model.json", errors)
    microbench = read_object(run / "models/microbenchmark_plan.json", errors)
    global_state, balance, frontier, queue = global_artifacts(run, workload, errors)
    if evidence_closed_contract(run):
        validate_schema_artifacts(run, (
            ("operator.json", "operator_contract.schema.json"),
            ("workload.json", "workload.schema.json"),
            ("hardware.json", "hardware_snapshot.schema.json"),
            ("hardware_evidence.json", "hardware_evidence_manifest.schema.json"),
            ("models/resource_discovery.json", "resource_discovery.schema.json"),
            ("models/optimization_plan.json", "optimization_plan.schema.json"),
            ("models/microarchitecture_model.json", "microarchitecture_model.schema.json"),
            ("models/global_schedule_state.json", "global_schedule_state.schema.json"),
            ("models/resource_balance.json", "resource_balance_ledger.schema.json"),
            ("models/tradeoff_frontier.json", "tradeoff_frontier.schema.json"),
            ("models/experiment_queue.json", "experiment_request.schema.json"),
            ("models/microbenchmark_plan.json", "microbenchmark_plan.schema.json"),
        ), errors)
        validate_strict_hardware_and_resources(run, architecture, global_state, errors)
        validate_strict_ranking(run, queue, errors)
    require(plan.get("status") == "EXECUTABLE", "planning: optimization_plan.status must be EXECUTABLE", errors)
    for field in (
        "objective",
        "global_scheduler_owner",
        "workload_priorities",
        "experiment_queue",
        "correctness_gates",
        "evidence_gates",
        "acceptance_rule",
        "stop_criteria",
        "revision_history",
    ):
        require(present(plan.get(field)), f"planning: optimization_plan.{field} must be populated", errors)
    tolerances = plan.get("model_error_tolerances_percent", {})
    for field in ("p1_p2_to_p3", "schedule_to_p4", "achieved_to_feasible_bound"):
        try:
            require(float(tolerances[field]) > 0, f"planning: tolerance {field} must be positive", errors)
        except (KeyError, TypeError, ValueError):
            errors.append(f"planning: tolerance {field} must be numeric")
    priorities = {str(item.get("case_id")) for item in plan.get("workload_priorities", []) if isinstance(item, dict)}
    require_coverage({key: {} for key in priorities}, case_ids(workload), "planning workload priorities", errors)
    require(present(architecture.get("target_identity")), "planning: microarchitecture target_identity is required", errors)
    require(present(architecture.get("scope")), "planning: relevant microarchitecture scope is required", errors)
    require(present(microbench.get("target_questions")), "planning: microbenchmark target_questions are required", errors)
    levels = microbench.get("levels", {})
    require(set(levels) == {"P0", "P1", "P2", "P3", "P4"}, "planning: microbenchmark levels must be exactly P0-P4", errors)
    require(global_state.get("status") == "PLANNED", "planning: global_schedule_state.status must be PLANNED", errors)
    require(plan.get("global_scheduler_owner") == global_state.get("owner", {}).get("owner_id"), "planning: plan/global scheduler owner mismatch", errors)
    if global_state.get("schema_version") == "global-schedule-state-v2":
        require(plan.get("global_supervisor_owner") == global_state.get("supervisor", {}).get("owner_id"), "planning: plan/global supervisor owner mismatch", errors)
        require(plan.get("candidate_limit") in {2, 3, 4}, "planning: candidate_limit must be 2-4", errors)
        require(present(plan.get("screening_budget")) and present(plan.get("qualification_budget")), "planning: screening and qualification budgets are required", errors)
        for tier in ("screening", "qualification"):
            budget = plan.get(f"{tier}_budget", {})
            for field in ("max_configurations", "max_samples_per_configuration", "max_process_launches", "max_wall_clock_minutes"):
                require(finite_number(budget.get(field), minimum=1e-300), f"planning: {tier}_budget.{field} must be positive", errors)
        require(finite_number(plan.get("max_revisions_per_decision"), minimum=0), "planning: max_revisions_per_decision must be non-negative", errors)
    require(present(global_state.get("revision_history")), "planning: global scheduler revision_history is required", errors)
    require(present(global_state.get("decision_policy", {}).get("objective")), "planning: global scheduler decision objective is required", errors)
    require(balance.get("status") == "INITIALIZED", "planning: resource balance must be INITIALIZED", errors)
    require(frontier.get("status") == "INITIALIZED", "planning: tradeoff frontier must be INITIALIZED", errors)
    require(queue.get("status") == "EXECUTABLE", "planning: global experiment queue must be EXECUTABLE", errors)


def baseline_gate(run: Path, workload: dict, errors: list[str]) -> None:
    baseline = read_object(run / "models/baseline.json", errors)
    if evidence_closed_contract(run):
        validate_schema_artifacts(run, (("models/baseline.json", "production_baseline.schema.json"),), errors)
    require(baseline.get("status") == "VALID", "baseline: status must be VALID", errors)
    require(baseline.get("correctness", {}).get("status") == "PASS", "baseline: correctness must PASS", errors)
    require(present(baseline.get("source_identities")), "baseline: source identities are required", errors)
    if evidence_closed_contract(run):
        errors.extend(validate_evidence_references(run, baseline.get("source_identities"), "baseline source identities"))
        errors.extend(validate_evidence_references(run, baseline.get("correctness", {}).get("evidence"), "baseline correctness evidence"))
    for field in ("cpu_dispatch", "gpu_active", "end_to_end"):
        require(present(baseline.get("measurement_methods", {}).get(field)), f"baseline: measurement method {field} is required", errors)
    for field in ("competing_load", "clock_power_policy", "thermal_policy", "warmup_and_cold_start"):
        require(present(baseline.get("environment_controls", {}).get(field)), f"baseline: environment control {field} is required", errors)
    indexed = indexed_cases(baseline, "baseline", errors)
    require_coverage(indexed, case_ids(workload), "baseline", errors)
    for key, case in indexed.items():
        require(case.get("correctness") == "PASS", f"baseline {key}: correctness must PASS", errors)
        for field in ("source_identity", "raw_samples", "cpu_dispatch", "gpu_active", "end_to_end"):
            require(present(case.get(field)), f"baseline {key}: missing {field}", errors)
        if evidence_closed_contract(run):
            validate_identity(run, case.get("source_identity", {}), f"baseline {key} source", errors, containment_root=run)
            validate_identity(run, case.get("raw_samples", {}), f"baseline {key} raw samples", errors, containment_root=run)


def modeling_gate(run: Path, workload: dict, errors: list[str]) -> None:
    architecture = read_object(run / "models/microarchitecture_model.json", errors)
    ledger = read_object(run / "models/work_ledger.json", errors)
    dag = read_object(run / "models/dag.json", errors)
    schedule = read_object(run / "models/schedule_model.json", errors)
    microbench = read_object(run / "models/microbenchmark_plan.json", errors)
    global_state, balance, frontier, queue = global_artifacts(run, workload, errors)
    if evidence_closed_contract(run):
        validate_schema_artifacts(run, (
            ("models/microarchitecture_model.json", "microarchitecture_model.schema.json"),
            ("models/work_ledger.json", "mandatory_work_ledger.schema.json"),
            ("models/dag.json", "operator_dag.schema.json"),
            ("models/schedule_model.json", "resource_schedule_model.schema.json"),
            ("models/microbenchmark_plan.json", "microbenchmark_plan.schema.json"),
        ), errors)
        validate_strict_hardware_and_resources(run, architecture, global_state, errors)
        validate_strict_ranking(run, queue, errors)
        validate_strict_p0(run, microbench, errors)
        validate_strict_requests(run, queue, errors)
        validate_strict_resource_rows(run, balance, errors)
    require(architecture.get("status") in {"INITIALIZED", "CALIBRATED"}, "modeling: microarchitecture model must be INITIALIZED or CALIBRATED", errors)
    for field in ("target_identity", "resource_nodes", "workload_mappings", "evidence"):
        require(present(architecture.get(field)), f"modeling: microarchitecture_model.{field} is required", errors)
    ledger_cases = indexed_cases(ledger, "mandatory-work ledger", errors)
    require_coverage(ledger_cases, case_ids(workload), "mandatory-work ledger", errors)
    for key, case in ledger_cases.items():
        for field in ("valid_work", "padded_or_redundant_work", "assumptions", "evidence"):
            require(present(case.get(field)), f"mandatory-work ledger {key}: missing {field}", errors)
    require(present(dag.get("nodes")), "modeling: DAG nodes are required", errors)
    require(present(dag.get("critical_paths")), "modeling: DAG critical_paths are required", errors)
    require(schedule.get("status") in {"INITIALIZED", "CALIBRATED"}, "modeling: schedule model must be INITIALIZED or CALIBRATED", errors)
    for field in ("binary_identity", "sass_control_flow", "dynamic_instruction_method", "resource_mapping", "workload_cases", "evidence"):
        require(present(schedule.get(field)), f"modeling: schedule_model.{field} is required", errors)
    schedule_ids = {str(case.get("case_id")) for case in schedule.get("workload_cases", []) if isinstance(case, dict)}
    require_coverage({key: {} for key in schedule_ids}, case_ids(workload), "schedule model", errors)
    require(microbench.get("status") == "EXECUTABLE", "modeling: microbenchmark plan must be EXECUTABLE", errors)
    require(microbench.get("levels", {}).get("P0", {}).get("status") == "PASS", "modeling: P0 measurement-system calibration must PASS", errors)
    require(present(microbench.get("cross_layer_prediction_gates")), "modeling: cross-layer prediction gates are required", errors)
    p2 = microbench.get("levels", {}).get("P2", {})
    if p2.get("required", True):
        require(present(microbench.get("coupling_tests")), "modeling: required P2 needs coupling tests", errors)
    require(global_state.get("status") == "MODEL_READY", "modeling: global_schedule_state.status must be MODEL_READY", errors)
    require(balance.get("status") in {"INITIALIZED", "CALIBRATED"}, "modeling: resource balance must be INITIALIZED or CALIBRATED", errors)
    require(frontier.get("status") in {"INITIALIZED", "CALIBRATED"}, "modeling: tradeoff frontier must be INITIALIZED or CALIBRATED", errors)
    require(queue.get("status") in {"EXECUTABLE", "ACTIVE"}, "modeling: experiment queue must be EXECUTABLE or ACTIVE", errors)
    for request in queue.get("requests", []):
        require(request.get("status") in {"DISPATCHED", "RESOLVED", "REJECTED", "BLOCKED"}, f"modeling: experiment request {request.get('request_id')} has not been dispatched", errors)


def experiment_gate(run: Path, workload: dict, errors: list[str]) -> None:
    architecture = read_object(run / "models/microarchitecture_model.json", errors)
    microbench = read_object(run / "models/microbenchmark_plan.json", errors)
    validation = read_object(run / "models/model_validation.json", errors)
    schedule = read_object(run / "models/schedule_model.json", errors)
    instruction = read_object(run / "static/instruction_audit.json", errors)
    global_state, balance, frontier, queue = global_artifacts(run, workload, errors)
    if evidence_closed_contract(run):
        validate_schema_artifacts(run, (
            ("models/model_validation.json", "cross_layer_model_validation.schema.json"),
            ("static/instruction_audit.json", "instruction_audit.schema.json"),
        ), errors)
        validate_strict_hardware_and_resources(run, architecture, global_state, errors)
        validate_strict_ranking(run, queue, errors)
        validate_strict_p0(run, microbench, errors)
        validate_strict_requests(run, queue, errors)
        validate_strict_resource_rows(run, balance, errors)
    require(architecture.get("status") in {"CALIBRATED", "VALIDATED"}, "experiment: microarchitecture model must be CALIBRATED or VALIDATED", errors)
    for field in ("resource_nodes", "allocation_constraints", "service_curves", "latency_constraints", "workload_mappings", "overlap_constraints", "evidence"):
        require(present(architecture.get(field)), f"experiment: microarchitecture_model.{field} is required", errors)
    levels = microbench.get("levels", {})
    for level in ("P0", "P1", "P3"):
        require(levels.get(level, {}).get("status") == "PASS", f"experiment: {level} must PASS", errors)
        if evidence_closed_contract(run):
            errors.extend(validate_evidence_references(run, levels.get(level, {}).get("evidence"), f"experiment {level} evidence"))
    p2 = levels.get("P2", {})
    if p2.get("status") == "NOT_APPLICABLE":
        require(p2.get("required") is False and present(p2.get("reason")), "experiment: P2 NOT_APPLICABLE requires required=false and a reason", errors)
    else:
        require(p2.get("status") == "PASS", "experiment: P2 must PASS or be justified NOT_APPLICABLE", errors)
        if evidence_closed_contract(run):
            errors.extend(validate_evidence_references(run, p2.get("evidence"), "experiment P2 evidence"))
    require(validation.get("measurement_system", {}).get("status") == "PASS", "experiment: measurement-system validation must PASS", errors)
    predictions = validation.get("component_predictions", [])
    require(present(predictions), "experiment: component predictions are required", errors)
    for index, record in enumerate(predictions if isinstance(predictions, list) else []):
        validate_prediction(record, f"component prediction {index}", errors, run)
    require(schedule.get("status") in {"CALIBRATED", "VALIDATED"}, "experiment: schedule model must be CALIBRATED or VALIDATED", errors)
    schedule_cases = {str(case.get("case_id")): case for case in schedule.get("workload_cases", []) if isinstance(case, dict) and case.get("case_id")}
    require_coverage(schedule_cases, case_ids(workload), "calibrated schedule", errors)
    for key, case in schedule_cases.items():
        for field in ("dynamic_instruction_work", "bounds", "predicted_production_us", "uncertainty"):
            require(present(case.get(field)), f"calibrated schedule {key}: missing {field}", errors)
        bounds = case.get("bounds", {})
        for field in ("silicon_lower", "resource_service", "dependency", "feasible_schedule"):
            require(present(bounds.get(field)), f"calibrated schedule {key}: missing bound {field}", errors)
    require(instruction.get("verdict") == "MATCH", "experiment: accepted candidate final-binary instruction audit must MATCH", errors)
    if evidence_closed_contract(run):
        require(instruction.get("schema_version") == "instruction-audit-v2", "instruction audit: strict runs require v2", errors)
        for identity_field in ("source_identity", "binary_identity", "sass_identity", "disassembly_receipt_identity"):
            validate_identity(run, instruction.get(identity_field, {}), f"instruction audit {identity_field}", errors, containment_root=run)
        discovery = read_object(run / "models/resource_discovery.json", errors)
        require(instruction.get("binary_identity", {}).get("sha256") == discovery.get("binary_identity", {}).get("sha256"), "instruction audit: accepted binary differs from resource discovery binary", errors)
        require(instruction.get("sass_identity", {}).get("sha256") == discovery.get("sass_input_identity", {}).get("sha256"), "instruction audit: accepted SASS differs from resource discovery SASS", errors)
        require(set(map(str, instruction.get("expected_signatures", []))) <= set(map(str, instruction.get("observed_sass_signatures", []))), "instruction audit: expected SASS signature is missing", errors)
        require(not instruction.get("material_mismatches") and not instruction.get("missing_evidence"), "instruction audit: MATCH cannot retain material mismatches or missing evidence", errors)
        mapped_resources = {str(item.get("resource_id") or item.get("resource")) for item in instruction.get("resource_mapping", []) if isinstance(item, dict)}
        require(set(map(str, discovery.get("required_resource_ids", []))) <= mapped_resources, "instruction audit: resource mapping does not cover discovered material resources", errors)
    for field in (
        "source_identity",
        "binary_identity",
        "resource_usage",
        "expected_signatures",
        "observed_sass_signatures",
        "sass_control_flow",
        "dynamic_instruction_counts_by_case",
        "dependency_chains",
        "issue_and_latency_analysis",
        "occupancy_and_cta_waves",
        "resource_mapping",
    ):
        require(present(instruction.get(field)), f"experiment: instruction_audit.{field} is required", errors)
    accepted = []
    for path in (run / "candidates").rglob("candidate_decision.json"):
        data = read_object(path, errors)
        if evidence_closed_contract(run):
            schema = Path(__file__).resolve().parents[1] / "schemas/candidate_decision.schema.json"
            try:
                errors.extend(
                    f"schema gate {path.relative_to(run)}: {item}"
                    for item in validate_json_file(path, schema)
                )
            except Exception as error:
                errors.append(f"schema gate {path.relative_to(run)}: {error}")
        if data.get("schema_version") == "candidate-decision-v1" and data.get("decision") == "ACCEPT":
            accepted.append(data)
    require(bool(accepted), "experiment: at least one candidate-decision-v1 must be ACCEPT", errors)
    for decision in accepted:
        require(decision.get("correctness", {}).get("status") == "PASS", "experiment: accepted candidate correctness must PASS", errors)
        require(decision.get("instruction_audit", {}).get("status") == "MATCH", "experiment: accepted candidate must reference a MATCH instruction audit", errors)
        global_decision = decision.get("global_schedule_decision", {})
        require(global_decision.get("status") == "ACCEPT", "experiment: accepted candidate requires global scheduler ACCEPT", errors)
        require(global_decision.get("issued_by_role") == "GLOBAL_SCHEDULER", "experiment: candidate global decision must be issued by GLOBAL_SCHEDULER", errors)
        for field in ("resource_balance_revision", "tradeoff_frontier_revision", "weighted_objective_effect"):
            require(present(global_decision.get(field)), f"experiment: candidate global decision missing {field}", errors)
    require(global_state.get("status") == "CANDIDATE_SELECTED", "experiment: global_schedule_state.status must be CANDIDATE_SELECTED", errors)
    require(balance.get("status") in {"CALIBRATED", "VALIDATED"}, "experiment: resource balance must be CALIBRATED or VALIDATED", errors)
    require(frontier.get("status") in {"CALIBRATED", "VALIDATED"}, "experiment: tradeoff frontier must be CALIBRATED or VALIDATED", errors)
    require(queue.get("status") in {"ACTIVE", "CLOSED"}, "experiment: experiment queue must be ACTIVE or CLOSED", errors)
    require_terminal_global_model(balance, queue, errors)
    global_choice = frontier.get("global_decision", {})
    require(global_choice.get("status") == "ACCEPT", "experiment: tradeoff frontier requires a global ACCEPT decision", errors)
    require(present(global_choice.get("selected_schedule")), "experiment: tradeoff frontier must select a schedule", errors)
    require(global_choice.get("issued_by_role") == "GLOBAL_SCHEDULER", "experiment: tradeoff decision must be issued by GLOBAL_SCHEDULER", errors)


def production_gate(run: Path, workload: dict, errors: list[str]) -> None:
    architecture = read_object(run / "models/microarchitecture_model.json", errors)
    production = read_object(run / "models/production_validation.json", errors)
    validation = read_object(run / "models/model_validation.json", errors)
    schedule = read_object(run / "models/schedule_model.json", errors)
    microbench = read_object(run / "models/microbenchmark_plan.json", errors)
    plan = read_object(run / "models/optimization_plan.json", errors)
    global_state, balance, frontier, queue = global_artifacts(run, workload, errors)
    if evidence_closed_contract(run):
        validate_schema_artifacts(run, (("models/production_validation.json", "production_validation.schema.json"),), errors)
        validate_strict_hardware_and_resources(run, architecture, global_state, errors)
        validate_strict_ranking(run, queue, errors)
        validate_strict_p0(run, microbench, errors)
        validate_strict_requests(run, queue, errors)
        validate_strict_resource_rows(run, balance, errors)
    require(architecture.get("status") == "VALIDATED", "production: microarchitecture model must be VALIDATED", errors)
    require(production.get("status") == "PASS", "production: validation status must PASS", errors)
    require(production.get("correctness", {}).get("status") == "PASS", "production: correctness must PASS", errors)
    require(production.get("p4_status") == "PASS", "production: P4 must PASS", errors)
    require(present(production.get("source_and_binary_identities")), "production: source/binary identities are required", errors)
    require(present(production.get("end_to_end_evidence")), "production: end-to-end evidence is required", errors)
    if evidence_closed_contract(run):
        errors.extend(validate_evidence_references(run, production.get("source_and_binary_identities"), "production source/binary identities"))
        errors.extend(validate_evidence_references(run, production.get("end_to_end_evidence"), "production end-to-end evidence"))
    indexed = indexed_cases(production, "production validation", errors)
    require_coverage(indexed, case_ids(workload), "production validation", errors)
    for key, record in indexed.items():
        require(record.get("correctness") == "PASS", f"production {key}: correctness must PASS", errors)
        for field in ("raw_samples", "gpu_active", "end_to_end"):
            require(present(record.get(field)), f"production {key}: missing {field}", errors)
        if evidence_closed_contract(run):
            validate_identity(run, record.get("raw_samples", {}), f"production {key} raw samples", errors, containment_root=run)
        validate_prediction(record, f"production prediction {key}", errors, run)
    require(validation.get("status") in {"PASS", "BOUNDED"}, "production: model validation must PASS or BOUNDED", errors)
    predictions = validation.get("production_predictions", [])
    require(present(predictions), "production: model production predictions are required", errors)
    for index, record in enumerate(predictions if isinstance(predictions, list) else []):
        validate_prediction(record, f"model production prediction {index}", errors, run)
    if validation.get("status") == "BOUNDED":
        require(present(validation.get("bounded_residuals")), "production: BOUNDED model requires bounded_residuals", errors)
    require(schedule.get("status") == "VALIDATED", "production: schedule model must be VALIDATED", errors)
    require(microbench.get("levels", {}).get("P4", {}).get("status") == "PASS", "production: microbenchmark P4 must PASS", errors)
    require(microbench.get("status") == "COMPLETE", "production: microbenchmark plan must be COMPLETE", errors)
    require(plan.get("status") == "COMPLETE", "production: optimization plan must be COMPLETE", errors)
    require(global_state.get("status") == "VALIDATED", "production: global schedule state must be VALIDATED", errors)
    require(balance.get("status") == "VALIDATED", "production: resource balance must be VALIDATED", errors)
    require(frontier.get("status") == "VALIDATED", "production: tradeoff frontier must be VALIDATED", errors)
    require(queue.get("status") == "CLOSED", "production: experiment queue must be CLOSED", errors)
    require(global_state.get("human_report_gate", {}).get("status") == "READY", "production: human report gate must be READY", errors)


def certificate_gate(run: Path, errors: list[str]) -> None:
    certificate = read_object(run / "limit_certificate.json", errors)
    require(certificate.get("schema_version") == "limit-certificate-v2", "certificate: invalid schema_version", errors)
    status = certificate.get("status")
    require(status in {"PROVEN_WITHIN_MODEL", "ARCHITECTURALLY_EXPLAINED"}, "certificate: status must be PROVEN_WITHIN_MODEL or ARCHITECTURALLY_EXPLAINED", errors)
    if status == "ARCHITECTURALLY_EXPLAINED":
        explanation = certificate.get("architecture_explanation", {})
        for field in ("sass_findings", "microarchitecture_findings", "bounded_residuals", "falsification_tests"):
            require(present(explanation.get(field)), f"certificate: architecture_explanation.{field} is required", errors)
    identities = certificate.get("identities", {})
    for name, record in identities.items():
        validate_identity(run, record, f"certificate identity {name}", errors)
    for name, bound in certificate.get("bounds", {}).items():
        if isinstance(bound, dict) and bound.get("identity"):
            validate_identity(run, bound["identity"], f"certificate bound {name}", errors)
    if status == "PROVEN_WITHIN_MODEL":
        proof = certificate.get("proof", {})
        require(proof.get("status") == "PASS", "certificate: proven claim requires proof.status=PASS", errors)
        weighted_lower = weighted_upper = 0.0
        workload = read_object(run / "workload.json", errors)
        weights = {str(case.get("id")): float(case.get("weight", 0.0)) for case in workload.get("cases", [])}
        by_case = {str(case.get("case_id")): case for case in proof.get("cases", [])}
        require(set(by_case) == set(weights), "certificate: proof workload coverage mismatch", errors)
        total_weight = sum(weights.values())
        for case_id, weight in weights.items():
            case = by_case.get(case_id, {})
            components = case.get("lower_components_us", {})
            try:
                lower = max(float(value) for value in components.values())
                upper = min(float(case["production_upper_us"]), float(case["feasible_upper_us"]))
                gap = upper - lower
                require(math.isclose(lower, float(case["proven_lower_us"]), rel_tol=1e-12, abs_tol=1e-12), f"certificate {case_id}: lower formula mismatch", errors)
                require(math.isclose(upper, float(case["proven_upper_us"]), rel_tol=1e-12, abs_tol=1e-12), f"certificate {case_id}: upper formula mismatch", errors)
                require(gap >= 0 and math.isclose(gap, float(case["gap_us"]), rel_tol=1e-12, abs_tol=1e-12), f"certificate {case_id}: gap formula mismatch", errors)
                weighted_lower += weight * lower
                weighted_upper += weight * upper
            except (KeyError, TypeError, ValueError):
                errors.append(f"certificate {case_id}: invalid numeric proof")
        if total_weight > 0:
            weighted_lower /= total_weight
            weighted_upper /= total_weight
            gap = weighted_upper - weighted_lower
            gap_percent = gap / weighted_upper * 100.0 if weighted_upper > 0 else math.inf
            require(math.isclose(weighted_lower, float(proof.get("weighted_lower_us")), rel_tol=1e-12, abs_tol=1e-12), "certificate: weighted lower mismatch", errors)
            require(math.isclose(weighted_upper, float(proof.get("weighted_upper_us")), rel_tol=1e-12, abs_tol=1e-12), "certificate: weighted upper mismatch", errors)
            require(math.isclose(gap_percent, float(proof.get("weighted_gap_percent")), rel_tol=1e-12, abs_tol=1e-12), "certificate: weighted gap mismatch", errors)
            require(gap_percent <= float(proof.get("frozen_tolerance_percent", -1)), "certificate: gap exceeds frozen tolerance", errors)
        require(not certificate.get("missing_evidence"), "certificate: proven claim cannot contain missing evidence", errors)
    project_root = run.parent.parent
    script_dir = Path(__file__).resolve().parent
    audit = subprocess.run(
        [sys.executable, str(script_dir / "audit_repository.py"), "--root", str(project_root)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    require(audit.returncode == 0, f"certificate: repository purity audit failed: {audit.stdout}{audit.stderr}", errors)


# ---------------------------------------------------------------------------
# State transition and command-line entrypoint
# ---------------------------------------------------------------------------


def validate_transition(run: Path, target: str) -> tuple[list[str], dict]:
    errors: list[str] = []
    state = read_object(run / "run_state.json", errors)
    workload = read_object(run / "workload.json", errors)
    validate_framework_contract(run, state, errors)
    current = state.get("current_phase")
    require(current in PHASES, f"run state: invalid current_phase {current!r}", errors)
    if current in PHASES:
        expected_index = PHASES.index(current) + 1
        expected = PHASES[expected_index] if expected_index < len(PHASES) else None
        require(target == expected, f"phase transition must be sequential: {current} -> {expected}, not {target}", errors)
    if target == "BASELINE":
        planning_gate(run, workload, errors)
    elif target == "MODELING":
        baseline_gate(run, workload, errors)
    elif target == "EXPERIMENT":
        modeling_gate(run, workload, errors)
    elif target == "PRODUCTION_VALIDATION":
        experiment_gate(run, workload, errors)
    elif target == "CERTIFICATION":
        production_gate(run, workload, errors)
    elif target == "COMPLETE":
        certificate_gate(run, errors)
    return errors, state


def atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--to", choices=PHASES, required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    run = args.run.resolve()
    errors, state = validate_transition(run, args.to)
    result = {
        "status": "PASS" if not errors else "FAIL",
        "run": str(run),
        "current_phase": state.get("current_phase"),
        "requested_phase": args.to,
        "errors": errors,
    }
    if errors:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    if args.check_only:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    current = state["current_phase"]
    completed = list(state.get("completed_phases", []))
    if current not in completed:
        completed.append(current)
    state["completed_phases"] = completed
    state["current_phase"] = args.to
    index = PHASES.index(args.to)
    state["allowed_next_phase"] = PHASES[index + 1] if index + 1 < len(PHASES) else None
    state["next_action"] = NEXT_ACTIONS[args.to]
    state["terminal"] = args.to == "COMPLETE"
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    atomic_json(run / "run_state.json", state)
    with (run / "decision_log.jsonl").open("a") as stream:
        stream.write(json.dumps({
            "schema_version": "phase-transition-v1",
            "at": state["updated_at"],
            "from": current,
            "to": args.to,
            "gate": "PASS",
        }, sort_keys=True) + "\n")
    result["advanced"] = True
    result["next_action"] = state["next_action"]
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}, sort_keys=True))
        raise SystemExit(1)
