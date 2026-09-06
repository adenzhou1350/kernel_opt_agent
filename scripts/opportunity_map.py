#!/usr/bin/env python3
"""Validate and rank globally material optimization opportunities before coding."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = "opportunity-map-v1"
SCOPES = {"DECOMPOSITION_CONDITIONAL", "CURRENT_SCHEDULE", "EMPIRICAL_BOTTLENECK"}
CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}
ACTIVE_LIFECYCLE_STATUSES = {
    "UNIMPLEMENTED",
    "IMPLEMENTING",
    "OBSERVED",
    "HAS_SURVIVOR",
}
TERMINAL_LIFECYCLE_STATUSES = {"CLOSED"}
LIFECYCLE_STATUSES = ACTIVE_LIFECYCLE_STATUSES | TERMINAL_LIFECYCLE_STATUSES
CLOSURE_DISPOSITIONS = {
    "MEASURED_REJECT",
    "AT_MEASURED_ROOF",
    "BELOW_MATERIALITY_FLOOR",
    "DEPENDENCY_BLOCKED",
}
PRODUCTION_IMPACT_SCOPES = {
    "REPRESENTATIVE_END_TO_END_TRACE",
    "PRODUCTION_TRACE",
    "FROZEN_WORKLOAD_DECOMPOSITION",
}
PRODUCTION_IMPACT_DECISIONS = {
    "CLEARS_MATERIALITY_FLOOR",
    "BELOW_MATERIALITY_FLOOR",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_object(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def map_path(run: Path) -> Path:
    return run / "models" / "opportunity_map.json"


def default_map(args: argparse.Namespace) -> dict:
    if args.min_opportunities < 1 or args.max_opportunities < args.min_opportunities:
        raise ValueError("opportunity bounds are invalid")
    if args.min_rewrite_families < 1:
        raise ValueError("min_rewrite_families must be positive")
    if not 1 <= args.min_candidate_opportunities <= args.min_opportunities:
        raise ValueError("min_candidate_opportunities must be between one and min_opportunities")
    return {
        "schema_version": SCHEMA,
        "status": "DRAFT",
        "created_at": now(),
        "ranked_at": None,
        "policy": {
            "min_opportunities": args.min_opportunities,
            "max_opportunities": args.max_opportunities,
            "min_rewrite_families": args.min_rewrite_families,
            "min_candidate_opportunities": args.min_candidate_opportunities,
            "confidence_weights": {"HIGH": 1.0, "MEDIUM": 0.65, "LOW": 0.35},
            "score_formula": "midpoint(likely_gain_interval_us) * confidence_weight / implementation_budget_minutes",
            "forbidden_claim_scope": "ABSOLUTE_GLOBAL_OPTIMUM",
            "require_production_impact_gate": True,
            "material_speedup_floor": 1.01,
        },
        "opportunities": [],
        "events": [],
    }


def load_map(run: Path) -> dict:
    path = map_path(run)
    if not path.is_file():
        raise ValueError(f"opportunity map is missing; run `kernel_opt.py opportunity init --run {run}`")
    data = read_object(path)
    if data.get("schema_version") != SCHEMA:
        raise ValueError("opportunity map uses an unsupported schema")
    return data


def validate_map(data: dict, *, require_ready: bool = False, run: Path | None = None) -> None:
    if data.get("schema_version") != SCHEMA:
        raise ValueError("opportunity map uses an unsupported schema")
    if data.get("status") not in {"DRAFT", "READY", "PAUSED"}:
        raise ValueError("opportunity map status is invalid")
    policy = data.get("policy")
    opportunities = data.get("opportunities")
    if not isinstance(policy, dict) or not isinstance(opportunities, list):
        raise ValueError("opportunity map policy and opportunities are required")
    required_policy = {
        "min_opportunities", "max_opportunities", "min_rewrite_families",
        "min_candidate_opportunities", "confidence_weights", "score_formula",
        "forbidden_claim_scope",
    }
    if not required_policy <= set(policy):
        raise ValueError("opportunity map policy is incomplete")
    if policy["forbidden_claim_scope"] != "ABSOLUTE_GLOBAL_OPTIMUM":
        raise ValueError("opportunity map must forbid absolute-global-optimum claims")
    try:
        minimum = int(policy["min_opportunities"])
        maximum = int(policy["max_opportunities"])
        minimum_families = int(policy["min_rewrite_families"])
        minimum_candidate_opportunities = int(policy["min_candidate_opportunities"])
        weights = policy["confidence_weights"]
        if set(weights) != CONFIDENCE or any(float(weights[key]) <= 0 for key in CONFIDENCE):
            raise ValueError
    except (TypeError, ValueError, KeyError) as error:
        raise ValueError("opportunity map policy values are invalid") from error
    if not 1 <= minimum <= maximum or not 1 <= minimum_candidate_opportunities <= minimum or minimum_families < 1:
        raise ValueError("opportunity map policy bounds are inconsistent")
    identifiers = []
    require_production_impact_gate = policy.get(
        "require_production_impact_gate", False
    )
    if not isinstance(require_production_impact_gate, bool):
        raise ValueError("require_production_impact_gate must be boolean")
    material_speedup_floor = policy.get("material_speedup_floor")
    if require_production_impact_gate:
        try:
            material_speedup_floor = float(material_speedup_floor)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "material_speedup_floor is required when the production impact gate is enabled"
            ) from error
        if not math.isfinite(material_speedup_floor) or material_speedup_floor <= 1:
            raise ValueError("material_speedup_floor must be finite and greater than one")
    for item in opportunities:
        validate_spec(
            item,
            run,
            require_production_impact_gate=require_production_impact_gate,
            material_speedup_floor=material_speedup_floor,
        )
        if item.get("status") not in LIFECYCLE_STATUSES:
            raise ValueError("opportunity lifecycle status is invalid")
        candidate_ids = item.get("candidate_ids")
        observations = item.get("observations")
        if not isinstance(candidate_ids, list) or len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("opportunity candidate_ids must be a unique array")
        if not isinstance(observations, list):
            raise ValueError("opportunity observations must be an array")
        closure = item.get("closure")
        if item.get("status") == "CLOSED":
            validate_closure(closure, run)
        elif closure is not None:
            raise ValueError("only CLOSED opportunities may carry a closure certificate")
        identifiers.append(item["opportunity_id"])
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("opportunity ids must be unique")
    if len(opportunities) > maximum:
        raise ValueError("opportunity map exceeds max_opportunities")
    if require_ready or data.get("status") == "READY":
        if data.get("status") != "READY":
            raise ValueError("opportunity map is not READY")
        if len(opportunities) < minimum:
            raise ValueError("READY opportunity map is smaller than min_opportunities")
        families = {family for item in opportunities for family in item["rewrite_families"]}
        if len(families) < minimum_families:
            raise ValueError("READY opportunity map lacks rewrite-family diversity")
        expected = sorted(opportunities, key=lambda item: (-score(item, policy), item["opportunity_id"]))
        if [item["opportunity_id"] for item in opportunities] != [item["opportunity_id"] for item in expected]:
            raise ValueError("READY opportunity map is not sorted by the declared score")
        for rank, item in enumerate(opportunities, 1):
            if item.get("priority_rank") != rank:
                raise ValueError("READY opportunity rank is inconsistent")
            if abs(float(item.get("priority_score")) - score(item, policy)) > 1e-12:
                raise ValueError("READY opportunity score is inconsistent")


def validate_spec(
    spec: dict,
    run: Path | None = None,
    *,
    require_production_impact_gate: bool = False,
    material_speedup_floor: float | None = None,
) -> None:
    required = (
        "opportunity_id", "name", "model_scope", "source_model_term", "affected_stages",
        "current_contribution_us", "optimistic_gain_ceiling_us", "likely_gain_interval_us",
        "confidence", "rewrite_families", "implementation_budget_minutes", "hypothesis",
        "derivation", "evidence",
    )
    missing = [field for field in required if spec.get(field) in (None, "", [])]
    if missing:
        raise ValueError(f"opportunity spec is missing fields: {missing}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", str(spec["opportunity_id"])):
        raise ValueError("opportunity_id must use lowercase stable characters")
    if spec["model_scope"] == "ABSOLUTE_GLOBAL_OPTIMUM" or spec["model_scope"] not in SCOPES:
        raise ValueError("absolute-global-optimum claims are forbidden; use a conditional, current-schedule, or empirical scope")
    stages = spec["affected_stages"]
    families = spec["rewrite_families"]
    if not isinstance(stages, list) or not stages or len(stages) != len(set(map(str, stages))):
        raise ValueError("affected_stages must be a non-empty unique array")
    if not isinstance(families, list) or not families or len(families) != len(set(map(str, families))):
        raise ValueError("rewrite_families must be a non-empty unique array")
    if not all(re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(value)) for value in families):
        raise ValueError("rewrite_families must use lowercase kebab-case")
    interval = spec["likely_gain_interval_us"]
    if not isinstance(interval, dict) or set(interval) != {"lower", "upper"}:
        raise ValueError("likely_gain_interval_us must contain exactly lower and upper")
    try:
        contribution = float(spec["current_contribution_us"])
        ceiling = float(spec["optimistic_gain_ceiling_us"])
        lower = float(interval["lower"])
        upper = float(interval["upper"])
        budget = float(spec["implementation_budget_minutes"])
    except (TypeError, ValueError) as error:
        raise ValueError("opportunity costs and gains must be numeric") from error
    if contribution <= 0 or budget <= 0:
        raise ValueError("current contribution and implementation budget must be positive")
    if not 0 <= lower <= upper <= ceiling <= contribution:
        raise ValueError("require 0 <= likely lower <= upper <= optimistic ceiling <= current contribution")
    if spec["confidence"] not in CONFIDENCE:
        raise ValueError("confidence must be HIGH, MEDIUM, or LOW")
    if not isinstance(spec["derivation"], str) or len(spec["derivation"].strip()) < 12:
        raise ValueError("derivation must explain how the numeric ceiling was obtained")
    if not isinstance(spec["evidence"], list) or not spec["evidence"]:
        raise ValueError("evidence must be a non-empty array")
    for index, identity in enumerate(spec["evidence"]):
        if not isinstance(identity, dict) or set(identity) != {"path", "sha256", "claim"}:
            raise ValueError(f"evidence[{index}] must contain exactly path, sha256, and claim")
        if not all(isinstance(identity[field], str) and identity[field] for field in ("path", "sha256", "claim")):
            raise ValueError(f"evidence[{index}] fields must be non-empty strings")
        if not re.fullmatch(r"[0-9a-f]{64}", identity["sha256"]):
            raise ValueError(f"evidence[{index}].sha256 must be lowercase SHA-256")
        if run is not None:
            path = (run / identity["path"]).resolve()
            try:
                path.relative_to(run.resolve())
            except ValueError as error:
                raise ValueError(f"evidence[{index}] escapes the run") from error
            if not path.is_file():
                raise ValueError(f"evidence[{index}] file is missing: {identity['path']}")
            if hashlib.sha256(path.read_bytes()).hexdigest() != identity["sha256"]:
                raise ValueError(f"evidence[{index}] hash mismatch: {identity['path']}")
    gate = spec.get("production_impact_gate")
    if require_production_impact_gate and gate is None:
        raise ValueError(
            "production_impact_gate is required before candidate implementation"
        )
    if gate is not None:
        validate_production_impact_gate(
            spec,
            gate,
            run,
            material_speedup_floor=material_speedup_floor,
        )


def validate_production_impact_gate(
    spec: dict,
    gate: object,
    run: Path | None = None,
    *,
    material_speedup_floor: float | None = None,
) -> None:
    if not isinstance(gate, dict):
        raise ValueError("production_impact_gate must be an object")
    required = {
        "measurement_scope",
        "baseline_end_to_end_us",
        "target_component_us",
        "candidate_component_speedup_ceiling",
        "derived_amdahl_speedup_ceiling",
        "material_speedup_floor",
        "decision",
        "derivation",
        "evidence",
    }
    if set(gate) != required:
        raise ValueError(
            "production_impact_gate fields are incomplete or contain unknown values"
        )
    if gate["measurement_scope"] not in PRODUCTION_IMPACT_SCOPES:
        raise ValueError("production_impact_gate measurement_scope is invalid")
    if gate["decision"] not in PRODUCTION_IMPACT_DECISIONS:
        raise ValueError("production_impact_gate decision is invalid")
    try:
        baseline = float(gate["baseline_end_to_end_us"])
        component = float(gate["target_component_us"])
        component_speedup = float(gate["candidate_component_speedup_ceiling"])
        declared_amdahl = float(gate["derived_amdahl_speedup_ceiling"])
        material_floor = float(gate["material_speedup_floor"])
    except (TypeError, ValueError) as error:
        raise ValueError("production_impact_gate numeric fields are invalid") from error
    numbers = (baseline, component, component_speedup, declared_amdahl, material_floor)
    if not all(math.isfinite(value) for value in numbers):
        raise ValueError("production_impact_gate values must be finite")
    if baseline <= 0 or not 0 < component <= baseline:
        raise ValueError(
            "production_impact_gate requires 0 < target_component_us <= baseline_end_to_end_us"
        )
    if component_speedup < 1 or declared_amdahl < 1 or material_floor <= 1:
        raise ValueError(
            "production_impact_gate speedup ceilings must be >= 1 and the material floor must be > 1"
        )
    if material_speedup_floor is not None and not math.isclose(
        material_floor,
        float(material_speedup_floor),
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        raise ValueError(
            "production_impact_gate material_speedup_floor must match the frozen map policy"
        )
    contribution = float(spec["current_contribution_us"])
    if not math.isclose(component, contribution, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError(
            "production_impact_gate target_component_us must equal current_contribution_us"
        )
    share = component / baseline
    expected_amdahl = 1.0 / ((1.0 - share) + share / component_speedup)
    if not math.isclose(declared_amdahl, expected_amdahl, rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError(
            "derived_amdahl_speedup_ceiling does not match the measured production share"
        )
    removable_us = component * (1.0 - 1.0 / component_speedup)
    if float(spec["optimistic_gain_ceiling_us"]) > removable_us + 1e-9:
        raise ValueError(
            "optimistic_gain_ceiling_us exceeds the production-impact removable-work ceiling"
        )
    expected_decision = (
        "CLEARS_MATERIALITY_FLOOR"
        if expected_amdahl >= material_floor
        else "BELOW_MATERIALITY_FLOOR"
    )
    if gate["decision"] != expected_decision:
        raise ValueError(
            "production_impact_gate decision disagrees with its Amdahl ceiling and materiality floor"
        )
    if gate["decision"] != "CLEARS_MATERIALITY_FLOOR":
        raise ValueError(
            "opportunity is below the production materiality floor; do not implement a candidate"
        )
    if not isinstance(gate["derivation"], str) or len(gate["derivation"].strip()) < 12:
        raise ValueError("production_impact_gate derivation must explain the measured share")
    evidence = gate["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("production_impact_gate evidence must be a non-empty array")
    for index, identity in enumerate(evidence):
        if not isinstance(identity, dict) or set(identity) != {"path", "sha256", "claim"}:
            raise ValueError(
                f"production_impact_gate evidence[{index}] must contain exactly path, sha256, and claim"
            )
        if not all(
            isinstance(identity.get(field), str) and identity[field]
            for field in ("path", "sha256", "claim")
        ):
            raise ValueError(
                f"production_impact_gate evidence[{index}] fields must be non-empty strings"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", identity["sha256"]):
            raise ValueError(
                f"production_impact_gate evidence[{index}].sha256 must be lowercase SHA-256"
            )
        if run is not None:
            path = (run / identity["path"]).resolve()
            try:
                path.relative_to(run.resolve())
            except ValueError as error:
                raise ValueError(
                    f"production_impact_gate evidence[{index}] escapes the run"
                ) from error
            if not path.is_file():
                raise ValueError(
                    f"production_impact_gate evidence[{index}] file is missing: {identity['path']}"
                )
            if hashlib.sha256(path.read_bytes()).hexdigest() != identity["sha256"]:
                raise ValueError(
                    f"production_impact_gate evidence[{index}] hash mismatch: {identity['path']}"
                )


def validate_closure(closure: object, run: Path | None = None) -> None:
    if not isinstance(closure, dict):
        raise ValueError("CLOSED opportunity requires a closure certificate")
    if set(closure) != {
        "disposition",
        "reason",
        "evidence",
        "reopen_conditions",
        "closed_at",
    }:
        raise ValueError("closure certificate fields are invalid")
    if closure["disposition"] not in CLOSURE_DISPOSITIONS:
        raise ValueError("closure disposition is invalid")
    if not isinstance(closure["reason"], str) or len(closure["reason"].strip()) < 12:
        raise ValueError("closure reason must explain the global stop decision")
    conditions = closure["reopen_conditions"]
    if (
        not isinstance(conditions, list)
        or not conditions
        or not all(isinstance(item, str) and item.strip() for item in conditions)
    ):
        raise ValueError("closure requires one or more explicit reopen conditions")
    if not isinstance(closure["closed_at"], str) or not closure["closed_at"]:
        raise ValueError("closure closed_at is required")
    identity = closure["evidence"]
    if not isinstance(identity, dict) or set(identity) != {"path", "sha256", "claim"}:
        raise ValueError("closure evidence must contain exactly path, sha256, and claim")
    if not all(
        isinstance(identity.get(field), str) and identity[field]
        for field in ("path", "sha256", "claim")
    ):
        raise ValueError("closure evidence fields must be non-empty strings")
    if not re.fullmatch(r"[0-9a-f]{64}", identity["sha256"]):
        raise ValueError("closure evidence sha256 must be lowercase SHA-256")
    if run is not None:
        path = (run / identity["path"]).resolve()
        try:
            path.relative_to(run.resolve())
        except ValueError as error:
            raise ValueError("closure evidence escapes the run") from error
        if not path.is_file():
            raise ValueError(f"closure evidence file is missing: {identity['path']}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != identity["sha256"]:
            raise ValueError(f"closure evidence hash mismatch: {identity['path']}")


def score(item: dict, policy: dict) -> float:
    if item.get("status") == "CLOSED":
        return 0.0
    interval = item["likely_gain_interval_us"]
    midpoint = (float(interval["lower"]) + float(interval["upper"])) / 2.0
    weight = float(policy["confidence_weights"][item["confidence"]])
    return midpoint * weight / float(item["implementation_budget_minutes"])


def command_init(args: argparse.Namespace) -> dict:
    run = args.run.resolve()
    path = map_path(run)
    if path.exists() and not args.if_missing:
        raise FileExistsError(f"opportunity map already exists: {path}")
    if path.exists():
        return read_object(path)
    data = default_map(args)
    atomic_json(path, data)
    return data


def command_add(args: argparse.Namespace) -> dict:
    run = args.run.resolve()
    data = load_map(run)
    spec = read_object(args.spec.resolve())
    validate_spec(
        spec,
        run,
        require_production_impact_gate=data["policy"].get(
            "require_production_impact_gate", False
        ),
        material_speedup_floor=data["policy"].get("material_speedup_floor"),
    )
    if data.get("status") == "PAUSED":
        raise ValueError("opportunity map is paused")
    if any(item.get("opportunity_id") == spec["opportunity_id"] for item in data["opportunities"]):
        raise ValueError(f"duplicate opportunity_id: {spec['opportunity_id']}")
    if len(data["opportunities"]) >= int(data["policy"]["max_opportunities"]):
        raise ValueError("opportunity map maximum is reached")
    item = dict(spec)
    item.update({
        "status": "UNIMPLEMENTED",
        "priority_rank": None,
        "priority_score": None,
        "candidate_ids": [],
        "observations": [],
        "created_at": now(),
    })
    data["opportunities"].append(item)
    data["status"] = "DRAFT"
    data["ranked_at"] = None
    data["events"].append({"at": now(), "event": "ADDED", "opportunity_id": item["opportunity_id"]})
    atomic_json(map_path(run), data)
    return item


def command_rank(args: argparse.Namespace) -> dict:
    run = args.run.resolve()
    data = load_map(run)
    opportunities = data["opportunities"]
    policy = data["policy"]
    if len(opportunities) < int(policy["min_opportunities"]):
        raise ValueError("opportunity map is smaller than min_opportunities")
    families = {family for item in opportunities for family in item["rewrite_families"]}
    if len(families) < int(policy["min_rewrite_families"]):
        raise ValueError("opportunity map lacks the required rewrite-family diversity")
    for item in opportunities:
        validate_spec(
            item,
            run,
            require_production_impact_gate=policy.get(
                "require_production_impact_gate", False
            ),
            material_speedup_floor=policy.get("material_speedup_floor"),
        )
        item["priority_score"] = score(item, policy)
    opportunities.sort(key=lambda item: (-float(item["priority_score"]), item["opportunity_id"]))
    for rank, item in enumerate(opportunities, 1):
        item["priority_rank"] = rank
    data["status"] = "READY"
    data["ranked_at"] = now()
    data["events"].append({"at": now(), "event": "RANKED", "order": [item["opportunity_id"] for item in opportunities]})
    validate_map(data, require_ready=True, run=run)
    atomic_json(map_path(run), data)
    return command_status(args)


def command_close(args: argparse.Namespace) -> dict:
    run = args.run.resolve()
    data = load_map(run)
    validate_map(data, require_ready=True, run=run)
    opportunity = next(
        (
            item
            for item in data["opportunities"]
            if item["opportunity_id"] == args.opportunity_id
        ),
        None,
    )
    if opportunity is None:
        raise ValueError(f"unknown opportunity_id: {args.opportunity_id}")
    if opportunity.get("status") == "CLOSED":
        raise ValueError("opportunity is already CLOSED")
    evidence = args.evidence.resolve()
    try:
        relative_evidence = evidence.relative_to(run)
    except ValueError as error:
        raise ValueError("closure evidence must live inside the run") from error
    if not evidence.is_file():
        raise ValueError(f"closure evidence is missing: {evidence}")
    opportunity["status"] = "CLOSED"
    opportunity["closure"] = {
        "disposition": args.disposition,
        "reason": args.reason,
        "evidence": {
            "path": relative_evidence.as_posix(),
            "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            "claim": args.evidence_claim,
        },
        "reopen_conditions": args.reopen_condition,
        "closed_at": now(),
    }
    data["events"].append(
        {
            "at": now(),
            "event": "CLOSED",
            "opportunity_id": args.opportunity_id,
            "disposition": args.disposition,
        }
    )
    command_rank_in_place(data, run)
    atomic_json(map_path(run), data)
    return opportunity


def command_reopen(args: argparse.Namespace) -> dict:
    run = args.run.resolve()
    data = load_map(run)
    validate_map(data, require_ready=True, run=run)
    opportunity = next(
        (
            item
            for item in data["opportunities"]
            if item["opportunity_id"] == args.opportunity_id
        ),
        None,
    )
    if opportunity is None:
        raise ValueError(f"unknown opportunity_id: {args.opportunity_id}")
    if opportunity.get("status") != "CLOSED":
        raise ValueError("only a CLOSED opportunity can be reopened")
    previous = opportunity.pop("closure")
    opportunity["status"] = (
        "OBSERVED"
        if opportunity.get("candidate_ids") or opportunity.get("observations")
        else "UNIMPLEMENTED"
    )
    opportunity.setdefault("observations", []).append(
        f"Reopened because: {args.reason}"
    )
    data["events"].append(
        {
            "at": now(),
            "event": "REOPENED",
            "opportunity_id": args.opportunity_id,
            "reason": args.reason,
            "previous_disposition": previous["disposition"],
        }
    )
    command_rank_in_place(data, run)
    atomic_json(map_path(run), data)
    return opportunity


def command_rank_in_place(data: dict, run: Path) -> None:
    policy = data["policy"]
    for item in data["opportunities"]:
        validate_spec(
            item,
            run,
            require_production_impact_gate=policy.get(
                "require_production_impact_gate", False
            ),
            material_speedup_floor=policy.get("material_speedup_floor"),
        )
        item["priority_score"] = score(item, policy)
    data["opportunities"].sort(
        key=lambda item: (-float(item["priority_score"]), item["opportunity_id"])
    )
    for rank, item in enumerate(data["opportunities"], 1):
        item["priority_rank"] = rank
    data["status"] = "READY"
    data["ranked_at"] = now()
    validate_map(data, require_ready=True, run=run)


def command_status(args: argparse.Namespace) -> dict:
    data = load_map(args.run.resolve())
    return {
        "status": data["status"],
        "opportunity_count": len(data["opportunities"]),
        "active_opportunity_count": sum(
            item.get("status") != "CLOSED" for item in data["opportunities"]
        ),
        "rewrite_family_count": len({family for item in data["opportunities"] for family in item.get("rewrite_families", [])}),
        "opportunities": [{
            "opportunity_id": item["opportunity_id"],
            "priority_rank": item.get("priority_rank"),
            "priority_score": item.get("priority_score"),
            "optimistic_gain_ceiling_us": item["optimistic_gain_ceiling_us"],
            "candidate_count": len(item.get("candidate_ids", [])),
            "status": item.get("status"),
            "closure": item.get("closure"),
        } for item in data["opportunities"]],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    init = subparsers.add_parser("init", help="initialize an opportunity map")
    init.add_argument("--run", type=Path, required=True)
    init.add_argument("--min-opportunities", type=int, default=4)
    init.add_argument("--max-opportunities", type=int, default=12)
    init.add_argument("--min-rewrite-families", type=int, default=4)
    init.add_argument("--min-candidate-opportunities", type=int, default=3)
    init.add_argument("--if-missing", action="store_true")
    add = subparsers.add_parser("add", help="validate and add one quantified opportunity")
    add.add_argument("--run", type=Path, required=True)
    add.add_argument("--spec", type=Path, required=True)
    rank = subparsers.add_parser("rank", help="rank opportunities by expected global gain per implementation minute")
    rank.add_argument("--run", type=Path, required=True)
    close = subparsers.add_parser("close", help="close a measured dead end with hash-bound evidence and explicit reopen conditions")
    close.add_argument("--run", type=Path, required=True)
    close.add_argument("--opportunity-id", required=True)
    close.add_argument("--disposition", choices=sorted(CLOSURE_DISPOSITIONS), required=True)
    close.add_argument("--reason", required=True)
    close.add_argument("--evidence", type=Path, required=True)
    close.add_argument("--evidence-claim", required=True)
    close.add_argument("--reopen-condition", action="append", required=True)
    reopen = subparsers.add_parser("reopen", help="reopen a closed opportunity after a recorded condition changes")
    reopen.add_argument("--run", type=Path, required=True)
    reopen.add_argument("--opportunity-id", required=True)
    reopen.add_argument("--reason", required=True)
    status = subparsers.add_parser("status", help="show ranked opportunities and candidate coverage")
    status.add_argument("--run", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    handlers = {
        "init": command_init,
        "add": command_add,
        "rank": command_rank,
        "close": command_close,
        "reopen": command_reopen,
        "status": command_status,
    }
    try:
        result = handlers[args.operation](args)
    except Exception as error:
        print(f"ERROR: {error}", file=__import__("sys").stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
