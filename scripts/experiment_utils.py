#!/usr/bin/env python3
"""Shared experiment materialization, catalog matching and result validation."""

from __future__ import annotations

import json
from pathlib import Path

from evidence_utils import path_is_within, read_object, resolve_evidence_path, sha256, validate_identity, validate_p0_receipt
from schema_utils import validate_json_file


QUALIFICATION = {
    "DRAFT": 0,
    "STATIC_VALIDATED": 1,
    "MECHANISM_VALIDATED": 2,
    "DEVICE_CALIBRATED": 3,
    "PRODUCTION_PREDICTIVE": 4,
}


def catalog_matches(catalog: dict, query: dict) -> list[dict]:
    resources = set(map(str, query.get("resources", [])))
    mechanisms = set(map(str, query.get("mechanisms", [])))
    boundaries = set(map(str, query.get("boundaries", [])))
    required = QUALIFICATION.get(str(query.get("qualification", "DRAFT")), 0)
    matches = []
    for entry in catalog.get("benchmarks", []):
        capabilities = entry.get("capabilities", {})
        if not resources <= set(map(str, capabilities.get("resources", []))):
            continue
        if not mechanisms <= set(map(str, capabilities.get("mechanisms", []))):
            continue
        if not boundaries <= set(map(str, capabilities.get("boundaries", []))):
            continue
        highest = entry.get("qualification", {}).get("highest_status", "DRAFT")
        if QUALIFICATION.get(str(highest), -1) < required:
            continue
        matches.append(entry)
    return matches


def validate_catalog_receipt(receipt_path: Path, catalog_path: Path, query: dict) -> list[str]:
    errors: list[str] = []
    if not receipt_path.is_file():
        return [f"catalog query receipt is missing: {receipt_path}"]
    receipt = read_object(receipt_path)
    if receipt.get("schema_version") != "catalog-query-receipt-v1":
        errors.append("catalog receipt: invalid schema_version")
    identity = receipt.get("catalog_identity", {})
    if identity.get("sha256") != sha256(catalog_path):
        errors.append("catalog receipt: catalog hash does not match current immutable snapshot")
    if receipt.get("query") != query:
        errors.append("catalog receipt: query does not match experiment request")
    expected = [entry.get("id") for entry in catalog_matches(read_object(catalog_path), query)]
    if receipt.get("matching_package_ids") != expected:
        errors.append("catalog receipt: matching packages were not produced by the deterministic matcher")
    return errors


def validate_materialized_experiment(path: Path, run: Path) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        return [f"materialized experiment is missing: {path}"]
    data = read_object(path)
    if data.get("schema_version") != "executable-experiment-v1":
        errors.append("experiment: invalid schema_version")
    if data.get("status") != "MATERIALIZED":
        errors.append("experiment: status must be MATERIALIZED before dispatch")
    schema = Path(__file__).resolve().parents[1] / "schemas/executable_experiment.schema.json"
    errors.extend(f"experiment schema: {item}" for item in validate_json_file(path, schema))
    commands = data.get("commands", {})
    for name in ("clean_build", "static_audit", "correctness", "warmup", "measure", "analyze"):
        if not isinstance(commands.get(name), list) or not commands[name] or not all(
            isinstance(item, list) and item and all(isinstance(argument, str) and argument for argument in item)
            for item in commands[name]
        ):
            errors.append(f"experiment: commands.{name} must be a non-empty argv-list collection")
    if not data.get("parameter_matrix"):
        errors.append("experiment: parameter_matrix must not be empty")
    if data.get("experiment_class") not in {"SCREENING", "QUALIFICATION"}:
        errors.append("experiment: experiment_class must be SCREENING or QUALIFICATION")
    if not data.get("tested_candidate_ids"):
        errors.append("experiment: tested_candidate_ids must not be empty")
    prepared = data.get("prepared_by", {})
    if prepared.get("role") != "EXPERIMENT_AGENT" or not prepared.get("actor_id"):
        errors.append("experiment: prepared_by must identify the EXPERIMENT_AGENT")
    identity_fields = (
        ("admissibility_contract_identity",)
        if data.get("experiment_kind") == "STATIC_ADMISSIBILITY"
        else ("decision_contract_identity", "measurability_contract_identity")
    )
    for field in identity_fields:
        validate_identity(run, data.get(field, {}), f"experiment {field}", errors, containment_root=run)
    if data.get("experiment_kind") == "STATIC_ADMISSIBILITY":
        measurement = data.get("measurement_contract", {})
        if measurement.get("timer") != "none_compiler_typecheck" or measurement.get("unit") != "binary_pass":
            errors.append("experiment: static-admissibility measurement must be untimed binary_pass")
        if measurement.get("gpu_launches") != 0 or measurement.get("performance_samples") != 0:
            errors.append("experiment: static-admissibility forbids GPU launches and performance samples")
        if len(data.get("parameter_matrix", [])) != 2:
            errors.append("experiment: static-admissibility requires exactly short and long configurations")
    controls = " ".join(map(str, data.get("controls", []))).lower()
    for token in ("zero", "positive", "negative", "live"):
        if token not in controls:
            errors.append(f"experiment: controls must contain a {token} control")
    if not data.get("expected_sass"):
        errors.append("experiment: expected_sass must not be empty")
    source = data.get("source", {})
    identities = source.get("identities", [])
    if not identities:
        errors.append("experiment: immutable source identities are required")
    for index, identity in enumerate(identities):
        validate_identity(run, identity, f"experiment source {index}", errors)
    contract = data.get("model_update_contract", {})
    for field in ("model_field", "summary_fields", "decision_changed"):
        if not contract.get(field):
            errors.append(f"experiment: model_update_contract.{field} is required")
    for field in ("raw_samples", "result", "static_audit", "reproduction_log"):
        value = data.get("artifacts", {}).get(field)
        if not value:
            errors.append(f"experiment: artifacts.{field} is required")
        else:
            resolved = resolve_evidence_path(run, str(value))
            if not path_is_within(resolved, run):
                errors.append(f"experiment: artifacts.{field} escapes the run directory")
    return errors


def validate_execution_receipt(path: Path, run: Path, experiment_path: Path, request_id: str) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        return [f"experiment execution receipt is missing: {path}"]
    schema = Path(__file__).resolve().parents[1] / "schemas/experiment_execution_receipt.schema.json"
    errors.extend(f"execution receipt schema: {item}" for item in validate_json_file(path, schema))
    data = read_object(path)
    experiment = read_object(experiment_path)
    if data.get("schema_version") != "experiment-execution-receipt-v1" or data.get("status") != "PASS":
        errors.append("execution receipt: schema/status must record PASS")
    if data.get("request_id") != request_id:
        errors.append("execution receipt: request_id mismatch")
    expected_identities = {
        "experiment_identity": experiment_path,
        "hardware_identity": run / "hardware.json",
        "workload_identity": run / "workload.json",
    }
    for field, expected_path in expected_identities.items():
        identity = data.get(field, {})
        if identity.get("sha256") != sha256(expected_path):
            errors.append(f"execution receipt: {field} hash mismatch")
    expected_commands = [
        (phase, index, argv)
        for phase in ("clean_build", "static_audit", "correctness", "warmup", "measure", "analyze")
        for index, argv in enumerate(experiment.get("commands", {}).get(phase, []))
    ]
    observed_commands = data.get("commands", [])
    if len(observed_commands) != len(expected_commands):
        errors.append("execution receipt: command count does not match experiment contract")
    for expected, observed in zip(expected_commands, observed_commands):
        phase, index, argv = expected
        if (observed.get("phase"), observed.get("index"), observed.get("argv")) != (phase, index, argv):
            errors.append(f"execution receipt: command order/argv mismatch at {phase}[{index}]")
        if observed.get("exit_code") != 0:
            errors.append(f"execution receipt: command failed at {phase}[{index}]")
        for stream in ("stdout", "stderr"):
            validate_identity(run, observed.get(stream, {}), f"execution receipt {phase}[{index}] {stream}", errors, containment_root=run)
        for input_index, identity in enumerate(observed.get("input_identities", [])):
            validate_identity(run, identity, f"execution receipt {phase}[{index}] input {input_index}", errors)
    artifacts = data.get("artifacts", {})
    for name in ("raw_samples", "result", "static_audit", "reproduction_log"):
        validate_identity(run, artifacts.get(name, {}), f"execution receipt artifact {name}", errors, containment_root=run)
        expected = resolve_evidence_path(run, str(experiment.get("artifacts", {}).get(name, "")))
        observed = resolve_evidence_path(run, str(artifacts.get(name, {}).get("path", "")))
        if expected != observed:
            errors.append(f"execution receipt: artifact path mismatch for {name}")
    return errors


def validate_benchmark_result(
    path: Path,
    run: Path,
    *,
    request_id: str | None = None,
    experiment_path: Path | None = None,
) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        return [f"benchmark result is missing: {path}"]
    data = read_object(path)
    if data.get("schema_version") != "benchmark-result-v2":
        errors.append("benchmark result: invalid schema_version")
    if request_id is not None and data.get("request_id") != request_id:
        errors.append("benchmark result: request_id does not match the queued experiment")
    if experiment_path is not None and data.get("experiment_identity", {}).get("sha256") != sha256(experiment_path):
        errors.append("benchmark result: experiment identity mismatch")
    for field, expected in (("hardware_identity", run / "hardware.json"), ("workload_identity", run / "workload.json")):
        if data.get(field, {}).get("sha256") != sha256(expected):
            errors.append(f"benchmark result: {field} mismatch")
    if data.get("validity", {}).get("status") != "VALID":
        errors.append("benchmark result: validity must be VALID")
    if data.get("correctness", {}).get("status") != "PASS":
        errors.append("benchmark result: correctness must PASS")
    measurement = data.get("measurement", {})
    is_compiler_predicate = (
        measurement.get("timer") == "none_compiler_typecheck"
        and measurement.get("unit") == "binary_pass"
    )
    minimum_samples = 1 if is_compiler_predicate else 9
    if not isinstance(data.get("raw_samples"), list) or len(data["raw_samples"]) < minimum_samples:
        errors.append(f"benchmark result: at least {minimum_samples} raw samples are required")
    for field in ("metric", "semantics", "unit", "timer"):
        if not data.get("measurement", {}).get(field):
            errors.append(f"benchmark result: measurement.{field} is required")
    for field in ("binary_identity", "sass_identity", "static_audit_identity", "resource_usage"):
        if not data.get("static_evidence", {}).get(field):
            errors.append(f"benchmark result: static_evidence.{field} is required")
    for label, identity in (
        ("source identity", data.get("source_identity", {})),
        ("binary identity", data.get("static_evidence", {}).get("binary_identity", {})),
        ("SASS identity", data.get("static_evidence", {}).get("sass_identity", {})),
        ("static audit identity", data.get("static_evidence", {}).get("static_audit_identity", {})),
        ("raw sample identity", data.get("raw_samples_identity", {})),
        ("correctness identity", data.get("correctness", {}).get("evidence_identity", {})),
        ("P0 receipt", data.get("measurement_system", {}).get("p0_receipt", {})),
    ):
        validate_identity(run, identity, f"benchmark result {label}", errors, containment_root=run)
    raw_path = resolve_evidence_path(run, str(data.get("raw_samples_identity", {}).get("path", "")))
    if raw_path.is_file():
        raw = read_object(raw_path)
        if raw.get("samples") != data.get("raw_samples"):
            errors.append("benchmark result: inline samples do not match immutable raw sample artifact")
    if data.get("correctness", {}).get("status") == "PASS" and not data.get("correctness", {}).get("checks"):
        errors.append("benchmark result: correctness PASS requires explicit checks")
    p0_path = resolve_evidence_path(run, str(data.get("measurement_system", {}).get("p0_receipt", {}).get("path", "")))
    if p0_path.is_file():
        errors.extend(validate_p0_receipt(p0_path, run))
    return errors
