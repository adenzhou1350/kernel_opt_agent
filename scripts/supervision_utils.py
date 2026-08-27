#!/usr/bin/env python3
"""Fail-closed validation for candidate-driven experiment supervision."""

from __future__ import annotations

import json
import math
from pathlib import Path

from evidence_utils import read_object, resolve_evidence_path, sha256, validate_identity
from schema_utils import validate_json_file


SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas"


def artifact_path(run: Path, identity: dict) -> Path:
    return resolve_evidence_path(run, str(identity.get("path", "")))


def validate_admissibility_contract(path: Path, run: Path) -> list[str]:
    errors = [
        f"admissibility contract schema: {item}"
        for item in validate_json_file(path, SCHEMA_ROOT / "candidate_admissibility_contract.schema.json")
    ]
    if errors:
        return errors
    data = read_object(path)
    if data.get("status") != "READY_FOR_SUPERVISOR":
        errors.append("admissibility contract: status must be READY_FOR_SUPERVISOR")
    if data.get("run_id") != run.name:
        errors.append("admissibility contract: run_id mismatch")
    validate_identity(run, data.get("candidate_binding", {}).get("artifact_identity", {}), "admissibility candidate", errors, containment_root=run)
    for index, evidence in enumerate(data.get("evidence", [])):
        validate_identity(run, evidence, f"admissibility evidence {index}", errors, containment_root=run)
    required_gates = {
        "G1_EXACT_PATH_IDENTITY", "G2_SAME_ITERATOR", "G3_BIJECTIVE_MAPPING",
        "G4_SCOREV_FRAGMENT_COMPATIBILITY", "G5_NEGATIVE_CONTROL", "G6_ZERO_DYNAMIC_EXECUTION",
    }
    observed_gates = {str(item.get("gate_id")) for item in data.get("gates", [])}
    if observed_gates != required_gates:
        errors.append(f"admissibility contract: exact G1-G6 gate set required; observed={sorted(observed_gates)}")
    encoded = json.dumps(data, sort_keys=True).lower()
    for forbidden in ("top_two_candidate_ids", "candidate_specific_decision_value", "maximum_decision_value"):
        if forbidden in encoded:
            errors.append(f"admissibility contract: performance-ranking field is forbidden: {forbidden}")
    non_claims = " ".join(map(str, data.get("explicit_non_claims", []))).lower()
    for token in ("latency", "speedup", "top2", "numerical correctness", "k-loop"):
        if token not in non_claims:
            errors.append(f"admissibility contract: explicit non-claim missing token {token!r}")
    outcomes = " ".join(str(item.get("outcome", "")) for item in data.get("outcomes", [])).upper()
    lifecycle = data.get("lifecycle")
    required_outcomes = (
        ("ADMIT", "INVALID")
        if lifecycle == "PASS_ONLY_INVALID"
        else ("ADMIT", "REJECT", "INVALID")
    )
    for token in required_outcomes:
        if token not in outcomes:
            errors.append(f"admissibility contract: outcome set must distinguish {token}")
    if lifecycle == "PASS_ONLY_INVALID" and "REJECT" in outcomes:
        errors.append("admissibility contract: PASS_ONLY_INVALID lifecycle forbids a candidate REJECT outcome")
    return errors


def validate_decision_contract(path: Path, run: Path) -> list[str]:
    errors = [f"decision contract schema: {item}" for item in validate_json_file(path, SCHEMA_ROOT / "decision_contract.schema.json")]
    if errors:
        return errors
    data = read_object(path)
    if data.get("status") != "READY_FOR_SUPERVISOR":
        errors.append("decision contract: status must be READY_FOR_SUPERVISOR")
    candidates = data.get("candidate_bindings", [])
    if not 2 <= len(candidates) <= 4:
        errors.append("decision contract: exactly 2-4 architecture candidates are allowed")
    candidate_ids = [str(item.get("candidate_id")) for item in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        errors.append("decision contract: candidate ids must be unique")
    top_two = list(map(str, data.get("top_two_candidate_ids", [])))
    if len(top_two) != 2 or not set(top_two) <= set(candidate_ids):
        errors.append("decision contract: top_two_candidate_ids must name exactly two bound candidates")
    for index, candidate in enumerate(candidates):
        validate_identity(run, candidate.get("artifact_identity", {}), f"decision candidate {index}", errors, containment_root=run)
        interval = candidate.get("predicted_objective", {})
        if float(interval.get("lower", math.inf)) > float(interval.get("upper", -math.inf)):
            errors.append(f"decision candidate {index}: predicted objective interval is inverted")
        if interval.get("unit") != data.get("decision_metric", {}).get("unit"):
            errors.append(f"decision candidate {index}: predicted objective unit differs from the decision metric")
    for label in ("objective_identity", "frontier_identity"):
        validate_identity(run, data.get(label, {}), f"decision contract {label}", errors, containment_root=run)
    need = data.get("measurement_need", {})
    current = need.get("current_interval", {})
    delta = need.get("top_two_delta_interval", {})
    boundary = need.get("decision_boundary", {})
    try:
        if float(current["lower"]) > float(current["upper"]):
            errors.append("decision contract: measurement current_interval is inverted")
        if float(delta["lower"]) > 0 or float(delta["upper"]) < 0:
            errors.append("decision contract: experiment is forbidden because the top-two delta interval cannot flip their ranking")
        if not float(current["lower"]) <= float(boundary["value"]) <= float(current["upper"]):
            errors.append("decision contract: decision boundary lies outside the unresolved quantity interval")
        quantity_units = {current["unit"], boundary["unit"], need["required_precision"]["unit"]}
        objective_units = {delta["unit"], need["maximum_decision_value"]["unit"], data["decision_metric"]["unit"]}
        if len(quantity_units) != 1:
            errors.append("decision contract: unresolved quantity, boundary and required precision units must agree")
        if len(objective_units) != 1:
            errors.append("decision contract: top-two delta, decision value and objective units must agree")
    except (KeyError, TypeError, ValueError):
        errors.append("decision contract: measurement interval and boundary fields must be finite numeric quantities")
    return errors


def validate_measurability_contract(path: Path, run: Path, decision_path: Path) -> list[str]:
    errors = [f"measurability contract schema: {item}" for item in validate_json_file(path, SCHEMA_ROOT / "measurability_contract.schema.json")]
    if errors:
        return errors
    data = read_object(path)
    decision = read_object(decision_path)
    if data.get("status") != "READY_FOR_SUPERVISOR":
        errors.append("measurability contract: status must be READY_FOR_SUPERVISOR")
    if data.get("decision_contract_identity", {}).get("sha256") != sha256(decision_path):
        errors.append("measurability contract: decision contract hash is stale")
    validate_identity(run, data.get("decision_contract_identity", {}), "measurability decision contract", errors, containment_root=run)
    need = decision.get("measurement_need", {})
    if data.get("quantity_id") != need.get("quantity_id"):
        errors.append("measurability contract: quantity_id differs from the single decision uncertainty")
    method = data.get("selected_method")
    identifiable = data.get("identifiability")
    if identifiable == "NOT_IDENTIFIABLE" and method not in {"CANDIDATE_AB", "NO_MEASUREMENT"}:
        errors.append("measurability contract: a non-identifiable quantity cannot authorize an atomic microbenchmark")
    if method == "ATOMIC_MICROBENCH" and identifiable != "ATOMIC_IDENTIFIABLE":
        errors.append("measurability contract: ATOMIC_MICROBENCH requires ATOMIC_IDENTIFIABLE")
    try:
        expected = float(data["expected_precision"]["absolute"])
        required = float(need["required_precision"]["value"])
        if data["expected_precision"]["unit"] != need["required_precision"]["unit"] or expected > required:
            errors.append("measurability contract: expected precision cannot resolve the registered decision boundary")
    except (KeyError, TypeError, ValueError):
        errors.append("measurability contract: invalid expected/required precision")
    return errors


def validate_experiment_budget(experiment: dict, decision: dict) -> list[str]:
    errors: list[str] = []
    tier = str(experiment.get("experiment_class", "")).lower()
    budget = decision.get("experiment_budget", {}).get(tier, {})
    candidate_ids = {str(item.get("candidate_id")) for item in decision.get("candidate_bindings", [])}
    tested = set(map(str, experiment.get("tested_candidate_ids", [])))
    top_two = set(map(str, decision.get("top_two_candidate_ids", [])))
    if not tested or not tested <= candidate_ids:
        errors.append("experiment budget: tested candidates must be a non-empty subset of the frozen frontier")
    if tier == "qualification" and (len(tested) > 2 or not tested <= top_two):
        errors.append("experiment budget: qualification may test only the frozen top-two candidates")
    declared = experiment.get("execution_budget", {})
    matrix = experiment.get("parameter_matrix", [])
    process_launches = sum(len(experiment.get("commands", {}).get(phase, [])) for phase in (
        "clean_build", "static_audit", "correctness", "warmup", "measure", "analyze"
    ))
    checks = (
        (len(matrix), "max_configurations"),
        (declared.get("samples_per_configuration"), "max_samples_per_configuration"),
        (max(process_launches, int(declared.get("process_launches", 0) or 0)), "max_process_launches"),
        (declared.get("max_wall_clock_minutes"), "max_wall_clock_minutes"),
    )
    for actual, key in checks:
        try:
            if float(actual) <= 0 or float(actual) > float(budget[key]):
                errors.append(f"experiment budget: {key} exceeded or non-positive (actual={actual}, limit={budget.get(key)})")
        except (KeyError, TypeError, ValueError):
            errors.append(f"experiment budget: {key} is missing or invalid")
    return errors


def validate_admissibility_budget(experiment: dict, contract: dict, run: Path) -> list[str]:
    errors: list[str] = []
    budget = contract.get("host_budget", {})
    declared = experiment.get("execution_budget", {})
    matrix = experiment.get("parameter_matrix", [])
    process_launches = sum(len(experiment.get("commands", {}).get(phase, [])) for phase in (
        "clean_build", "static_audit", "correctness", "warmup", "measure", "analyze"
    ))
    checks = (
        (len(matrix), "max_configurations"),
        (declared.get("samples_per_configuration"), "max_samples_per_configuration"),
        (max(process_launches, int(declared.get("process_launches", 0) or 0)), "max_process_launches"),
        (declared.get("max_wall_clock_minutes"), "max_wall_clock_minutes"),
    )
    for actual, key in checks:
        try:
            if float(actual) <= 0 or float(actual) > float(budget[key]):
                errors.append(f"admissibility budget: {key} exceeded or non-positive (actual={actual}, limit={budget.get(key)})")
        except (KeyError, TypeError, ValueError):
            errors.append(f"admissibility budget: {key} is missing or invalid")
    if experiment.get("experiment_class") != "SCREENING":
        errors.append("admissibility budget: static gate must be SCREENING")
    if set(map(str, experiment.get("tested_candidate_ids", []))) != {str(contract.get("candidate_binding", {}).get("candidate_id"))}:
        errors.append("admissibility budget: experiment must test exactly the bound candidate")
    global_cap = read_object(run / "models/optimization_plan.json").get("screening_budget", {})
    for key in ("max_configurations", "max_samples_per_configuration", "max_process_launches", "max_wall_clock_minutes"):
        try:
            if float(budget[key]) > float(global_cap[key]):
                errors.append(f"admissibility budget: contract {key} exceeds the global screening cap")
        except (KeyError, TypeError, ValueError):
            errors.append(f"admissibility budget: invalid global cap for {key}")
    return errors


def validate_global_budget(run: Path, decision: dict) -> list[str]:
    errors: list[str] = []
    plan_path = run / "models/optimization_plan.json"
    if not plan_path.is_file():
        return ["global budget: optimization_plan.json is missing"]
    plan = read_object(plan_path)
    for tier in ("screening", "qualification"):
        proposed = decision.get("experiment_budget", {}).get(tier, {})
        cap = plan.get(f"{tier}_budget", {})
        for key in ("max_configurations", "max_samples_per_configuration", "max_process_launches", "max_wall_clock_minutes"):
            try:
                if float(proposed[key]) > float(cap[key]):
                    errors.append(f"global budget: decision {tier}.{key} exceeds the optimization-plan cap")
            except (KeyError, TypeError, ValueError):
                errors.append(f"global budget: invalid {tier}.{key} cap or decision value")
    try:
        if int(decision.get("experiment_budget", {}).get("max_revisions", -1)) > int(plan.get("max_revisions_per_decision", -1)):
            errors.append("global budget: decision revision count exceeds the optimization-plan cap")
    except (TypeError, ValueError):
        errors.append("global budget: invalid revision cap")
    return errors


def validate_supervisor_approval(path: Path, run: Path, request: dict, experiment_path: Path) -> list[str]:
    if not path.is_file():
        return [f"supervisor approval is missing: {path}"]
    errors = [f"supervisor approval schema: {item}" for item in validate_json_file(path, SCHEMA_ROOT / "supervisor_approval.schema.json")]
    if errors:
        return errors
    approval = read_object(path)
    state = read_object(run / "models/global_schedule_state.json")
    experiment = read_object(experiment_path)
    if approval.get("request_id") != request.get("request_id"):
        errors.append("supervisor approval: request_id mismatch")
    if approval.get("experiment_identity", {}).get("sha256") != sha256(experiment_path):
        errors.append("supervisor approval: experiment changed after approval")
    is_static = experiment.get("experiment_kind") == "STATIC_ADMISSIBILITY"
    expected_action = "DISPATCH_STATIC_ADMISSIBILITY" if is_static else f"DISPATCH_{experiment.get('experiment_class')}"
    if approval.get("action") != expected_action:
        errors.append("supervisor approval: action does not match experiment class")
    supervisor = state.get("supervisor", {})
    if supervisor.get("role") != "GLOBAL_SUPERVISOR" or approval.get("issued_by", {}).get("supervisor_id") != supervisor.get("owner_id"):
        errors.append("supervisor approval: issuer is not the registered GLOBAL_SUPERVISOR")
    identities = (
        {"admissibility_contract_identity": request.get("admissibility_contract", {})}
        if is_static
        else {
            "decision_contract_identity": request.get("decision_contract", {}),
            "measurability_contract_identity": request.get("measurability_contract", {}),
        }
    )
    for field, expected in identities.items():
        observed = approval.get(field, {})
        if observed.get("sha256") != expected.get("sha256"):
            errors.append(f"supervisor approval: {field} differs from the request binding")
        validate_identity(run, observed, f"supervisor approval {field}", errors, containment_root=run)
    if is_static:
        contract_path = artifact_path(run, request.get("admissibility_contract", {}))
        if contract_path.is_file():
            contract = read_object(contract_path)
            errors.extend(validate_admissibility_contract(contract_path, run))
            errors.extend(validate_admissibility_budget(experiment, contract, run))
            expected_budget = {key: value for key, value in contract.get("host_budget", {}).items() if key != "max_revisions"}
            if approval.get("approved_budget") != expected_budget:
                errors.append("supervisor approval: approved budget differs from the frozen admissibility budget")
        else:
            contract = {}
            errors.append("supervisor approval: admissibility contract is missing")
        decision = {}
        measurability = {}
    else:
        decision_path = artifact_path(run, request.get("decision_contract", {}))
        measurability_path = artifact_path(run, request.get("measurability_contract", {}))
        if decision_path.is_file():
            decision = read_object(decision_path)
            if approval.get("frontier_identity", {}).get("sha256") != decision.get("frontier_identity", {}).get("sha256"):
                errors.append("supervisor approval: frontier identity is not the decision-contract frontier")
            if approval.get("objective_identity", {}).get("sha256") != decision.get("objective_identity", {}).get("sha256"):
                errors.append("supervisor approval: objective identity is not the decision-contract objective")
            errors.extend(validate_experiment_budget(experiment, decision))
            errors.extend(validate_global_budget(run, decision))
            expected_budget = decision.get("experiment_budget", {}).get(str(experiment.get("experiment_class", "")).lower(), {})
            if approval.get("approved_budget") != expected_budget:
                errors.append("supervisor approval: approved budget differs from the frozen decision budget")
        else:
            decision = {}
        if measurability_path.is_file():
            measurability = read_object(measurability_path)
            method = measurability.get("selected_method")
            if method == "NO_MEASUREMENT":
                errors.append("supervisor approval: NO_MEASUREMENT cannot authorize execution")
        else:
            measurability = {}
    actors = approval.get("separation_of_duties", {})
    expected_actors = {
        "scheduler_id": (contract if is_static else decision).get("issued_by", {}).get("owner_id"),
        "analyst_id": (contract.get("analysis_owner", {}) if is_static else measurability.get("issued_by", {})).get("analyst_id"),
        "experimenter_id": experiment.get("prepared_by", {}).get("actor_id"),
    }
    for field, expected in expected_actors.items():
        if actors.get(field) != expected:
            errors.append(f"supervisor approval: {field} differs from the bound role artifact")
    actor_ids = [actors.get("scheduler_id"), actors.get("analyst_id"), actors.get("experimenter_id"), supervisor.get("owner_id")]
    if None in actor_ids or len(actor_ids) != len(set(actor_ids)):
        errors.append("supervisor approval: scheduler, analyst, experimenter and supervisor must be distinct actors")
    return errors
