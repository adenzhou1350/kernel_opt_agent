#!/usr/bin/env python3
"""Materialize and score leakage-resistant community-knowledge A/B trials."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from statistics import median

from community_knowledge import (
    atomic_json,
    now,
    read_object,
    sha256_file,
    validate_corpus,
    validate_graph,
)
from schema_utils import validate_instance, validate_json_file


SUITE_SCHEMA = "community-temporal-suite-v1"
TRIAL_SCHEMA = "community-evaluation-trial-v1"
RESULT_SCHEMA = "community-trial-result-v1"
ASSESSMENT_SCHEMA = "community-trial-assessment-v1"
REPORT_SCHEMA = "community-ab-report-v1"
REPEAT_SUMMARY_SCHEMA = "community-ab-repeat-summary-v1"
SCHEDULE_SCHEMA = "community-evaluation-schedule-v1"
SOURCE_RECEIPT_SCHEMA = "community-trial-source-receipt-v1"
EXECUTION_AUDIT_SCHEMA = "community-trial-execution-audit-v1"
SUITE_RUN_SUMMARY_SCHEMA = "community-suite-run-summary-v1"
TASK_PACKET_AUDIT_SCHEMA = "community-task-packet-audit-v1"
PRIOR_SHORTLIST_SCHEMA = "community-prior-shortlist-v1"
FRONTIER_CONTRACT_SCHEMA = "community-frontier-contract-v1"
HELDOUT_QUEUE_SCHEMA = "community-heldout-queue-v1"
FEASIBILITY_SCREEN_SCHEMA = "community-feasibility-screen-v1"
PRESELECTION_ANCHOR_SCHEMA = "community-preselection-anchor-v1"
PRESELECTION_CHAIN_AUDIT_SCHEMA = "community-preselection-chain-audit-v1"
META_ANALYSIS_SCHEMA = "community-ab-meta-analysis-v1"
PRIOR_OUTCOME_LEDGER_SCHEMA = "community-prior-outcome-ledger-v1"
PRIOR_CONTEXT_DISTINCTION_SCHEMA = "community-prior-context-distinction-v1"
PRIOR_ROUTING_SNAPSHOT_SCHEMA = "community-prior-routing-snapshot-v1"
ARMS = ("CONTROL", "COMMUNITY_AUGMENTED")
METRICS = {
    "TIME_TO_FIRST_CORRECT",
    "TIME_TO_FIRST_IMPROVEMENT",
    "BEST_SPEEDUP",
    "ARCHITECTURE_FAMILY_COVERAGE",
    "HELDOUT_CORRECTNESS",
    "WHOLE_MODEL_SPEEDUP",
    "UPSTREAM_READINESS",
}

PRIOR_STOPWORDS = {
    "and", "the", "with", "from", "into", "while", "where", "that", "this",
    "same", "must", "under", "without", "input", "output", "historical", "path",
    "tensor", "tensors", "runtime", "single", "device", "candidate", "baseline",
}


def prior_tokens(value: object) -> set[str]:
    text = prior_scalar_text(value)
    return {
        token for token in re.findall(r"[a-z][a-z0-9_+-]{2,}", text)
        if token not in PRIOR_STOPWORDS
    }


def prior_scalar_text(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(prior_scalar_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(prior_scalar_text(item) for item in value)
    return str(value).lower()


def target_compute_capability(environment: dict) -> str | None:
    target = environment.get("target", environment)
    value = target.get("compute_capability") if isinstance(target, dict) else None
    if isinstance(value, list) and len(value) == 2:
        return f"{value[0]}.{value[1]}"
    match = re.search(r"sm\s*([0-9])([0-9])", json.dumps(environment).lower())
    return f"{match.group(1)}.{match.group(2)}" if match else None


def prior_term_in_text(term: str, text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", term.lower()).strip()
    if not normalized:
        return False
    pattern = r"(?<![a-z0-9])" + r"\s+".join(
        re.escape(part) for part in normalized.split()
    ) + r"(?![a-z0-9])"
    normalized_text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.search(pattern, normalized_text) is not None


def prior_outcome_maps(
    prior_outcomes: dict | None,
    context_distinction: dict | None,
) -> tuple[dict[tuple[str, str], dict], set[tuple[str, str]]]:
    aggregates = {
        (row["prior_kind"], row["prior_id"]): row
        for row in (prior_outcomes or {}).get("aggregates", [])
    }
    exceptions = {
        (row["prior_kind"], row["prior_id"])
        for row in (context_distinction or {}).get("exceptions", [])
    }
    return aggregates, exceptions


def apply_prior_outcome(
    prior_kind: str,
    prior_id: str,
    base_score: float,
    aggregates: dict[tuple[str, str], dict],
    exceptions: set[tuple[str, str]],
) -> tuple[float | None, dict]:
    aggregate = aggregates.get((prior_kind, prior_id))
    if aggregate is None:
        return base_score, {
            "routing_adjustment": "NO_EVIDENCE",
            "score_delta": 0.0,
            "observation_count": 0,
            "task_count": 0,
            "heldout_loss_count": 0,
            "context_distinction_applied": False,
        }
    adjustment = aggregate["routing_adjustment"]
    exception_applied = (
        adjustment == "REQUIRE_CONTEXT_GUARD"
        and (prior_kind, prior_id) in exceptions
    )
    # Keep task relevance primary: outcome feedback moves a prior by only one
    # lexical-match equivalent rather than overriding the local diagnosis.
    delta = {"UPRANK": 1.0, "DOWNRANK": -1.0}.get(adjustment, 0.0)
    outcome = {
        "routing_adjustment": adjustment,
        "score_delta": delta,
        "observation_count": aggregate["observation_count"],
        "task_count": aggregate["task_count"],
        "heldout_loss_count": aggregate["heldout_loss_count"],
        "context_distinction_applied": exception_applied,
    }
    if adjustment == "REQUIRE_CONTEXT_GUARD" and not exception_applied:
        return None, outcome
    return max(0.0, base_score + delta), outcome


def build_prior_shortlist(
    task_path: Path,
    environment_path: Path,
    graph_path: Path,
    methods_path: Path | None,
    output: Path,
    root: Path,
    prior_outcomes_path: Path | None = None,
    context_distinction_path: Path | None = None,
) -> dict:
    task = read_object(task_path)
    environment = read_object(environment_path)
    graph = read_object(graph_path)
    methods = read_object(methods_path) if methods_path is not None else None
    prior_outcomes = (
        read_object(prior_outcomes_path) if prior_outcomes_path is not None else None
    )
    context_distinction = (
        read_object(context_distinction_path)
        if context_distinction_path is not None
        else None
    )
    outcome_aggregates, context_exceptions = prior_outcome_maps(
        prior_outcomes, context_distinction
    )
    query = prior_tokens({"objective": task.get("objective"), "operator": task.get("operator"),
                          "workload": task.get("workload"), "baseline": task.get("baseline")})
    task_text = prior_scalar_text(task)
    context_text = prior_scalar_text({"task": task, "environment": environment})
    capability = target_compute_capability(environment)
    event_rows, method_rows = [], []
    rejected = {"event_hard_gate": 0, "event_low_relevance": 0,
                "event_prior_guard": 0,
                "method_hard_gate": 0, "method_low_relevance": 0,
                "method_prior_guard": 0,
                "method_provenance_gate": 0}
    graph_events = {node["event_id"]: node for node in graph["nodes"]}
    for node in graph["nodes"]:
        hard = node["hard_requirements"]
        required_cc = hard["compute_capabilities"]
        required_terms = hard["required_context_terms"]
        if ((required_cc and capability not in required_cc)
                or any(not prior_term_in_text(term, context_text) for term in required_terms)):
            rejected["event_hard_gate"] += 1
            continue
        hits = sorted(query & prior_tokens({
            "summary": node["summary"], "rewrite_families": node["rewrite_families"],
            "operators": node["operators"], "subsystems": node["subsystems"]}))
        if len(hits) < 2:
            rejected["event_low_relevance"] += 1
            continue
        base_score = float(len(hits))
        score, prior_outcome = apply_prior_outcome(
            "EVENT", node["event_id"], base_score,
            outcome_aggregates, context_exceptions,
        )
        if score is None:
            rejected["event_prior_guard"] += 1
            continue
        event_rows.append({"id": node["event_id"], "base_score": base_score,
                           "score": score, "matched_terms": hits,
                           "prior_outcome": prior_outcome, "record": node})
    for card in (methods or {}).get("cards", []):
        if card["kind"] not in {
            "TRANSFORMATION",
            "ORCHESTRATION",
            "EVALUATION_GUARD",
        }:
            rejected["method_low_relevance"] += 1
            continue
        applicability = card["applicability"]
        vendors = {item.lower() for item in applicability["vendors"]}
        vendor_ok = "any" in vendors or ("nvidia" in context_text and "nvidia" in vendors)
        capabilities_ok = all(item.lower() in context_text for item in applicability["required_capabilities"])
        affinities = applicability["architecture_affinity"]
        affinity_ok = not affinities or any(item.lower() in context_text for item in affinities)
        if not vendor_ok or not capabilities_ok or not affinity_ok:
            rejected["method_hard_gate"] += 1
            continue
        provenance = card.get("community_provenance")
        if provenance is not None:
            sources = [graph_events.get(event_id)
                       for event_id in provenance["source_event_ids"]]
            card_available = datetime.fromisoformat(
                card["source"]["available_at"].replace("Z", "+00:00"))
            experiment_times = [datetime.fromisoformat(
                ref["available_at"].replace("Z", "+00:00"))
                for ref in provenance.get("experiment_refs", [])]
            if (any(source is None for source in sources)
                    or any(datetime.fromisoformat(
                        source["source_available_at"].replace("Z", "+00:00"))
                        > card_available for source in sources if source is not None)
                    or any(available > card_available
                           for available in experiment_times)):
                rejected["method_provenance_gate"] += 1
                continue
        hits = sorted({term.lower() for term in applicability["problem_signatures"]
                       if prior_term_in_text(term, task_text)})
        if len(hits) < 2:
            rejected["method_low_relevance"] += 1
            continue
        kind_bonus = {
            "EVALUATION_GUARD": 3.0,
            "TRANSFORMATION": 2.0,
            "ORCHESTRATION": 1.0,
        }[card["kind"]]
        base_score = float(len(hits)) + kind_bonus
        score, prior_outcome = apply_prior_outcome(
            "METHOD", card["method_id"], base_score,
            outcome_aggregates, context_exceptions,
        )
        if score is None:
            rejected["method_prior_guard"] += 1
            continue
        method_rows.append({"id": card["method_id"],
                            "base_score": base_score, "score": score,
                            "matched_terms": hits,
                            "prior_outcome": prior_outcome, "record": card})
    event_rows.sort(key=lambda row: (-row["score"], row["id"]))
    method_rows.sort(key=lambda row: (-row["score"], row["id"]))
    candidate_methods = [row for row in method_rows
                         if row["record"]["kind"] != "EVALUATION_GUARD"][:2]
    evaluation_guards = [row for row in method_rows
                         if row["record"]["kind"] == "EVALUATION_GUARD"][:1]
    selected_methods = sorted(candidate_methods + evaluation_guards,
                              key=lambda row: (-row["score"], row["id"]))
    top_event = event_rows[0] if event_rows else None
    top_method = candidate_methods[0] if candidate_methods else None
    if ((top_event is not None and top_event["score"] >= 5.0)
            or (top_method is not None and top_method["score"] >= 5.0)):
        routing_recommendation = "CONSULT_BEFORE_FIRST_CANDIDATE"
        routing_rationale = (
            "A hard-gated prior has at least five relevance points; inspect its "
            "smallest transferable mechanism before the first source edit."
        )
    elif top_event is not None or top_method is not None:
        routing_recommendation = "DEFER_UNTIL_LOCAL_GAP"
        routing_rationale = (
            "Relevant priors exist, but their lexical evidence is weak enough to "
            "defer retrieval until local diagnosis leaves a named gap."
        )
    else:
        routing_recommendation = "NO_RELEVANT_PRIOR"
        routing_rationale = "No event or candidate-generation method passed routing."
    receipt = {
        "schema_version": PRIOR_SHORTLIST_SCHEMA, "generated_at": now(),
        "claim_boundary": "DISCOVERY_PRIOR_ONLY",
        "inputs": {"task": identity_for(task_path, task_path.parent.parent),
                   "environment": identity_for(environment_path, environment_path.parent.parent),
                   "graph": identity_for(graph_path, graph_path.parent.parent),
                   "methods": identity_for(methods_path, methods_path.parent.parent) if methods_path else None,
                   "prior_outcomes": identity_for(
                       prior_outcomes_path, prior_outcomes_path.parent.parent
                   ) if prior_outcomes_path else None,
                   "prior_context_distinction": identity_for(
                       context_distinction_path,
                       context_distinction_path.parent.parent,
                   ) if context_distinction_path else None},
        "policy": {"max_events": 2, "max_methods": 3, "minimum_token_hits": 2,
                   "hard_gate_policy": "FAIL_CLOSED",
                   "outcome_adjustments": {
                       "UPRANK": 1.0,
                       "DOWNRANK": -1.0,
                       "UNCHANGED": 0.0,
                       "REQUIRE_CONTEXT_GUARD": 0.0,
                   }},
        "events": event_rows[:2], "methods": selected_methods,
        "routing": {
            "recommendation": routing_recommendation,
            "top_event_id": top_event["id"] if top_event is not None else None,
            "top_event_score": top_event["score"] if top_event is not None else None,
            "top_method_id": top_method["id"] if top_method is not None else None,
            "top_method_score": top_method["score"] if top_method is not None else None,
            "rationale": routing_rationale,
        },
        "rejections": rejected,
    }
    errors = validate_instance(receipt, read_object(root / "schemas" / "community_prior_shortlist.schema.json"))
    if errors:
        raise ValueError("invalid prior shortlist: " + "; ".join(errors))
    atomic_json(output, receipt)
    return receipt


def build_frontier_contract(task_path: Path, output: Path, material_gain_margin: float,
                            root: Path) -> dict:
    """Bind every new trial to a small, task-independent search-space audit."""
    contract = {
        "schema_version": FRONTIER_CONTRACT_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "MINIMUM_SEARCH_COVERAGE_ONLY",
        "task_identity": identity_for(task_path, task_path.parent.parent),
        "policy": {
            "minimum_ranked_architectures": 3,
            "unknown_bound_policy": "SCREEN_OR_EXHAUST_SEARCH_PHASE",
            "deadline_fraction": 0.55,
            "material_gain_margin": material_gain_margin,
            "qualification_checkpoint": (
                "FIRST_MATERIAL_CORRECT_BEFORE_NEXT_CANDIDATE"
            ),
        },
        "required_dimensions": [
            {
                "dimension_id": "launch-materialization",
                "question": "Can launches, graph breaks, or mandatory intermediate traffic be removed?",
            },
            {
                "dimension_id": "work-decomposition",
                "question": "Would a structurally different partition/reduction/pipeline expose more useful parallelism?",
            },
            {
                "dimension_id": "shape-path-specialization",
                "question": "Can dominant shapes or optional runtime paths use a materially cheaper implementation?",
            },
        ],
    }
    errors = validate_instance(
        contract,
        read_object(root / "schemas" / "community_frontier_contract.schema.json"),
    )
    if errors:
        raise ValueError("invalid frontier contract: " + "; ".join(errors))
    atomic_json(output, contract)
    return contract


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include a timezone: {value}")
    return parsed


def resolve_inside(base: Path, relative: str) -> Path:
    path = (base / relative).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError as error:
        raise ValueError(f"identity path escapes its artifact root: {relative}") from error
    return path


def validate_identity(base: Path, identity: dict, label: str) -> Path:
    path = resolve_inside(base, identity["path"])
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    if sha256_file(path) != identity["sha256"]:
        raise ValueError(f"{label} hash changed: {identity['path']}")
    return path


def validate_prior_context_distinction(
    contract_path: Path,
    ledger_path: Path,
    task_id: str,
    root: Path,
) -> dict:
    errors = validate_json_file(
        contract_path,
        root / "schemas" / "community_prior_context_distinction.schema.json",
    )
    if errors:
        raise ValueError("invalid prior context distinction: " + "; ".join(errors))
    contract = read_object(contract_path)
    if contract["schema_version"] != PRIOR_CONTEXT_DISTINCTION_SCHEMA:
        raise ValueError("unsupported prior context distinction schema")
    if contract["task_id"] != task_id:
        raise ValueError("prior context distinction task_id does not match suite task")
    if contract["prior_outcome_ledger_sha256"] != sha256_file(ledger_path):
        raise ValueError("prior context distinction binds a different outcome ledger")
    ledger = read_object(ledger_path)
    guarded = {
        (row["prior_kind"], row["prior_id"]): row
        for row in ledger["aggregates"]
        if row["routing_adjustment"] == "REQUIRE_CONTEXT_GUARD"
    }
    seen: set[tuple[str, str]] = set()
    for exception in contract["exceptions"]:
        key = (exception["prior_kind"], exception["prior_id"])
        if key in seen:
            raise ValueError(f"duplicate prior context exception: {key}")
        seen.add(key)
        if key not in guarded:
            raise ValueError(
                f"prior context exception does not name a guarded prior: {key}"
            )
        failed_tasks = {
            row["task_id"]
            for row in ledger["observations"]
            if (row["prior_kind"], row["prior_id"]) == key
            and row["deltas"]["heldout_pass_count_gain"] is not None
            and float(row["deltas"]["heldout_pass_count_gain"]) < 0
        }
        if set(exception["failed_task_ids"]) != failed_tasks:
            raise ValueError(
                f"prior context exception omits or invents failed tasks for {key}"
            )
    return contract


def suite_protocol_registration_errors(suite: dict, preregistration: dict) -> list[str]:
    errors = []
    if parse_time(preregistration["cutoff_at"]) != parse_time(suite["cutoff_at"]):
        errors.append("suite cutoff differs from anchored preregistration")
    evaluation = preregistration.get("evaluation")
    if evaluation is None:
        errors.append("anchored suite requires a preregistered evaluation protocol")
        return errors
    protocol = suite["protocol"]
    for field in (
        "arms",
        "repeats",
        "randomized_order",
        "network_policy",
        "model_identity",
        "task_packet_contract",
        "budgets",
        "minimum_material_speedup",
        "metrics",
    ):
        if protocol.get(field) != evaluation[field]:
            errors.append(
                f"suite protocol {field} differs from anchored preregistration"
            )
    return errors


def validate_suite(
    suite_path: Path, corpus: Path, root: Path | None = None
) -> dict:
    root = root or repository_root()
    suite_path = suite_path.resolve()
    schema_errors = validate_json_file(
        suite_path, root / "schemas" / "community_temporal_suite.schema.json"
    )
    if schema_errors:
        raise ValueError("invalid temporal suite: " + "; ".join(schema_errors))
    suite = read_object(suite_path)
    if suite["schema_version"] != SUITE_SCHEMA:
        raise ValueError("unsupported temporal suite schema")
    if set(suite["protocol"]["metrics"]) != METRICS:
        raise ValueError("temporal suite must measure the complete metric set")

    base = suite_path.parent
    graph_path = validate_identity(base, suite["training_graph"], "training graph")
    validate_corpus(corpus, root)
    validate_graph(graph_path, corpus, root)
    graph = read_object(graph_path)
    cutoff = parse_time(suite["cutoff_at"])
    anchored_preregistration = None
    if suite.get("preselection_anchor") is not None:
        anchor_path = validate_identity(
            base, suite["preselection_anchor"], "suite preselection anchor"
        )
        validate_preselection_anchor(anchor_path, root)
        anchor = read_object(anchor_path)
        anchored_preregistration = read_object(
            Path(anchor["preregistration_identity"]["path"])
        )
        protocol_errors = suite_protocol_registration_errors(
            suite, anchored_preregistration
        )
        if protocol_errors:
            raise ValueError("; ".join(protocol_errors))
    for node in graph["nodes"]:
        if parse_time(node["source_available_at"]) > cutoff:
            raise ValueError(
                f"temporal leakage: {node['event_id']} source evidence "
                "was available after cutoff"
            )
    method_count = 0
    if suite.get("training_methods"):
        method_path = validate_identity(
            base, suite["training_methods"], "training method snapshot"
        )
        method_errors = validate_json_file(
            method_path,
            root / "schemas" / "optimization_method_snapshot.schema.json",
        )
        if method_errors:
            raise ValueError("invalid training method snapshot: " + "; ".join(method_errors))
        method_snapshot = read_object(method_path)
        if parse_time(method_snapshot["cutoff_at"]) != cutoff:
            raise ValueError("training method snapshot cutoff does not match suite cutoff")
        card_ids = []
        for card in method_snapshot["cards"]:
            card_errors = validate_instance(
                card, read_object(root / "schemas" / "optimization_method.schema.json")
            )
            if card_errors:
                raise ValueError("invalid method card in training snapshot: " + "; ".join(card_errors))
            if parse_time(card["source"]["available_at"]) > cutoff:
                raise ValueError(
                    f"temporal leakage: method {card['method_id']} was available after cutoff"
                )
            card_ids.append(card["method_id"])
        if sorted(card_ids) != method_snapshot["included_method_ids"]:
            raise ValueError("training method snapshot card ids do not match included_method_ids")
        if len(card_ids) != len(set(card_ids)):
            raise ValueError("training method snapshot contains duplicate method ids")
        method_count = len(card_ids)
    prior_outcome_path = None
    if suite.get("training_prior_outcomes"):
        prior_outcome_path = validate_identity(
            base, suite["training_prior_outcomes"], "training prior outcome ledger"
        )
        prior_errors = validate_json_file(
            prior_outcome_path,
            root / "schemas" / "community_prior_outcome_ledger.schema.json",
        )
        if prior_errors:
            raise ValueError(
                "invalid training prior outcome ledger: " + "; ".join(prior_errors)
            )
        prior_outcomes = read_object(prior_outcome_path)
        validate_prior_outcome_ledger_consistency(prior_outcomes)
        if parse_time(prior_outcomes["generated_at"]) > cutoff:
            raise ValueError(
                "temporal leakage: prior outcome ledger was generated after cutoff"
            )
    prior_routing_path = None
    if suite.get("training_prior_routing") is not None:
        prior_routing_path = validate_identity(
            base, suite["training_prior_routing"], "training prior routing snapshot"
        )
        routing_errors = validate_json_file(
            prior_routing_path,
            root / "schemas" / "community_prior_routing_snapshot.schema.json",
        )
        if routing_errors:
            raise ValueError(
                "invalid training prior routing snapshot: "
                + "; ".join(routing_errors)
            )
        prior_routing = read_object(prior_routing_path)
        if parse_time(prior_routing["generated_at"]) > cutoff:
            raise ValueError(
                "temporal leakage: prior routing snapshot was generated after cutoff"
            )
        if prior_outcome_path is None:
            raise ValueError(
                "training prior routing snapshot requires its source outcome ledger"
            )
        if prior_routing["source_ledger"]["sha256"] != sha256_file(
            prior_outcome_path
        ):
            raise ValueError(
                "training prior routing snapshot binds a different outcome ledger"
            )
    if anchored_preregistration is not None:
        evaluation = anchored_preregistration["evaluation"]
        if prior_outcome_path is None:
            raise ValueError("anchored suite is missing its preregistered outcome ledger")
        if sha256_file(prior_outcome_path) != evaluation["source_ledger_sha256"]:
            raise ValueError("suite outcome ledger differs from anchored preregistration")
        routing_identity = anchored_preregistration.get("prior_routing_identity")
        if routing_identity is None or prior_routing_path is None:
            raise ValueError("anchored suite is missing its prior routing snapshot")
        if sha256_file(prior_routing_path) != routing_identity["sha256"]:
            raise ValueError(
                "suite prior routing snapshot differs from anchored preregistration"
            )
    training_sources: set[tuple[str, int]] = set()
    for event_identity in graph["input_identity"]["events"]:
        event_path = validate_identity(corpus, event_identity, "training event")
        event = read_object(event_path)
        source = event["source_snapshot"]
        training_sources.add((source["repository"], source["pr_number"]))

    validate_identity(base, suite["protocol"]["prompt_identity"], "trial prompt")
    validate_identity(
        base, suite["protocol"]["environment_identity"], "runtime environment"
    )
    task_ids: set[str] = set()
    task_packet_contract = suite["protocol"].get(
        "task_packet_contract", "LEGACY_UNSCHEMATIZED"
    )
    for task in suite["tasks"]:
        if task["task_id"] in task_ids:
            raise ValueError(f"duplicate task_id: {task['task_id']}")
        task_ids.add(task["task_id"])
        if parse_time(task["available_at"]) <= cutoff:
            raise ValueError(
                f"temporal leakage: task {task['task_id']} is not after cutoff"
            )
        if (task["repository"], task.get("pr_number")) in training_sources:
            raise ValueError(
                f"temporal leakage: held-out task {task['task_id']} is in training graph"
            )
        packet_path = validate_identity(
            base, task["packet"], f"task packet {task['task_id']}"
        )
        oracle_path = validate_identity(
            base, task["hidden_oracle"], f"hidden oracle {task['task_id']}"
        )
        if task.get("prior_context_distinction") is not None:
            if prior_outcome_path is None:
                raise ValueError(
                    "prior context distinction requires a training prior outcome ledger"
                )
            distinction_path = validate_identity(
                base,
                task["prior_context_distinction"],
                f"prior context distinction {task['task_id']}",
            )
            validate_prior_context_distinction(
                distinction_path, prior_outcome_path, task["task_id"], root
            )
        if task_packet_contract in {"STRICT_V2", "STRICT_V3"}:
            packet_schema = (
                "community_heldout_task_v3.schema.json"
                if task_packet_contract == "STRICT_V3"
                else "community_heldout_task.schema.json"
            )
            packet_errors = validate_json_file(
                packet_path, root / "schemas" / packet_schema
            )
            if packet_errors:
                raise ValueError(
                    f"invalid strict task packet {task['task_id']}: "
                    + "; ".join(packet_errors)
                )
            oracle_errors = validate_json_file(
                oracle_path, root / "schemas" / "community_hidden_oracle.schema.json"
            )
            if oracle_errors:
                raise ValueError(
                    f"invalid strict hidden oracle {task['task_id']}: "
                    + "; ".join(oracle_errors)
                )
            packet = read_object(packet_path)
            oracle = read_object(oracle_path)
            if packet["task_id"] != task["task_id"] or oracle["task_id"] != task["task_id"]:
                raise ValueError(
                    f"strict task/oracle identity does not match {task['task_id']}"
                )
            if task_packet_contract == "STRICT_V3":
                confirmed_at = parse_time(
                    packet["intake_confirmation"]["confirmed_at"]
                )
                if confirmed_at <= cutoff:
                    raise ValueError(
                        f"STRICT_V3 task {task['task_id']} intake confirmation "
                        "is not after the training cutoff"
                    )
                if confirmed_at > parse_time(task["available_at"]):
                    raise ValueError(
                        f"STRICT_V3 task {task['task_id']} intake confirmation "
                        "postdates the sealed task"
                    )
            if task.get("prospective_id") is not None:
                seal = oracle.get("prospective_seal")
                if seal is None:
                    raise ValueError(
                        f"prospective task {task['task_id']} lacks a prospective seal"
                    )
                if seal["baseline_revision"] != task["base_revision"]:
                    raise ValueError(
                        f"prospective task {task['task_id']} baseline revision mismatch"
                    )
                if seal["task_packet_sha256"] != task["packet"]["sha256"]:
                    raise ValueError(
                        f"prospective task {task['task_id']} packet seal mismatch"
                    )
                if parse_time(seal["sealed_at"]) != parse_time(task["available_at"]):
                    raise ValueError(
                        f"prospective task {task['task_id']} seal time mismatch"
                    )
            weight_sum = sum(float(value) for value in packet["workload"]["shape_weights"].values())
            if not math.isclose(weight_sum, 1.0, rel_tol=0.0, abs_tol=1e-9):
                raise ValueError(
                    f"strict task packet {task['task_id']} shape weights sum to {weight_sum}, not 1"
                )
            if packet["hardware"]["device"].lower() not in task["target_hardware"].lower():
                raise ValueError(
                    f"strict task packet {task['task_id']} hardware does not match suite target"
                )
        support_targets: set[str] = set()
        for item in task.get("support", []):
            validate_identity(
                base, item["source"], f"task support {task['task_id']}"
            )
            target = PurePosixPath(item["target"])
            if target.is_absolute() or ".." in target.parts:
                raise ValueError(
                    f"task support target escapes harness: {item['target']}"
                )
            normalized = target.as_posix()
            if normalized in support_targets:
                raise ValueError(f"duplicate task support target: {normalized}")
            support_targets.add(normalized)
    return {
        "status": "PASS",
        "suite_id": suite["suite_id"],
        "training_event_count": len(graph["nodes"]),
        "training_method_count": method_count,
        "task_count": len(suite["tasks"]),
        "cutoff_at": suite["cutoff_at"],
    }


def absolute_identity(path: Path) -> dict:
    resolved = path.resolve()
    return {"path": resolved.as_posix(), "sha256": sha256_file(resolved)}


def build_heldout_queue(
    receipt_paths: list[Path],
    graph_path: Path,
    methods_path: Path | None,
    corpus: Path,
    cutoff_at: str,
    max_items: int,
    random_seed: int,
    root: Path | None = None,
) -> dict:
    """Select post-cutoff PRs from discovery metadata without solution artifacts."""
    root = root or repository_root()
    if not receipt_paths:
        raise ValueError("held-out selection requires at least one sync receipt")
    if not 1 <= max_items <= 100:
        raise ValueError("held-out max_items must be between 1 and 100")
    if random_seed < 0:
        raise ValueError("held-out random_seed must be non-negative")
    cutoff = parse_time(cutoff_at)

    graph_path = graph_path.resolve()
    validate_graph(graph_path, corpus, root)
    graph = read_object(graph_path)
    graph_cutoff = graph.get("temporal_cutoff_at")
    if graph_cutoff is None or parse_time(graph_cutoff) != cutoff:
        raise ValueError("training graph cutoff does not match held-out cutoff")
    training_sources = {
        (node["repository"], int(node["pr_number"])) for node in graph["nodes"]
    }

    method_identity = None
    if methods_path is not None:
        methods_path = methods_path.resolve()
        method_errors = validate_json_file(
            methods_path,
            root / "schemas" / "optimization_method_snapshot.schema.json",
        )
        if method_errors:
            raise ValueError(
                "invalid held-out method snapshot: " + "; ".join(method_errors)
            )
        methods = read_object(methods_path)
        if parse_time(methods["cutoff_at"]) != cutoff:
            raise ValueError("training method cutoff does not match held-out cutoff")
        method_ids = []
        for card in methods["cards"]:
            if parse_time(card["source"]["available_at"]) > cutoff:
                raise ValueError(
                    f"held-out method snapshot leaks future method {card['method_id']}"
                )
            method_ids.append(card["method_id"])
        if sorted(method_ids) != methods["included_method_ids"]:
            raise ValueError(
                "held-out method snapshot card ids do not match included ids"
            )
        if len(method_ids) != len(set(method_ids)):
            raise ValueError("held-out method snapshot contains duplicate method ids")
        method_identity = absolute_identity(methods_path)

    receipt_schema = root / "schemas" / "community_sync_receipt.schema.json"
    receipt_identities = []
    candidate_count = 0
    deduplicated: dict[tuple[str, int], dict] = {}
    for raw_path in sorted({path.resolve() for path in receipt_paths}):
        errors = validate_json_file(raw_path, receipt_schema)
        if errors:
            raise ValueError(
                f"invalid held-out sync receipt {raw_path}: " + "; ".join(errors)
            )
        receipt = read_object(raw_path)
        if receipt["schema_version"] != "community-sync-receipt-v2":
            raise ValueError("held-out selection requires community-sync-receipt-v2")
        if (
            receipt.get("window_basis") != "UPDATED_AT"
            or receipt.get("heldout_eligibility_basis") != "EARLIEST_PUBLIC_AT"
        ):
            raise ValueError("held-out sync receipt has unsafe time semantics")
        receipt_identities.append(absolute_identity(raw_path))
        repository = receipt["repository"]
        for candidate in receipt["candidates"]:
            candidate_count += 1
            if candidate["earliest_public_at"] != candidate["created_at"]:
                raise ValueError(
                    f"held-out candidate {repository}#{candidate['pr_number']} "
                    "has inconsistent earliest public time"
                )
            earliest = parse_time(candidate["earliest_public_at"])
            updated = parse_time(candidate["updated_at"])
            if earliest > updated:
                raise ValueError(
                    f"held-out candidate {repository}#{candidate['pr_number']} "
                    "was updated before it was public"
                )
            key = (repository, int(candidate["pr_number"]))
            row = {
                "repository": repository,
                "pr_number": int(candidate["pr_number"]),
                "title": candidate["title"],
                "earliest_public_at": candidate["earliest_public_at"],
                "updated_at": candidate["updated_at"],
                "classifications": sorted(candidate["classifications"]),
                "discovery_score": int(candidate["selection_score"]),
            }
            previous = deduplicated.get(key)
            if previous is not None:
                if previous["earliest_public_at"] != row["earliest_public_at"]:
                    raise ValueError(
                        f"held-out candidate {repository}#{candidate['pr_number']} "
                        "has conflicting creation times"
                    )
                if parse_time(previous["updated_at"]) >= updated:
                    continue
            deduplicated[key] = row

    eligible = []
    excluded = []
    for key, row in sorted(deduplicated.items()):
        if parse_time(row["earliest_public_at"]) <= cutoff:
            excluded.append(
                {
                    "repository": row["repository"],
                    "pr_number": row["pr_number"],
                    "earliest_public_at": row["earliest_public_at"],
                    "reason": "PRE_CUTOFF_PUBLIC",
                }
            )
            continue
        if key in training_sources:
            excluded.append(
                {
                    "repository": row["repository"],
                    "pr_number": row["pr_number"],
                    "earliest_public_at": row["earliest_public_at"],
                    "reason": "TRAINING_SOURCE",
                }
            )
            continue
        row["diversity_group"] = (
            row["repository"] + ":" + ",".join(row["classifications"])
        )
        row["seeded_tiebreak"] = hashlib.sha256(
            f"{random_seed}:{row['repository']}:{row['pr_number']}".encode()
        ).hexdigest()
        eligible.append(row)

    grouped: dict[str, list[dict]] = {}
    for row in eligible:
        grouped.setdefault(row["diversity_group"], []).append(row)
    for rows in grouped.values():
        rows.sort(
            key=lambda row: (-row["discovery_score"], row["seeded_tiebreak"])
        )
        for rank, row in enumerate(rows, start=1):
            row["within_group_rank"] = rank
    eligible.sort(
        key=lambda row: (
            row["within_group_rank"] != 1,
            -row["discovery_score"],
            row["seeded_tiebreak"],
        )
    )
    for rank, row in enumerate(eligible, start=1):
        row["priority_rank"] = rank
        row["selection"] = "SELECTED" if rank <= max_items else "BACKLOG"

    queue = {
        "schema_version": HELDOUT_QUEUE_SCHEMA,
        "generated_at": now(),
        "cutoff_at": cutoff_at,
        "claim_boundary": "DISCOVERY_METADATA_SELECTION_ONLY",
        "input_identity": {
            "receipts": receipt_identities,
            "training_graph": absolute_identity(graph_path),
            "training_methods": method_identity,
            "corpus_index_sha256": sha256_file(corpus.resolve() / "index.json"),
        },
        "policy": {
            "max_items": max_items,
            "random_seed": random_seed,
            "required_receipt_schema": "community-sync-receipt-v2",
            "eligibility_time_field": "earliest_public_at",
            "exclude_training_sources": True,
            "selection_inputs": [
                "repository",
                "pr_number",
                "classifications",
                "selection_score",
                "earliest_public_at",
            ],
            "ordering": (
                "DIVERSE_GROUP_FIRST_THEN_DISCOVERY_SCORE_THEN_SEEDED_HASH"
            ),
        },
        "inventory": {
            "receipt_candidate_count": candidate_count,
            "deduplicated_count": len(deduplicated),
            "eligible_count": len(eligible),
            "selected_count": min(len(eligible), max_items),
            "backlog_count": max(0, len(eligible) - max_items),
            "excluded_pre_cutoff_count": sum(
                row["reason"] == "PRE_CUTOFF_PUBLIC" for row in excluded
            ),
            "excluded_training_source_count": sum(
                row["reason"] == "TRAINING_SOURCE" for row in excluded
            ),
        },
        "items": eligible,
        "excluded": excluded,
    }
    errors = validate_instance(
        queue,
        read_object(root / "schemas" / "community_heldout_queue.schema.json"),
    )
    if errors:
        raise ValueError("invalid held-out queue: " + "; ".join(errors))
    return queue


def validate_heldout_queue(
    queue_path: Path, corpus: Path, root: Path | None = None
) -> dict:
    root = root or repository_root()
    queue_path = queue_path.resolve()
    errors = validate_json_file(
        queue_path, root / "schemas" / "community_heldout_queue.schema.json"
    )
    if errors:
        raise ValueError("invalid held-out queue: " + "; ".join(errors))
    queue = read_object(queue_path)
    inputs = queue["input_identity"]
    corpus_index = corpus.resolve() / "index.json"
    if sha256_file(corpus_index) != inputs["corpus_index_sha256"]:
        raise ValueError("held-out queue corpus index changed")
    for identity in [*inputs["receipts"], inputs["training_graph"]]:
        path = Path(identity["path"])
        if not path.is_file() or sha256_file(path) != identity["sha256"]:
            raise ValueError(f"held-out queue input changed: {identity['path']}")
    method_identity = inputs["training_methods"]
    methods_path = None
    if method_identity is not None:
        methods_path = Path(method_identity["path"])
        if (
            not methods_path.is_file()
            or sha256_file(methods_path) != method_identity["sha256"]
        ):
            raise ValueError(
                f"held-out queue input changed: {method_identity['path']}"
            )
    expected = build_heldout_queue(
        [Path(identity["path"]) for identity in inputs["receipts"]],
        Path(inputs["training_graph"]["path"]),
        methods_path,
        corpus,
        queue["cutoff_at"],
        int(queue["policy"]["max_items"]),
        int(queue["policy"]["random_seed"]),
        root,
    )
    observed_stable = {
        key: value for key, value in queue.items() if key != "generated_at"
    }
    expected_stable = {
        key: value for key, value in expected.items() if key != "generated_at"
    }
    if observed_stable != expected_stable:
        raise ValueError("held-out queue is stale or was edited without recomputation")
    return {"status": "PASS", **queue["inventory"]}


def rule_matches_candidate(rule: dict, candidate: dict) -> bool:
    match = rule.get("match", {})
    repositories = match.get("repositories")
    if repositories is not None and candidate["repository"] not in repositories:
        return False
    classifications = match.get("classifications_any")
    if classifications is not None and not (
        set(classifications) & set(candidate["classifications"])
    ):
        return False
    title_regex = match.get("title_regex")
    if title_regex is not None and re.search(
        title_regex, candidate["title"], flags=re.IGNORECASE
    ) is None:
        return False
    return True


def resource_satisfies(resource: dict, requirements: dict) -> bool:
    vendors = requirements["vendors_any"]
    return (
        (not vendors or resource["vendor"] in vendors)
        and set(requirements["capabilities_all"]) <= set(resource["capabilities"])
        and resource["gpu_count"] >= requirements["minimum_gpu_count"]
        and resource["memory_gib_per_gpu"]
        >= requirements["minimum_memory_gib_per_gpu"]
    )


def build_feasibility_screen(
    queue_path: Path,
    policy_path: Path,
    profile_path: Path,
    corpus: Path,
    root: Path | None = None,
) -> dict:
    """Account for every selected task using frozen discovery metadata only."""
    root = root or repository_root()
    queue_path = queue_path.resolve()
    policy_path = policy_path.resolve()
    profile_path = profile_path.resolve()
    validate_heldout_queue(queue_path, corpus, root)
    for path, schema_name, label in (
        (policy_path, "community_feasibility_policy.schema.json", "policy"),
        (profile_path, "community_execution_profile.schema.json", "profile"),
    ):
        errors = validate_json_file(path, root / "schemas" / schema_name)
        if errors:
            raise ValueError(f"invalid feasibility {label}: " + "; ".join(errors))
    queue = read_object(queue_path)
    policy = read_object(policy_path)
    profile = read_object(profile_path)

    priorities = [int(rule["priority"]) for rule in policy["rules"]]
    if len(priorities) != len(set(priorities)):
        raise ValueError("feasibility policy rule priorities must be unique")
    for rule in policy["rules"]:
        title_regex = rule["match"].get("title_regex")
        if title_regex is not None:
            try:
                re.compile(title_regex)
            except re.error as error:
                raise ValueError(
                    f"invalid feasibility regex in {rule['rule_id']}: {error}"
                ) from error
    resource_ids = [row["resource_id"] for row in profile["resources"]]
    if len(resource_ids) != len(set(resource_ids)):
        raise ValueError("execution profile resource ids must be unique")
    harness_keys = [
        (row["repository"], row["task_family"]) for row in profile["harnesses"]
    ]
    if len(harness_keys) != len(set(harness_keys)):
        raise ValueError("execution profile harness keys must be unique")
    harnesses = {
        (row["repository"], row["task_family"]): row
        for row in profile["harnesses"]
    }

    rules = sorted(policy["rules"], key=lambda row: int(row["priority"]))
    items = []
    for candidate in queue["items"]:
        if candidate["selection"] != "SELECTED":
            continue
        rule = next(
            (row for row in rules if rule_matches_candidate(row, candidate)),
            policy["default_rule"],
        )
        rule_id = rule.get("rule_id", "default")
        requirements = rule["requirements"]
        capable = sorted(
            resource["resource_id"]
            for resource in profile["resources"]
            if resource_satisfies(resource, requirements)
        )
        ready = sorted(
            resource["resource_id"]
            for resource in profile["resources"]
            if resource["resource_id"] in capable
            and resource["availability"] == "AVAILABLE"
        )
        harness = harnesses.get((candidate["repository"], rule["task_family"]))
        harness_status = harness["status"] if harness else "UNKNOWN"
        if rule.get("forced_status") is not None:
            status = rule["forced_status"]
            reason = rule["reason"]
            harness_status = "NOT_APPLICABLE"
        elif not capable:
            status = "INFEASIBLE"
            reason = "NO_DECLARED_RESOURCE_SATISFIES_REQUIREMENTS"
        elif not ready:
            status = "HARNESS_BLOCKED"
            reason = "CAPABLE_RESOURCE_NOT_CURRENTLY_AVAILABLE"
        elif harness_status != "READY":
            status = "HARNESS_BLOCKED"
            reason = harness["reason"] if harness else "HARNESS_NOT_DECLARED"
        else:
            status = "ELIGIBLE"
            reason = rule["reason"]
        items.append(
            {
                "repository": candidate["repository"],
                "pr_number": candidate["pr_number"],
                "queue_priority_rank": candidate["priority_rank"],
                "task_family": rule["task_family"],
                "matched_rule_id": rule_id,
                "requirements": requirements,
                "status": status,
                "reason": reason,
                "candidate_resource_ids": capable,
                "ready_resource_ids": ready,
                "harness_status": harness_status,
            }
        )
    items.sort(key=lambda row: row["queue_priority_rank"])
    selected_count = queue["inventory"]["selected_count"]
    if len(items) != selected_count:
        raise ValueError("feasibility screen did not account for every selected task")
    registration = (
        "PRESELECTION"
        if parse_time(policy["declared_at"]) <= parse_time(queue["generated_at"])
        else "POST_SELECTION_PILOT"
    )
    screen = {
        "schema_version": FEASIBILITY_SCREEN_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "FEASIBILITY_ACCOUNTING_NOT_PERFORMANCE_EVIDENCE",
        "registration": registration,
        "input_identity": {
            "queue": absolute_identity(queue_path),
            "policy": absolute_identity(policy_path),
            "execution_profile": absolute_identity(profile_path),
        },
        "inventory": {
            "selected_queue_count": selected_count,
            "eligible_count": sum(row["status"] == "ELIGIBLE" for row in items),
            "infeasible_count": sum(row["status"] == "INFEASIBLE" for row in items),
            "harness_blocked_count": sum(
                row["status"] == "HARNESS_BLOCKED" for row in items
            ),
        },
        "items": items,
    }
    errors = validate_instance(
        screen,
        read_object(root / "schemas" / "community_feasibility_screen.schema.json"),
    )
    if errors:
        raise ValueError("invalid feasibility screen: " + "; ".join(errors))
    return screen


def validate_feasibility_screen(
    screen_path: Path, corpus: Path, root: Path | None = None
) -> dict:
    root = root or repository_root()
    errors = validate_json_file(
        screen_path, root / "schemas" / "community_feasibility_screen.schema.json"
    )
    if errors:
        raise ValueError("invalid feasibility screen: " + "; ".join(errors))
    screen = read_object(screen_path)
    inputs = screen["input_identity"]
    for identity in inputs.values():
        path = Path(identity["path"])
        if not path.is_file() or sha256_file(path) != identity["sha256"]:
            raise ValueError(f"feasibility screen input changed: {identity['path']}")
    expected = build_feasibility_screen(
        Path(inputs["queue"]["path"]),
        Path(inputs["policy"]["path"]),
        Path(inputs["execution_profile"]["path"]),
        corpus,
        root,
    )
    observed_stable = {
        key: value for key, value in screen.items() if key != "generated_at"
    }
    expected_stable = {
        key: value for key, value in expected.items() if key != "generated_at"
    }
    if observed_stable != expected_stable:
        raise ValueError("feasibility screen is stale or was edited")
    return {"status": "PASS", **screen["inventory"]}


def git_bytes(repository: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout


def anchored_repository_path(repository: Path, relative: str) -> Path:
    repository = repository.resolve()
    path = (repository / Path(relative)).resolve()
    try:
        path.relative_to(repository)
    except ValueError as error:
        raise ValueError(f"preregistration path escapes repository: {relative}") from error
    if not path.is_file():
        raise FileNotFoundError(f"preregistered input is missing: {path}")
    return path


def build_preselection_anchor(
    preregistration_path: Path,
    git_commit: str,
    root: Path | None = None,
) -> dict:
    """Prove the frozen protocol and inputs existed in a pre-cutoff commit."""
    root = (root or repository_root()).resolve()
    preregistration_path = preregistration_path.resolve()
    errors = validate_json_file(
        preregistration_path,
        root / "schemas" / "community_heldout_preregistration.schema.json",
    )
    if errors:
        raise ValueError("invalid held-out preregistration: " + "; ".join(errors))
    try:
        preregistration_relative = preregistration_path.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("preregistration must be inside the Git repository") from error
    resolved_commit = git_bytes(root, "rev-parse", f"{git_commit}^{{commit}}").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", resolved_commit):
        raise ValueError("Git did not resolve a full commit identity")
    preregistration_at_commit = git_bytes(
        root, "show", f"{resolved_commit}:{preregistration_relative}"
    )
    current_bytes = preregistration_path.read_bytes()
    if preregistration_at_commit != current_bytes:
        raise ValueError("working preregistration differs from anchored Git commit")
    preregistration = read_object(preregistration_path)
    committed_at = git_bytes(root, "show", "-s", "--format=%cI", resolved_commit).decode().strip()
    if parse_time(committed_at) > parse_time(preregistration["cutoff_at"]):
        raise ValueError("preregistration commit is later than its discovery cutoff")

    roles = (
        ("FEASIBILITY_POLICY", preregistration["policy_identity"]),
        ("EXECUTION_PROFILE", preregistration["execution_profile_identity"]),
    )
    if preregistration.get("prior_routing_identity") is not None:
        roles = (*roles, (
            "PRIOR_ROUTING_SNAPSHOT",
            preregistration["prior_routing_identity"],
        ))
    anchored_inputs = []
    for role, identity in roles:
        path = anchored_repository_path(root, identity["path"])
        if sha256_file(path) != identity["sha256"]:
            raise ValueError(f"preregistered {role.lower()} hash differs from working file")
        committed_bytes = git_bytes(root, "show", f"{resolved_commit}:{identity['path']}")
        committed_sha256 = hashlib.sha256(committed_bytes).hexdigest()
        if committed_sha256 != identity["sha256"]:
            raise ValueError(f"preregistered {role.lower()} was not frozen in Git commit")
        anchored_inputs.append(
            {"role": role, "path": identity["path"], "sha256": identity["sha256"]}
        )
        if role == "PRIOR_ROUTING_SNAPSHOT":
            routing_errors = validate_json_file(
                path,
                root / "schemas" / "community_prior_routing_snapshot.schema.json",
            )
            if routing_errors:
                raise ValueError(
                    "invalid preregistered prior routing snapshot: "
                    + "; ".join(routing_errors)
                )
            routing = read_object(path)
            if parse_time(routing["generated_at"]) > parse_time(
                preregistration["cutoff_at"]
            ):
                raise ValueError(
                    "prior routing snapshot was generated after discovery cutoff"
                )
            if parse_time(routing["source_ledger"]["generated_at"]) > parse_time(
                preregistration["cutoff_at"]
            ):
                raise ValueError(
                    "prior routing source ledger was generated after discovery cutoff"
                )
            evaluation = preregistration.get("evaluation")
            if (
                evaluation is not None
                and evaluation["source_ledger_sha256"]
                != routing["source_ledger"]["sha256"]
            ):
                raise ValueError(
                    "evaluation source ledger differs from prior routing snapshot"
                )
    anchor = {
        "schema_version": PRESELECTION_ANCHOR_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "GIT_EXISTENCE_BEFORE_CUTOFF_ONLY",
        "preregistration_identity": absolute_identity(preregistration_path),
        "git_anchor": {
            "repository": root.as_posix(),
            "commit": resolved_commit,
            "committed_at": committed_at,
            "preregistration_path": preregistration_relative,
        },
        "anchored_inputs": anchored_inputs,
        "cutoff_at": preregistration["cutoff_at"],
        "status": "PASS",
    }
    errors = validate_instance(
        anchor,
        read_object(root / "schemas" / "community_preselection_anchor.schema.json"),
    )
    if errors:
        raise ValueError("invalid preselection anchor: " + "; ".join(errors))
    return anchor


def validate_preselection_anchor(
    anchor_path: Path, root: Path | None = None
) -> dict:
    root = (root or repository_root()).resolve()
    errors = validate_json_file(
        anchor_path, root / "schemas" / "community_preselection_anchor.schema.json"
    )
    if errors:
        raise ValueError("invalid preselection anchor: " + "; ".join(errors))
    anchor = read_object(anchor_path)
    preregistration_identity = anchor["preregistration_identity"]
    preregistration_path = Path(preregistration_identity["path"])
    if (
        not preregistration_path.is_file()
        or sha256_file(preregistration_path) != preregistration_identity["sha256"]
    ):
        raise ValueError("preselection anchor preregistration input changed")
    expected = build_preselection_anchor(
        preregistration_path, anchor["git_anchor"]["commit"], root
    )
    observed_stable = {
        key: value for key, value in anchor.items() if key != "generated_at"
    }
    expected_stable = {
        key: value for key, value in expected.items() if key != "generated_at"
    }
    if observed_stable != expected_stable:
        raise ValueError("preselection anchor is stale or was edited")
    return {
        "status": "PASS",
        "commit": anchor["git_anchor"]["commit"],
        "committed_at": anchor["git_anchor"]["committed_at"],
        "cutoff_at": anchor["cutoff_at"],
    }


def preselection_link_errors(
    preregistration: dict,
    anchor: dict,
    queue: dict,
    screen: dict,
    receipts: list[dict],
) -> list[str]:
    """Check cross-artifact invariants after each artifact passed its own audit."""
    errors = []
    cutoff_at = preregistration["cutoff_at"]
    if anchor["cutoff_at"] != cutoff_at or queue["cutoff_at"] != cutoff_at:
        errors.append("anchor, queue and preregistration cutoffs must match exactly")
    if parse_time(anchor["git_anchor"]["committed_at"]) > parse_time(cutoff_at):
        errors.append("anchored Git commit is later than preregistered cutoff")
    selection = preregistration["selection"]
    queue_policy = queue["policy"]
    for field in ("max_items", "random_seed", "eligibility_time_field"):
        if queue_policy[field] != selection[field]:
            errors.append(f"queue policy {field} differs from preregistration")
    if queue_policy["required_receipt_schema"] != selection["required_receipt_schema"]:
        errors.append("queue receipt schema differs from preregistration")
    registered = set(preregistration["repositories"])
    observed = {receipt["repository"] for receipt in receipts}
    if observed != registered:
        errors.append("discovery receipt repositories differ from preregistration")
    for receipt in receipts:
        repository = receipt["repository"]
        if receipt["schema_version"] != selection["required_receipt_schema"]:
            errors.append(f"{repository} receipt schema differs from preregistration")
        if parse_time(receipt["window"]["since"]) < parse_time(cutoff_at):
            errors.append(f"{repository} discovery window begins before cutoff")
        if parse_time(receipt["generated_at"]) < parse_time(cutoff_at):
            errors.append(f"{repository} receipt was generated before cutoff")
    if screen["registration"] != "PRESELECTION":
        errors.append("feasibility screen is not labeled PRESELECTION")
    if (
        screen["input_identity"]["policy"]["sha256"]
        != preregistration["policy_identity"]["sha256"]
    ):
        errors.append("screen policy differs from preregistration")
    if (
        screen["input_identity"]["execution_profile"]["sha256"]
        != preregistration["execution_profile_identity"]["sha256"]
    ):
        errors.append("screen execution profile differs from preregistration")
    if (
        queue["inventory"]["receipt_candidate_count"]
        != sum(int(receipt["candidate_count"]) for receipt in receipts)
    ):
        errors.append("queue candidate count differs from discovery receipts")
    if (
        screen["inventory"]["selected_queue_count"]
        != queue["inventory"]["selected_count"]
    ):
        errors.append("feasibility screen does not cover the selected queue")
    screened_total = sum(
        int(screen["inventory"][field])
        for field in (
            "eligible_count",
            "infeasible_count",
            "harness_blocked_count",
        )
    )
    if screened_total != queue["inventory"]["selected_count"]:
        errors.append("feasibility outcome counts do not cover every selected task")
    return errors


def audit_preselection_chain(
    anchor_path: Path,
    queue_path: Path,
    screen_path: Path,
    corpus: Path,
    root: Path | None = None,
) -> dict:
    """Verify that a prospective queue and screen use one anchored protocol."""
    root = (root or repository_root()).resolve()
    anchor_path = anchor_path.resolve()
    queue_path = queue_path.resolve()
    screen_path = screen_path.resolve()
    validate_preselection_anchor(anchor_path, root)
    validate_heldout_queue(queue_path, corpus, root)
    validate_feasibility_screen(screen_path, corpus, root)
    anchor = read_object(anchor_path)
    queue = read_object(queue_path)
    screen = read_object(screen_path)
    preregistration_path = Path(anchor["preregistration_identity"]["path"])
    preregistration = read_object(preregistration_path)
    receipt_paths = [
        Path(identity["path"]) for identity in queue["input_identity"]["receipts"]
    ]
    receipts = [read_object(path) for path in receipt_paths]
    errors = preselection_link_errors(
        preregistration, anchor, queue, screen, receipts
    )
    if screen["input_identity"]["queue"]["sha256"] != sha256_file(queue_path):
        errors.append("feasibility screen is bound to a different queue")
    if errors:
        raise ValueError("invalid preselection chain: " + "; ".join(errors))
    registered = sorted(preregistration["repositories"])
    observed = sorted({receipt["repository"] for receipt in receipts})
    audit = {
        "schema_version": PRESELECTION_CHAIN_AUDIT_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "SELECTION_CHAIN_INTEGRITY_NOT_PERFORMANCE_EVIDENCE",
        "input_identity": {
            "anchor": absolute_identity(anchor_path),
            "preregistration": absolute_identity(preregistration_path),
            "queue": absolute_identity(queue_path),
            "feasibility_screen": absolute_identity(screen_path),
        },
        "observations": {
            "cutoff_at": preregistration["cutoff_at"],
            "git_commit": anchor["git_anchor"]["commit"],
            "registered_repositories": registered,
            "observed_repositories": observed,
            "receipt_count": len(receipts),
            "receipt_candidate_count": queue["inventory"]["receipt_candidate_count"],
            "excluded_pre_cutoff_count": queue["inventory"][
                "excluded_pre_cutoff_count"
            ],
            "selected_count": queue["inventory"]["selected_count"],
            "eligible_count": screen["inventory"]["eligible_count"],
            "infeasible_count": screen["inventory"]["infeasible_count"],
            "harness_blocked_count": screen["inventory"][
                "harness_blocked_count"
            ],
        },
        "status": "PASS",
    }
    errors = validate_instance(
        audit,
        read_object(
            root / "schemas" / "community_preselection_chain_audit.schema.json"
        ),
    )
    if errors:
        raise ValueError("invalid preselection chain audit: " + "; ".join(errors))
    return audit


def validate_preselection_chain_audit(
    audit_path: Path, corpus: Path, root: Path | None = None
) -> dict:
    root = (root or repository_root()).resolve()
    errors = validate_json_file(
        audit_path,
        root / "schemas" / "community_preselection_chain_audit.schema.json",
    )
    if errors:
        raise ValueError("invalid preselection chain audit: " + "; ".join(errors))
    audit = read_object(audit_path)
    inputs = audit["input_identity"]
    for identity in inputs.values():
        path = Path(identity["path"])
        if not path.is_file() or sha256_file(path) != identity["sha256"]:
            raise ValueError(f"preselection chain input changed: {identity['path']}")
    expected = audit_preselection_chain(
        Path(inputs["anchor"]["path"]),
        Path(inputs["queue"]["path"]),
        Path(inputs["feasibility_screen"]["path"]),
        corpus,
        root,
    )
    observed_stable = {
        key: value for key, value in audit.items() if key != "generated_at"
    }
    expected_stable = {
        key: value for key, value in expected.items() if key != "generated_at"
    }
    if observed_stable != expected_stable:
        raise ValueError("preselection chain audit is stale or was edited")
    return {"status": "PASS", **audit["observations"]}


def identity_for(path: Path, base: Path) -> dict:
    return {
        "path": path.resolve().relative_to(base.resolve()).as_posix(),
        "sha256": sha256_file(path),
    }


def source_tree_snapshot(source: Path) -> dict:
    """Return a deterministic content-only identity for a materialized source tree."""
    source = source.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"materialized source tree is missing: {source}")
    entries = []
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        entries.append(
            {
                "path": path.relative_to(source).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    if not entries:
        raise ValueError("materialized source tree is empty")
    encoded = json.dumps(
        entries, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return {
        "schema_version": "community-source-tree-v1",
        "file_count": len(entries),
        "content_bytes": sum(item["size"] for item in entries),
        "root_sha256": hashlib.sha256(encoded).hexdigest(),
        "entries": entries,
    }


def safe_extract_zip(archive: Path, destination: Path) -> None:
    """Extract a git archive without traversal or live-link materialization.

    Git ZIP archives store a symlink's target as its blob payload. Writing that
    payload as a regular file matches Git for Windows with ``core.symlinks=false``
    and prevents a link from escaping the isolated trial.
    """
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as zipped:
        for info in zipped.infolist():
            relative = PurePosixPath(info.filename)
            if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                raise ValueError(f"unsafe source archive member: {info.filename}")
            target = (destination / Path(*relative.parts)).resolve()
            try:
                target.relative_to(destination)
            except ValueError as error:
                raise ValueError(
                    f"source archive member escapes destination: {info.filename}"
                ) from error
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(info) as source_stream, target.open("wb") as target_stream:
                shutil.copyfileobj(source_stream, target_stream)


def run_git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout.strip()


def prepare_trial_source(
    trial_dir: Path, repository: Path, root: Path | None = None
) -> dict:
    """Materialize and bind the exact historical source revision for one trial."""
    root = root or repository_root()
    trial_dir = trial_dir.resolve()
    trial = validate_trial(trial_dir, root)
    repository = repository.resolve()
    if not repository.is_dir():
        raise FileNotFoundError(f"source repository is missing: {repository}")
    source_dir = trial_dir / "source"
    receipt_path = trial_dir / "source_receipt.json"
    tree_path = trial_dir / "source_tree.json"
    if source_dir.exists() or receipt_path.exists() or tree_path.exists():
        raise ValueError("trial source has already been materialized")

    revision = trial["source_checkout"]["revision"]
    resolved_revision = run_git(repository, "rev-parse", f"{revision}^{{commit}}")
    if resolved_revision != revision:
        raise ValueError(
            f"source revision resolved to {resolved_revision}, expected {revision}"
        )
    tree_id = run_git(repository, "rev-parse", f"{revision}^{{tree}}")

    with tempfile.TemporaryDirectory(prefix="source-materialization-", dir=trial_dir) as temporary:
        temporary_path = Path(temporary)
        archive_path = temporary_path / "source.zip"
        archive_result = subprocess.run(
            ["git", "archive", "--format=zip", "--output", str(archive_path), revision],
            cwd=repository,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if archive_result.returncode:
            detail = archive_result.stderr.strip() or archive_result.stdout.strip()
            raise ValueError(f"git archive failed: {detail}")
        archive_sha256 = sha256_file(archive_path)
        extracted = temporary_path / "extracted"
        safe_extract_zip(archive_path, extracted)
        extracted.rename(source_dir)

    source_tree = source_tree_snapshot(source_dir)
    atomic_json(tree_path, source_tree)
    receipt = {
        "schema_version": SOURCE_RECEIPT_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "EXACT_HISTORICAL_SOURCE_MATERIALIZATION",
        "trial_identity": identity_for(trial_dir / "trial.json", trial_dir),
        "repository": trial["source_checkout"]["repository"],
        "revision": revision,
        "git_tree": tree_id,
        "archive_sha256": archive_sha256,
        "symlink_policy": "BLOB_TEXT_NO_LIVE_LINKS",
        "source_root": "source",
        "source_tree": identity_for(tree_path, trial_dir),
        "source_root_sha256": source_tree["root_sha256"],
    }
    errors = validate_instance(
        receipt,
        read_object(root / "schemas" / "community_trial_source_receipt.schema.json"),
    )
    if errors:
        raise ValueError("invalid source receipt: " + "; ".join(errors))
    atomic_json(receipt_path, receipt)
    return validate_source_receipt(trial_dir, root)


def validate_source_receipt(
    trial_dir: Path, root: Path | None = None
) -> dict:
    root = root or repository_root()
    trial_dir = trial_dir.resolve()
    trial = validate_trial(trial_dir, root)
    receipt_path = trial_dir / "source_receipt.json"
    errors = validate_json_file(
        receipt_path,
        root / "schemas" / "community_trial_source_receipt.schema.json",
    )
    if errors:
        raise ValueError("invalid source receipt: " + "; ".join(errors))
    receipt = read_object(receipt_path)
    validate_identity(trial_dir, receipt["trial_identity"], "source receipt trial")
    if receipt["repository"] != trial["source_checkout"]["repository"]:
        raise ValueError("source receipt repository differs from trial")
    if receipt["revision"] != trial["source_checkout"]["revision"]:
        raise ValueError("source receipt revision differs from trial")
    tree_path = validate_identity(
        trial_dir, receipt["source_tree"], "source tree manifest"
    )
    recorded_tree = read_object(tree_path)
    observed_tree = source_tree_snapshot(resolve_inside(trial_dir, receipt["source_root"]))
    if observed_tree != recorded_tree:
        raise ValueError("materialized source tree changed after binding")
    if receipt["source_root_sha256"] != observed_tree["root_sha256"]:
        raise ValueError("source root hash differs from source tree manifest")
    return {
        "status": "PASS",
        "trial_id": trial["trial_id"],
        "revision": receipt["revision"],
        "git_tree": receipt["git_tree"],
        "file_count": observed_tree["file_count"],
        "content_bytes": observed_tree["content_bytes"],
        "source_root_sha256": observed_tree["root_sha256"],
    }


def audit_codex_execution(
    trial_dir: Path,
    transcript_name: str = "executor.jsonl",
    stderr_name: str = "executor.stderr.log",
    sandbox_mode: str = "AUDITED_UNRESTRICTED",
    root: Path | None = None,
) -> dict:
    """Audit an isolated Codex JSONL transcript without trusting its summary."""
    root = root or repository_root()
    trial_dir = trial_dir.resolve()
    trial = validate_trial(trial_dir, root)
    transcript_path = resolve_inside(trial_dir, transcript_name)
    stderr_path = resolve_inside(trial_dir, stderr_name)
    if not transcript_path.is_file():
        raise FileNotFoundError(f"executor transcript is missing: {transcript_path}")
    if not stderr_path.is_file():
        raise FileNotFoundError(f"executor stderr log is missing: {stderr_path}")

    commands = []
    completed_commands = 0
    failed_commands = 0
    declined_commands = 0
    max_declared_repairs = 0
    turn_completed = False
    malformed_lines = 0
    final_agent_result = None
    ranking_change_indexes = []
    production_source_change_indexes = []
    finalization_started_index = None
    multiple_finalization_markers = False
    runner_prefix_hash_match = None
    result_commit_index = None
    result_commit_event = None
    multiple_result_commit_markers = False
    transcript_prefix_hasher = hashlib.sha256()
    trial_path_prefix = trial_dir.as_posix().lower().rstrip("/") + "/"

    def trial_relative_change_path(value: object) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        normalized = value.strip().replace("\\", "/").lower()
        if normalized.startswith(trial_path_prefix):
            return normalized[len(trial_path_prefix):]
        if re.match(r"^[a-z]:/", normalized) or normalized.startswith("/mnt/"):
            return None
        while normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized

    # JSONL records are delimited only by physical LF/CRLF bytes.  str.splitlines()
    # also splits valid JSON string data on Unicode U+2028/U+2029, which can occur
    # in minified JavaScript captured in command output and creates a false audit
    # failure.  TextIO iteration preserves those code points inside the record.
    with transcript_path.open(encoding="utf-8", newline="") as transcript:
        for event_index, line in enumerate(transcript):
            if not line.strip():
                transcript_prefix_hasher.update(line.encode("utf-8"))
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                malformed_lines += 1
                transcript_prefix_hasher.update(line.encode("utf-8"))
                continue
            if event.get("type") == "runner.finalization_started":
                if finalization_started_index is not None:
                    multiple_finalization_markers = True
                finalization_started_index = event_index
                expected_prefix_hash = event.get("search_transcript_sha256")
                runner_prefix_hash_match = (
                    isinstance(expected_prefix_hash, str)
                    and transcript_prefix_hasher.hexdigest() == expected_prefix_hash
                )
            if event.get("type") == "runner.result_committed":
                if result_commit_index is not None:
                    multiple_result_commit_markers = True
                result_commit_index = event_index
                result_commit_event = event
            transcript_prefix_hasher.update(line.encode("utf-8"))
            if event.get("type") == "turn.completed":
                turn_completed = True
            item = event.get("item") or {}
            if (
                event.get("type") == "item.completed"
                and item.get("type") == "file_change"
                and item.get("status") == "completed"
            ):
                for change in item.get("changes") or []:
                    relative_path = trial_relative_change_path(change.get("path"))
                    if relative_path == "evidence/opportunity-ranking.json":
                        ranking_change_indexes.append(event_index)
                    elif relative_path and relative_path.startswith("source/"):
                        production_source_change_indexes.append(event_index)
            if (
                event.get("type") == "item.started"
                and item.get("type") == "command_execution"
            ):
                commands.append(str(item.get("command", "")))
            if (
                event.get("type") == "item.completed"
                and item.get("type") == "command_execution"
            ):
                status = item.get("status")
                if status == "completed":
                    completed_commands += 1
                    if item.get("exit_code") not in (None, 0):
                        failed_commands += 1
                elif status == "failed":
                    failed_commands += 1
                elif status == "declined":
                    declined_commands += 1
            if (
                event.get("type") == "item.completed"
                and item.get("type") == "agent_message"
            ):
                try:
                    message = json.loads(item.get("text", ""))
                except (json.JSONDecodeError, TypeError):
                    continue
                final_agent_result = message
                declared = message.get("technical_repair_attempts")
                if isinstance(declared, int):
                    max_declared_repairs = max(max_declared_repairs, declared)

    normalized = "\n".join(commands)
    forbidden_patterns = {
        "NETWORK_COMMAND": r"(?i)(Invoke-WebRequest|curl(?:\.exe)?\s|wget\s|https?://|ssh\s|scp\s)",
        "REMOTE_GIT_COMMAND": r"(?i)git\s+(fetch|clone|pull|remote)\b",
        "PARENT_TRAVERSAL": r"(?<!\.)\.\.[\\/]",
    }
    violations = [
        name for name, pattern in forbidden_patterns.items() if re.search(pattern, normalized)
    ]
    if multiple_finalization_markers:
        violations.append("MULTIPLE_FINALIZATION_MARKERS")
    if multiple_result_commit_markers:
        violations.append("MULTIPLE_RESULT_COMMIT_MARKERS")
    if finalization_started_index is not None and not runner_prefix_hash_match:
        violations.append("RUNNER_PHASE_PREFIX_MISMATCH")
    trial_windows = str(trial_dir).lower()
    trial_wsl = "/mnt/" + trial_windows[0] + trial_windows[2:].replace("\\", "/")
    external_paths = []
    for command in commands:
        for match in re.findall(r"(?i)[a-z]:\\[^\s'\";]+", command):
            lowered = match.rstrip(".,)").lower()
            while "\\\\" in lowered:
                lowered = lowered.replace("\\\\", "\\")
            if lowered.startswith(trial_windows):
                continue
            if "codex-runtimes\\codex-primary-runtime" in lowered:
                continue
            external_paths.append(hashlib.sha256(lowered.encode()).hexdigest())
        for match in re.findall(r"/mnt/[a-z]/[^\s'\";]+", command):
            lowered = match.rstrip(".,)").lower()
            if not lowered.startswith(trial_wsl):
                external_paths.append(hashlib.sha256(lowered.encode()).hexdigest())
    if external_paths:
        violations.append("EXTERNAL_DATA_PATH")
    if malformed_lines:
        violations.append("MALFORMED_TRANSCRIPT")

    ranking_change_index = (
        max(ranking_change_indexes) if ranking_change_indexes else None
    )
    first_source_change_index = (
        min(production_source_change_indexes)
        if production_source_change_indexes
        else None
    )
    ranking_preceded_source_edit = None
    if first_source_change_index is not None:
        ranking_preceded_source_edit = (
            ranking_change_index is not None
            and ranking_change_index < first_source_change_index
        )
        if trial.get("frontier_contract") is not None and not ranking_preceded_source_edit:
            violations.append(
                "OPPORTUNITY_RANKING_NOT_FROZEN_BEFORE_SOURCE_EDIT"
            )
    source_change_after_finalization = None
    if finalization_started_index is not None:
        source_change_after_finalization = any(
            index > finalization_started_index
            for index in production_source_change_indexes
        )
        if source_change_after_finalization:
            violations.append("PRODUCTION_SOURCE_EDIT_DURING_FINALIZATION")

    repair_lower_bound = max(failed_commands, declined_commands, max_declared_repairs)
    if repair_lower_bound > trial["budget"]["max_technical_repairs"]:
        violations.append("TECHNICAL_REPAIR_BUDGET_EXCEEDED")
    result_path = trial_dir / "result.json"
    result_identity = identity_for(result_path, trial_dir) if result_path.is_file() else None
    result_commit_hash_match = None
    if result_commit_event is not None:
        draft_path = trial_dir / "finalizer_draft.json"
        closure_path = trial_dir / "evidence" / "frontier-closure.json"
        result_commit_hash_match = (
            finalization_started_index is not None
            and result_commit_index is not None
            and result_commit_index > finalization_started_index
            and draft_path.is_file()
            and closure_path.is_file()
            and result_path.is_file()
            and result_commit_event.get("draft_sha256") == sha256_file(draft_path)
            and result_commit_event.get("frontier_closure_sha256")
            == sha256_file(closure_path)
            and result_commit_event.get("result_sha256") == sha256_file(result_path)
        )
        if not result_commit_hash_match:
            violations.append("RUNNER_RESULT_COMMIT_MISMATCH")
    if not turn_completed:
        violations.append("TURN_NOT_COMPLETED")
    if result_identity is None:
        violations.append("RESULT_MISSING")
    else:
        result_errors = validate_json_file(
            result_path, root / "schemas" / "community_trial_result.schema.json"
        )
        if result_errors:
            violations.append("RESULT_SCHEMA_INVALID")
        elif final_agent_result != read_object(result_path):
            violations.append("RESULT_TRANSCRIPT_MISMATCH")

    violations = sorted(set(violations))
    receipt = {
        "schema_version": EXECUTION_AUDIT_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "TRANSCRIPT_AND_RESULT_INTEGRITY_ONLY",
        "status": "PASS" if not violations else "FAIL",
        "sandbox_mode": sandbox_mode,
        "auditor_identity": {
            "implementation": identity_for(
                root / "scripts" / "community_evaluation.py", root
            ),
            "contract": identity_for(
                root / "schemas" / "community_trial_execution_audit.schema.json",
                root,
            ),
        },
        "trial_identity": identity_for(trial_dir / "trial.json", trial_dir),
        "transcript_identity": identity_for(transcript_path, trial_dir),
        "stderr_identity": identity_for(stderr_path, trial_dir),
        "result_identity": result_identity,
        "observations": {
            "command_count": len(commands),
            "completed_command_count": completed_commands,
            "failed_command_count": failed_commands,
            "declined_command_count": declined_commands,
            "max_agent_declared_technical_repairs": max_declared_repairs,
            "technical_repair_lower_bound": repair_lower_bound,
            "turn_completed": turn_completed,
            "malformed_line_count": malformed_lines,
            "opportunity_ranking_change_index": ranking_change_index,
            "first_production_source_change_index": first_source_change_index,
            "ranking_preceded_production_edit": ranking_preceded_source_edit,
            "finalization_started_index": finalization_started_index,
            "source_change_after_finalization": source_change_after_finalization,
            "runner_prefix_hash_match": runner_prefix_hash_match,
            "result_commit_index": result_commit_index,
            "result_commit_hash_match": result_commit_hash_match,
            "external_path_hashes": sorted(set(external_paths)),
        },
        "violations": violations,
    }
    errors = validate_instance(
        receipt,
        read_object(root / "schemas" / "community_trial_execution_audit.schema.json"),
    )
    if errors:
        raise ValueError("invalid execution audit: " + "; ".join(errors))
    atomic_json(trial_dir / "execution_audit.json", receipt)
    return receipt


def materialize_trial(
    suite_path: Path,
    corpus: Path,
    task_id: str,
    arm: str,
    repeat_index: int,
    output: Path,
    root: Path | None = None,
) -> dict:
    root = root or repository_root()
    validate_suite(suite_path, corpus, root)
    if arm not in ARMS:
        raise ValueError(f"arm must be one of {ARMS}")
    suite_path = suite_path.resolve()
    suite = read_object(suite_path)
    if repeat_index < 1 or repeat_index > suite["protocol"]["repeats"]:
        raise ValueError("repeat index is outside the frozen protocol")
    task = next((item for item in suite["tasks"] if item["task_id"] == task_id), None)
    if task is None:
        raise ValueError(f"unknown task_id: {task_id}")
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"trial directory is not empty: {output}")
    (output / "input").mkdir(parents=True, exist_ok=True)
    # Executors are required to retain measurements here. Materializing the
    # directory avoids charging one arm a repair merely because its first
    # read-only inspection happens before it writes evidence.
    (output / "evidence").mkdir(parents=True, exist_ok=True)

    suite_base = suite_path.parent
    task_source = validate_identity(suite_base, task["packet"], "task packet")
    prompt_source = validate_identity(
        suite_base, suite["protocol"]["prompt_identity"], "trial prompt"
    )
    environment_source = validate_identity(
        suite_base, suite["protocol"]["environment_identity"], "runtime environment"
    )
    task_target = output / "input" / "task.json"
    prompt_target = output / "input" / "prompt.md"
    environment_target = output / "input" / "environment.json"
    result_schema_target = output / "input" / "result.schema.json"
    executor_prompt_target = output / "input" / "executor.md"
    frontier_contract_target = output / "input" / "frontier_contract.json"
    ranking_schema_target = output / "input" / "opportunity-ranking.schema.json"
    closure_schema_target = output / "input" / "frontier-closure.schema.json"
    shutil.copyfile(task_source, task_target)
    shutil.copyfile(prompt_source, prompt_target)
    shutil.copyfile(environment_source, environment_target)
    shutil.copyfile(
        root / "schemas" / "community_trial_result.schema.json",
        result_schema_target,
    )
    shutil.copyfile(
        root / "knowledge" / "community" / "executor_prompt.md",
        executor_prompt_target,
    )
    shutil.copyfile(
        root / "schemas" / "community_opportunity_ranking.schema.json",
        ranking_schema_target,
    )
    shutil.copyfile(
        root / "schemas" / "community_frontier_closure.schema.json",
        closure_schema_target,
    )
    build_frontier_contract(
        task_target,
        frontier_contract_target,
        suite["protocol"]["minimum_material_speedup"] - 1.0,
        root,
    )

    support_identities = []
    if task.get("support"):
        (output / "harness").mkdir(parents=True, exist_ok=True)
        for item in task["support"]:
            source = validate_identity(suite_base, item["source"], "task support")
            target = resolve_inside(output / "harness", item["target"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            support_identities.append(identity_for(target, output))

    graph_identity = None
    method_identity = None
    prior_outcome_identity = None
    prior_context_identity = None
    prior_shortlist_identity = None
    knowledge_policy = "WITHHELD"
    method_policy = "WITHHELD"
    prior_outcome_policy = "WITHHELD"
    if arm == "COMMUNITY_AUGMENTED":
        (output / "knowledge").mkdir(parents=True, exist_ok=True)
        graph_source = validate_identity(
            suite_base, suite["training_graph"], "training graph"
        )
        graph_target = output / "knowledge" / "community_graph.json"
        shutil.copyfile(graph_source, graph_target)
        graph_identity = identity_for(graph_target, output)
        knowledge_policy = "FROZEN_GRAPH_ONLY"
        if suite.get("training_methods"):
            method_source = validate_identity(
                suite_base, suite["training_methods"], "training method snapshot"
            )
            method_target = output / "knowledge" / "methods.json"
            shutil.copyfile(method_source, method_target)
            method_identity = identity_for(method_target, output)
            method_policy = "FROZEN_SNAPSHOT_ONLY"
        prior_outcome_target = None
        if suite.get("training_prior_outcomes"):
            prior_outcome_source = validate_identity(
                suite_base,
                suite["training_prior_outcomes"],
                "training prior outcome ledger",
            )
            prior_outcome_target = output / "knowledge" / "prior_outcomes.json"
            shutil.copyfile(prior_outcome_source, prior_outcome_target)
            prior_outcome_identity = identity_for(prior_outcome_target, output)
            prior_outcome_policy = "FROZEN_LEDGER_ONLY"
        prior_context_target = None
        if task.get("prior_context_distinction"):
            prior_context_source = validate_identity(
                suite_base,
                task["prior_context_distinction"],
                "prior context distinction",
            )
            prior_context_target = (
                output / "knowledge" / "prior_context_distinction.json"
            )
            shutil.copyfile(prior_context_source, prior_context_target)
            prior_context_identity = identity_for(prior_context_target, output)
        shortlist_target = output / "knowledge" / "prior_shortlist.json"
        build_prior_shortlist(
            task_target,
            environment_target,
            graph_target,
            method_target if method_identity is not None else None,
            shortlist_target,
            root,
            prior_outcome_target,
            prior_context_target,
        )
        prior_shortlist_identity = identity_for(shortlist_target, output)

    trial_id = f"{suite['suite_id']}.{task_id}.r{repeat_index}.{arm.lower()}"
    manifest = {
        "schema_version": TRIAL_SCHEMA,
        "trial_id": trial_id,
        "created_at": now(),
        "suite_identity": {
            "path": str(suite_path),
            "sha256": sha256_file(suite_path),
        },
        "suite_id": suite["suite_id"],
        "task_id": task_id,
        "repeat_index": repeat_index,
        "arm": arm,
        "status": "MATERIALIZED",
        "budget": suite["protocol"]["budgets"],
        "success_thresholds": {
            "minimum_material_speedup": suite["protocol"][
                "minimum_material_speedup"
            ]
        },
        "access_policy": {
            "network": "DISABLED",
            "community_knowledge": knowledge_policy,
            "method_knowledge": method_policy,
            "prior_outcome_knowledge": prior_outcome_policy,
        },
        "source_checkout": {
            "repository": task["repository"],
            "revision": task["base_revision"],
        },
        "task_input": identity_for(task_target, output),
        "prompt_input": identity_for(prompt_target, output),
        "environment_input": identity_for(environment_target, output),
        "result_contract": identity_for(result_schema_target, output),
        "executor_prompt": identity_for(executor_prompt_target, output),
        "frontier_contract": identity_for(frontier_contract_target, output),
        "opportunity_ranking_contract": identity_for(
            ranking_schema_target, output
        ),
        "frontier_closure_contract": identity_for(closure_schema_target, output),
        "task_support": support_identities,
        "community_graph": graph_identity,
        "method_snapshot": method_identity,
        "prior_outcome_ledger": prior_outcome_identity,
        "prior_context_distinction": prior_context_identity,
        "prior_shortlist": prior_shortlist_identity,
        "knowledge_realization_required": arm == "COMMUNITY_AUGMENTED",
    }
    errors = validate_instance(
        manifest,
        read_object(root / "schemas" / "community_evaluation_trial.schema.json"),
    )
    if errors:
        raise ValueError("invalid materialized trial: " + "; ".join(errors))
    atomic_json(output / "trial.json", manifest)
    return manifest


def schedule_key(seed: int, *parts: object) -> str:
    value = ":".join([str(seed), *(str(part) for part in parts)])
    return hashlib.sha256(value.encode()).hexdigest()


def planned_trials(suite: dict) -> list[tuple[str, int, str]]:
    seed = int(suite["protocol"]["random_seed"])
    blocks = [
        (task["task_id"], repeat_index)
        for task in suite["tasks"]
        for repeat_index in range(1, int(suite["protocol"]["repeats"]) + 1)
    ]
    blocks.sort(key=lambda item: schedule_key(seed, *item))
    plan = []
    for task_id, repeat_index in blocks:
        arms = sorted(
            ARMS,
            key=lambda arm: schedule_key(seed, task_id, repeat_index, arm),
        )
        plan.extend((task_id, repeat_index, arm) for arm in arms)
    return plan


def validate_schedule(
    schedule_path: Path, root: Path | None = None
) -> dict:
    root = root or repository_root()
    schedule_path = schedule_path.resolve()
    errors = validate_json_file(
        schedule_path,
        root / "schemas" / "community_evaluation_schedule.schema.json",
    )
    if errors:
        raise ValueError("invalid evaluation schedule: " + "; ".join(errors))
    schedule = read_object(schedule_path)
    suite_identity = schedule["suite_identity"]
    suite_path = Path(suite_identity["path"]).resolve()
    if not suite_path.is_file() or sha256_file(suite_path) != suite_identity["sha256"]:
        raise ValueError("evaluation schedule suite identity is stale")
    suite = read_object(suite_path)
    if schedule["random_seed"] != suite["protocol"]["random_seed"]:
        raise ValueError("evaluation schedule random seed differs from suite")
    expected = planned_trials(suite)
    observed = [
        (entry["task_id"], entry["repeat_index"], entry["arm"])
        for entry in schedule["entries"]
    ]
    if observed != expected:
        raise ValueError("evaluation schedule order was edited or incompletely materialized")
    if [entry["order_index"] for entry in schedule["entries"]] != list(
        range(1, len(expected) + 1)
    ):
        raise ValueError("evaluation schedule order indices are not contiguous")
    for entry in schedule["entries"]:
        trial_dir = resolve_inside(schedule_path.parent, entry["trial_directory"])
        trial_manifest = trial_dir / "trial.json"
        if (
            not trial_manifest.is_file()
            or sha256_file(trial_manifest) != entry["trial_manifest_sha256"]
        ):
            raise ValueError(
                f"scheduled trial manifest changed: {entry['trial_directory']}"
            )
        validate_trial(trial_dir, root)
    return {
        "status": "PASS",
        "entry_count": len(expected),
        "random_seed": schedule["random_seed"],
    }


def materialize_suite(
    suite_path: Path,
    corpus: Path,
    output: Path,
    root: Path | None = None,
) -> dict:
    root = root or repository_root()
    validate_suite(suite_path, corpus, root)
    suite_path = suite_path.resolve()
    suite = read_object(suite_path)
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"schedule directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    entries = []
    for order_index, (task_id, repeat_index, arm) in enumerate(
        planned_trials(suite), start=1
    ):
        directory_name = (
            f"{order_index:03d}-{task_id}-r{repeat_index}-{arm.lower()}"
        )
        trial_dir = output / "trials" / directory_name
        materialize_trial(
            suite_path,
            corpus,
            task_id,
            arm,
            repeat_index,
            trial_dir,
            root,
        )
        entries.append(
            {
                "order_index": order_index,
                "task_id": task_id,
                "repeat_index": repeat_index,
                "arm": arm,
                "trial_directory": f"trials/{directory_name}",
                "trial_manifest_sha256": sha256_file(trial_dir / "trial.json"),
            }
        )
    schedule = {
        "schema_version": SCHEDULE_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "EXECUTION_ORDER_ONLY",
        "suite_identity": {
            "path": str(suite_path),
            "sha256": sha256_file(suite_path),
        },
        "random_seed": suite["protocol"]["random_seed"],
        "entries": entries,
    }
    schedule_path = output / "schedule.json"
    atomic_json(schedule_path, schedule)
    result = validate_schedule(schedule_path, root)
    return {**result, "schedule": str(schedule_path)}


def validate_trial(trial_dir: Path, root: Path | None = None) -> dict:
    root = root or repository_root()
    trial_dir = trial_dir.resolve()
    trial_path = trial_dir / "trial.json"
    errors = validate_json_file(
        trial_path, root / "schemas" / "community_evaluation_trial.schema.json"
    )
    if errors:
        raise ValueError("invalid trial manifest: " + "; ".join(errors))
    trial = read_object(trial_path)
    validate_identity(trial_dir, trial["task_input"], "trial task input")
    validate_identity(trial_dir, trial["prompt_input"], "trial prompt input")
    validate_identity(
        trial_dir, trial["environment_input"], "trial runtime environment"
    )
    validate_identity(trial_dir, trial["result_contract"], "trial result contract")
    validate_identity(trial_dir, trial["executor_prompt"], "trial executor prompt")
    frontier_contract = trial.get("frontier_contract")
    if frontier_contract is not None:
        frontier_contract_path = validate_identity(
            trial_dir, frontier_contract, "trial frontier contract"
        )
        frontier_errors = validate_json_file(
            frontier_contract_path,
            root / "schemas" / "community_frontier_contract.schema.json",
        )
        if frontier_errors:
            raise ValueError(
                "invalid trial frontier contract: " + "; ".join(frontier_errors)
            )
        for field, label in (
            (
                "opportunity_ranking_contract",
                "opportunity ranking contract",
            ),
            (
                "frontier_closure_contract",
                "frontier closure contract",
            ),
        ):
            if trial.get(field) is None:
                raise ValueError(f"trial frontier contract requires {label}")
            validate_identity(trial_dir, trial[field], f"trial {label}")
    for identity in trial.get("task_support", []):
        support_path = validate_identity(trial_dir, identity, "trial task support")
        try:
            support_path.relative_to((trial_dir / "harness").resolve())
        except ValueError as error:
            raise ValueError("trial task support is outside harness") from error
    source_checkout = trial["source_checkout"]
    if len(source_checkout["revision"]) != 40 or any(
        character not in "0123456789abcdef"
        for character in source_checkout["revision"]
    ):
        raise ValueError("trial source revision must be a full lowercase commit hash")
    graph = trial["community_graph"]
    methods = trial.get("method_snapshot")
    prior_outcomes = trial.get("prior_outcome_ledger")
    prior_context = trial.get("prior_context_distinction")
    if trial["arm"] == "CONTROL":
        if (
            graph is not None
            or methods is not None
            or prior_outcomes is not None
            or prior_context is not None
            or trial.get("prior_shortlist") is not None
            or (trial_dir / "knowledge").exists()
        ):
            raise ValueError("control trial must not contain community knowledge")
        if trial["access_policy"].get("prior_outcome_knowledge", "WITHHELD") != "WITHHELD":
            raise ValueError("control trial must withhold prior outcome knowledge")
    else:
        if graph is None:
            raise ValueError("community trial is missing its frozen graph")
        graph_path = validate_identity(
            trial_dir, graph, "trial community graph"
        )
        method_path = None
        if methods is not None:
            method_path = validate_identity(trial_dir, methods, "trial method snapshot")
            method_errors = validate_json_file(
                method_path,
                root / "schemas" / "optimization_method_snapshot.schema.json",
            )
            if method_errors:
                raise ValueError("invalid trial method snapshot: " + "; ".join(method_errors))
        prior_outcome_path = None
        if prior_outcomes is not None:
            prior_outcome_path = validate_identity(
                trial_dir, prior_outcomes, "trial prior outcome ledger"
            )
            prior_errors = validate_json_file(
                prior_outcome_path,
                root / "schemas" / "community_prior_outcome_ledger.schema.json",
            )
            if prior_errors:
                raise ValueError(
                    "invalid trial prior outcome ledger: " + "; ".join(prior_errors)
                )
            validate_prior_outcome_ledger_consistency(
                read_object(prior_outcome_path)
            )
            if trial["access_policy"].get("prior_outcome_knowledge") != "FROZEN_LEDGER_ONLY":
                raise ValueError(
                    "community trial prior outcome access policy is inconsistent"
                )
        elif trial["access_policy"].get("prior_outcome_knowledge", "WITHHELD") != "WITHHELD":
            raise ValueError(
                "community trial claims prior outcome access without a ledger"
            )
        prior_context_path = None
        if prior_context is not None:
            if prior_outcome_path is None:
                raise ValueError(
                    "trial prior context distinction requires an outcome ledger"
                )
            prior_context_path = validate_identity(
                trial_dir, prior_context, "trial prior context distinction"
            )
            validate_prior_context_distinction(
                prior_context_path, prior_outcome_path, trial["task_id"], root
            )
        shortlist = trial.get("prior_shortlist")
        if shortlist is not None:
            shortlist_path = validate_identity(
                trial_dir, shortlist, "trial prior shortlist"
            )
            shortlist_errors = validate_json_file(
                shortlist_path,
                root / "schemas" / "community_prior_shortlist.schema.json",
            )
            if shortlist_errors:
                raise ValueError(
                    "invalid trial prior shortlist: "
                    + "; ".join(shortlist_errors)
                )
            shortlist_record = read_object(shortlist_path)
            if shortlist_record["inputs"].get("prior_outcomes") != prior_outcomes:
                raise ValueError("prior shortlist outcome-ledger identity mismatch")
            if (
                shortlist_record["inputs"].get("prior_context_distinction")
                != prior_context
            ):
                raise ValueError("prior shortlist context-distinction identity mismatch")
            selected = {
                (kind, row["id"]): row
                for kind, rows in (
                    ("EVENT", shortlist_record["events"]),
                    ("METHOD", shortlist_record["methods"]),
                )
                for row in rows
            }
            for key, row in selected.items():
                outcome = row.get("prior_outcome")
                if outcome is None:
                    if prior_outcomes is not None:
                        raise ValueError(
                            f"prior shortlist lacks outcome routing for selected prior: {key}"
                        )
                    continue
                if (
                    outcome["routing_adjustment"] == "REQUIRE_CONTEXT_GUARD"
                    and not outcome["context_distinction_applied"]
                ):
                    raise ValueError(
                        f"guarded prior was selected without a context distinction: {key}"
                    )
            if prior_outcome_path is not None:
                with tempfile.TemporaryDirectory() as temporary:
                    expected_path = Path(temporary) / "prior_shortlist.json"
                    expected = build_prior_shortlist(
                        validate_identity(
                            trial_dir, trial["task_input"], "trial task input"
                        ),
                        validate_identity(
                            trial_dir,
                            trial["environment_input"],
                            "trial runtime environment",
                        ),
                        graph_path,
                        method_path,
                        expected_path,
                        root,
                        prior_outcome_path,
                        prior_context_path,
                    )
                observed_stable = {
                    key: value
                    for key, value in shortlist_record.items()
                    if key != "generated_at"
                }
                expected_stable = {
                    key: value
                    for key, value in expected.items()
                    if key != "generated_at"
                }
                if observed_stable != expected_stable:
                    raise ValueError(
                        "prior shortlist is stale or bypasses frozen outcome routing"
                    )
    return trial


def nullable_min(values: list[float]) -> float | None:
    return min(values) if values else None


def nullable_max(values: list[float]) -> float | None:
    return max(values) if values else None


def validate_frontier_closure(trial_dir: Path, trial: dict, result: dict,
                              root: Path) -> int | None:
    """Validate pre-registered search breadth and fail-closed stop accounting."""
    contract_identity = trial.get("frontier_contract")
    closure_identity = result.get("frontier_closure")
    if contract_identity is None:
        if closure_identity is not None:
            raise ValueError("frontier closure is forbidden without a frontier contract")
        return None
    if closure_identity is None:
        raise ValueError("frontier closure is required by the trial frontier contract")

    contract_path = validate_identity(
        trial_dir, contract_identity, "trial frontier contract"
    )
    closure_path = validate_identity(
        trial_dir, closure_identity, "trial frontier closure"
    )
    closure_schema_path = validate_identity(
        trial_dir,
        trial["frontier_closure_contract"],
        "trial frontier closure contract",
    )
    closure_errors = validate_json_file(closure_path, closure_schema_path)
    if closure_errors:
        raise ValueError("invalid frontier closure: " + "; ".join(closure_errors))
    contract = read_object(contract_path)
    validate_qualification_checkpoint(trial, result, contract)
    closure = read_object(closure_path)
    if closure["contract_identity"] != contract_identity:
        raise ValueError("frontier closure is bound to a different contract")

    ranking_path = validate_identity(
        trial_dir,
        closure["opportunity_ranking_identity"],
        "trial opportunity ranking",
    )
    ranking_schema_path = validate_identity(
        trial_dir,
        trial["opportunity_ranking_contract"],
        "trial opportunity ranking contract",
    )
    ranking_errors = validate_json_file(ranking_path, ranking_schema_path)
    if ranking_errors:
        raise ValueError("invalid opportunity ranking: " + "; ".join(ranking_errors))
    ranking = read_object(ranking_path)
    if ranking["contract_identity"] != contract_identity:
        raise ValueError("opportunity ranking is bound to a different contract")
    if ranking["created_at_seconds"] > result["elapsed_seconds"]:
        raise ValueError("opportunity ranking was created after the trial elapsed time")
    if closure["generated_at_seconds"] > result["elapsed_seconds"]:
        raise ValueError("frontier closure was generated after the trial elapsed time")

    ranked = ranking["architectures"]
    minimum = contract["policy"]["minimum_ranked_architectures"]
    if len(ranked) < minimum:
        raise ValueError("opportunity ranking is smaller than the frontier contract")
    ranked_ids = [item["architecture_id"] for item in ranked]
    if len(ranked_ids) != len(set(ranked_ids)):
        raise ValueError("opportunity ranking architecture ids must be unique")
    if [item["rank"] for item in ranked] != list(range(1, len(ranked) + 1)):
        raise ValueError("opportunity ranking ranks must be contiguous and ordered")
    required_dimensions = {
        item["dimension_id"] for item in contract["required_dimensions"]
    }
    covered_dimensions = {
        dimension
        for item in ranked
        for dimension in item["dimension_ids"]
    }
    missing_dimensions = sorted(required_dimensions - covered_dimensions)
    if missing_dimensions:
        raise ValueError(
            "opportunity ranking omits required dimensions: "
            + ", ".join(missing_dimensions)
        )
    for item in ranked:
        bound = item["upper_bound"]
        if (bound["kind"] == "QUANTIFIED") != (
            bound["maximum_speedup"] is not None
        ):
            raise ValueError(
                f"ranked architecture {item['architecture_id']} has inconsistent bound"
            )

    closure_rows = closure["architectures"]
    closure_by_id = {item["architecture_id"]: item for item in closure_rows}
    if len(closure_by_id) != len(closure_rows):
        raise ValueError("frontier closure architecture ids must be unique")
    if set(closure_by_id) != set(ranked_ids):
        raise ValueError("frontier closure must account for every frozen architecture")
    candidate_by_id = {
        item["candidate_id"]: item for item in result["candidates"]
    }
    referenced_candidates: set[str] = set()
    selected_rows = []
    search_deadline = (
        float(trial["budget"]["wall_clock_seconds"])
        * float(contract["policy"]["deadline_fraction"])
    )
    for architecture_id in ranked_ids:
        row = closure_by_id[architecture_id]
        unknown = sorted(set(row["candidate_ids"]) - set(candidate_by_id))
        if unknown:
            raise ValueError(
                f"frontier architecture {architecture_id} references unknown candidates: "
                + ", ".join(unknown)
            )
        referenced_candidates.update(row["candidate_ids"])
        status = row["status"]
        bound = row["current_upper_bound"]
        if (bound["kind"] == "QUANTIFIED") != (
            bound["maximum_speedup"] is not None
        ):
            raise ValueError(
                f"frontier architecture {architecture_id} has inconsistent bound"
            )
        if status in {"SELECTED", "EVALUATED"} and not row["candidate_ids"]:
            raise ValueError(
                f"frontier architecture {architecture_id} requires an evaluated candidate"
            )
        if status in {"DOMINATED", "INFEASIBLE"} and not row["evidence"]:
            raise ValueError(
                f"frontier architecture {architecture_id} requires closure evidence"
            )
        if status == "DOMINATED" and bound["kind"] != "QUANTIFIED":
            raise ValueError(
                f"frontier architecture {architecture_id} needs a quantified domination bound"
            )
        if status == "INFEASIBLE" and bound["kind"] == "UNKNOWN":
            raise ValueError(
                f"frontier architecture {architecture_id} needs structural infeasibility evidence"
            )
        for evidence in row["evidence"]:
            validate_identity(
                trial_dir, evidence, f"frontier evidence {architecture_id}"
            )
        if status == "SELECTED":
            selected_rows.append(row)
        if status == "DEADLINE_UNTESTED" and not (
            result["completion_status"] == "BUDGET_EXHAUSTED"
            or result["elapsed_seconds"] >= search_deadline
        ):
            raise ValueError(
                f"frontier architecture {architecture_id} used deadline before search cutoff"
            )
    if referenced_candidates != set(candidate_by_id):
        raise ValueError("frontier closure does not map every evaluated candidate")

    selected_id = closure["selected_candidate_id"]
    selected_speedup = closure["selected_speedup"]
    if selected_id is None:
        if selected_rows or selected_speedup is not None:
            raise ValueError("frontier closure has inconsistent null selection")
    else:
        if selected_id not in candidate_by_id or len(selected_rows) != 1:
            raise ValueError("frontier closure must identify one evaluated selection")
        if selected_id not in selected_rows[0]["candidate_ids"]:
            raise ValueError("selected candidate is not mapped to selected architecture")
        candidate_speedup = candidate_by_id[selected_id]["speedup"]
        if candidate_speedup is None or selected_speedup != candidate_speedup:
            raise ValueError("frontier selected speedup does not match candidate evidence")
        # Screening can expose a faster raw point that is not selectable: it
        # may violate a public per-shape guard, and only the pre-selected final
        # candidate receives the held-out pass.  Compare the selection against
        # other correctness- and held-out-accepted candidates, not every raw
        # correctness-passing measurement.
        accepted_speeds = [
            item["speedup"]
            for item in result["candidates"]
            if item["correctness"] == "PASS"
            and item["heldout_correctness"] == "PASS"
            and item["speedup"] is not None
        ]
        if not accepted_speeds or selected_speedup != max(accepted_speeds):
            raise ValueError(
                "frontier selection is not the best held-out-accepted candidate"
            )
        margin = float(contract["policy"]["material_gain_margin"])
        selected_bound = selected_rows[0]["current_upper_bound"]
        compile_attempts = sum(
            item["compile_attempts"] for item in result["candidates"]
        )
        measurement_attempts = sum(
            item["measurement_attempts"] for item in result["candidates"]
        )
        search_capacity_remains = (
            result["elapsed_seconds"] < search_deadline
            and len(result["candidates"]) < trial["budget"]["max_candidates"]
            and compile_attempts < trial["budget"]["max_compile_attempts"]
            and measurement_attempts < trial["budget"]["max_measurements"]
            and result["technical_repair_attempts"]
            < trial["budget"]["max_technical_repairs"]
            and result["causal_revisions"]
            < trial["budget"]["max_causal_revisions"]
        )
        selected_bound_open = (
            selected_bound["kind"] != "QUANTIFIED"
            or float(selected_bound["maximum_speedup"])
            > selected_speedup * (1.0 + margin)
        )
        if selected_bound_open and search_capacity_remains:
            raise ValueError(
                "selected architecture retains a material open bound while search capacity remains"
            )
        for row in closure_rows:
            if row["status"] != "DOMINATED":
                continue
            bound = row["current_upper_bound"]
            if (
                bound["kind"] == "QUANTIFIED"
                and float(bound["maximum_speedup"]) > selected_speedup * (1.0 + margin)
            ):
                raise ValueError(
                    f"frontier architecture {row['architecture_id']} remains materially open"
                )
    return len(ranked)


def validate_qualification_checkpoint(trial: dict, result: dict,
                                      contract: dict) -> None:
    """Reject optional exploration that bypassed the first shippable result."""
    if contract["policy"].get("qualification_checkpoint") != (
        "FIRST_MATERIAL_CORRECT_BEFORE_NEXT_CANDIDATE"
    ):
        return
    material_speedup = float(
        trial["success_thresholds"]["minimum_material_speedup"]
    )
    chronological = sorted(
        result["candidates"],
        key=lambda item: (item["proposed_at_seconds"], item["candidate_id"]),
    )
    for candidate, later in zip(chronological, chronological[1:]):
        if (
            candidate["correctness"] == "PASS"
            and candidate["speedup"] is not None
            and float(candidate["speedup"]) >= material_speedup
            and candidate["heldout_correctness"] != "PASS"
        ):
            raise ValueError(
                "qualification checkpoint bypassed before later candidate: "
                f"{candidate['candidate_id']} -> {later['candidate_id']}"
            )


def assess_trial(
    trial_dir: Path,
    root: Path | None = None,
    require_execution_audit: bool = False,
) -> dict:
    root = root or repository_root()
    trial_dir = trial_dir.resolve()
    trial = validate_trial(trial_dir, root)
    result_path = trial_dir / "result.json"
    errors = validate_json_file(
        result_path, root / "schemas" / "community_trial_result.schema.json"
    )
    if errors:
        raise ValueError("invalid trial result: " + "; ".join(errors))
    result = read_object(result_path)
    for field in ("trial_id", "task_id", "arm"):
        if result[field] != trial[field]:
            raise ValueError(f"trial result {field} does not match manifest")

    ranked_architecture_count = validate_frontier_closure(
        trial_dir, trial, result, root
    )

    if require_execution_audit:
        audit_path = trial_dir / "execution_audit.json"
        if not audit_path.is_file():
            raise ValueError("valid execution audit required: file is missing")
        audit_errors = validate_json_file(
            audit_path,
            root / "schemas" / "community_trial_execution_audit.schema.json",
        )
        if audit_errors:
            raise ValueError("valid execution audit required: " + "; ".join(audit_errors))
        audit = read_object(audit_path)
        if audit["status"] != "PASS":
            raise ValueError("passing execution audit required")
        validate_identity(
            root,
            audit["auditor_identity"]["implementation"],
            "execution auditor implementation",
        )
        validate_identity(
            root,
            audit["auditor_identity"]["contract"],
            "execution auditor contract",
        )
        if audit["trial_identity"] != identity_for(trial_dir / "trial.json", trial_dir):
            raise ValueError("execution audit is stale for trial manifest")
        if audit["result_identity"] != identity_for(result_path, trial_dir):
            raise ValueError("execution audit is stale for trial result")

    candidate_ids: set[str] = set()
    for candidate in result["candidates"]:
        candidate_id = candidate["candidate_id"]
        if candidate_id in candidate_ids:
            raise ValueError(f"duplicate candidate_id: {candidate_id}")
        candidate_ids.add(candidate_id)
        if candidate["evaluated_at_seconds"] < candidate["proposed_at_seconds"]:
            raise ValueError(f"candidate {candidate_id} was evaluated before proposal")
        if candidate["evaluated_at_seconds"] > result["elapsed_seconds"]:
            raise ValueError(f"candidate {candidate_id} exceeds observed wall time")
        if candidate["speedup"] is not None and candidate["measurement_attempts"] < 1:
            raise ValueError(f"candidate {candidate_id} has speedup without measurement")
        if (
            candidate["whole_model_speedup"] is not None
            and candidate["heldout_correctness"] == "NOT_RUN"
        ):
            raise ValueError(
                f"candidate {candidate_id} has whole-model speedup without held-out validation"
            )
        if candidate["upstream_ready"] and (
            candidate["correctness"] != "PASS"
            or candidate["heldout_correctness"] != "PASS"
            or not candidate["evidence"]
        ):
            raise ValueError(
                f"candidate {candidate_id} cannot be upstream-ready without complete evidence"
            )
        for identity in candidate["evidence"]:
            validate_identity(
                trial_dir, identity, f"candidate evidence {candidate_id}"
            )

    method_realization = result.get("method_realization")
    community_realization = result.get("knowledge_realization")
    guarded_prior_ids: set[tuple[str, str]] = set()
    context_exception_ids: set[tuple[str, str]] = set()
    if trial.get("prior_outcome_ledger") is not None:
        ledger_path = validate_identity(
            trial_dir, trial["prior_outcome_ledger"], "trial prior outcome ledger"
        )
        ledger = read_object(ledger_path)
        guarded_prior_ids = {
            (row["prior_kind"], row["prior_id"])
            for row in ledger["aggregates"]
            if row["routing_adjustment"] == "REQUIRE_CONTEXT_GUARD"
        }
    if trial.get("prior_context_distinction") is not None:
        distinction_path = validate_identity(
            trial_dir,
            trial["prior_context_distinction"],
            "trial prior context distinction",
        )
        context_exception_ids = {
            (row["prior_kind"], row["prior_id"])
            for row in read_object(distinction_path)["exceptions"]
        }
    community_disposition = None
    community_realized_candidate_count = 0
    if trial["arm"] == "CONTROL":
        if community_realization is not None:
            raise ValueError("community realization is forbidden in the control arm")
    elif trial.get("knowledge_realization_required") or community_realization is not None:
        if community_realization is None:
            raise ValueError("community realization is required in the augmented arm")
        graph_path = validate_identity(
            trial_dir, trial["community_graph"], "trial community graph"
        )
        available_event_ids = {
            item["event_id"] for item in read_object(graph_path)["nodes"]
        }
        inspected_event_ids = community_realization["inspected_event_ids"]
        selected_event_ids = community_realization["selected_event_ids"]
        unknown_inspected = sorted(set(inspected_event_ids) - available_event_ids)
        if unknown_inspected:
            raise ValueError(
                "community realization inspected unknown events: "
                + ", ".join(unknown_inspected)
            )
        if not set(selected_event_ids).issubset(inspected_event_ids):
            raise ValueError("selected community events must be inspected events")
        forbidden_guarded_events = {
            event_id
            for event_id in selected_event_ids
            if ("EVENT", event_id) in guarded_prior_ids
            and ("EVENT", event_id) not in context_exception_ids
        }
        if forbidden_guarded_events:
            raise ValueError(
                "selected community events bypassed a frozen context guard: "
                + ", ".join(sorted(forbidden_guarded_events))
            )
        realization_candidate_ids = community_realization["candidate_ids"]
        unknown_candidates = sorted(set(realization_candidate_ids) - candidate_ids)
        if unknown_candidates:
            raise ValueError(
                "community realization references unknown candidates: "
                + ", ".join(unknown_candidates)
            )
        for evidence in community_realization["evidence"]:
            validate_identity(trial_dir, evidence, "community realization evidence")
        community_disposition = community_realization["disposition"]
        if community_disposition == "PRIOR_GATE_CLOSED":
            if inspected_event_ids or selected_event_ids or realization_candidate_ids:
                raise ValueError(
                    "PRIOR_GATE_CLOSED cannot inspect, select, or realize an event"
                )
        elif community_disposition == "NO_RELEVANT_COMMUNITY_PRIOR":
            if selected_event_ids or realization_candidate_ids:
                raise ValueError(
                    "NO_RELEVANT_COMMUNITY_PRIOR cannot select or realize an event"
                )
        else:
            if not selected_event_ids or not realization_candidate_ids:
                raise ValueError(
                    "REALIZED_IN_CANDIDATE requires selected events and candidates"
                )
            if not community_realization["evidence"]:
                raise ValueError(
                    "realized community event requires hash-bound evidence"
                )
            community_realized_candidate_count = len(realization_candidate_ids)

    method_disposition = None
    method_realized_candidate_count = 0
    if trial.get("method_snapshot") is None:
        if method_realization is not None:
            raise ValueError("method realization is forbidden without a method snapshot")
    else:
        if method_realization is None:
            raise ValueError("method realization is required when a method snapshot is exposed")
        method_snapshot_path = validate_identity(
            trial_dir, trial["method_snapshot"], "trial method snapshot"
        )
        method_snapshot = read_object(method_snapshot_path)
        available_method_ids = set(method_snapshot["included_method_ids"])
        inspected_method_ids = method_realization["inspected_method_ids"]
        unknown_inspected = sorted(set(inspected_method_ids) - available_method_ids)
        if unknown_inspected:
            raise ValueError(
                "method realization inspected unknown methods: "
                + ", ".join(unknown_inspected)
            )
        selected_method_id = method_realization["selected_method_id"]
        disposition = method_realization["disposition"]
        realization_candidate_ids = method_realization["candidate_ids"]
        unknown_candidates = sorted(set(realization_candidate_ids) - candidate_ids)
        if unknown_candidates:
            raise ValueError(
                "method realization references unknown candidates: "
                + ", ".join(unknown_candidates)
            )
        for identity in method_realization["evidence"]:
            validate_identity(trial_dir, identity, "method realization evidence")
        if disposition == "NO_RELEVANT_METHOD_PRIOR":
            if (
                selected_method_id is not None
                or method_realization["instantiation"] is not None
                or realization_candidate_ids
            ):
                raise ValueError(
                    "NO_RELEVANT_METHOD_PRIOR cannot select, instantiate, or realize a method"
                )
        else:
            if selected_method_id is None or selected_method_id not in inspected_method_ids:
                raise ValueError(
                    "selected method must be one of the inspected snapshot methods"
                )
            if (
                ("METHOD", selected_method_id) in guarded_prior_ids
                and ("METHOD", selected_method_id) not in context_exception_ids
            ):
                raise ValueError(
                    "selected method bypassed a frozen context guard"
                )
            if method_realization["instantiation"] is None:
                raise ValueError("selected method requires an operator instantiation")
            if not method_realization["evidence"]:
                raise ValueError("selected method requires hash-bound realization evidence")
            if disposition == "REALIZED_IN_CANDIDATE" and not realization_candidate_ids:
                raise ValueError("realized method must reference at least one candidate")
        method_disposition = disposition
        if disposition == "REALIZED_IN_CANDIDATE":
            method_realized_candidate_count = len(realization_candidate_ids)

    budget = trial["budget"]
    usage = {
        "elapsed_seconds": result["elapsed_seconds"],
        "candidate_count": len(result["candidates"]),
        "compile_attempts": sum(
            item["compile_attempts"] for item in result["candidates"]
        ),
        "measurement_attempts": sum(
            item["measurement_attempts"] for item in result["candidates"]
        ),
        "technical_repair_attempts": result["technical_repair_attempts"],
        "causal_revisions": result["causal_revisions"],
    }
    limits = {
        "elapsed_seconds": "wall_clock_seconds",
        "candidate_count": "max_candidates",
        "compile_attempts": "max_compile_attempts",
        "measurement_attempts": "max_measurements",
        "technical_repair_attempts": "max_technical_repairs",
        "causal_revisions": "max_causal_revisions",
    }
    exceeded = [
        name for name, budget_name in limits.items() if usage[name] > budget[budget_name]
    ]
    if exceeded:
        raise ValueError("trial exceeded frozen budget: " + ", ".join(exceeded))

    correct = [
        item for item in result["candidates"] if item["correctness"] == "PASS"
    ]
    accepted = correct
    if trial.get("frontier_contract") is not None:
        closure_path = validate_identity(
            trial_dir, result["frontier_closure"], "trial frontier closure"
        )
        selected_candidate_id = read_object(closure_path)["selected_candidate_id"]
        accepted = [
            item for item in correct
            if item["candidate_id"] == selected_candidate_id
        ]
    minimum_material_speedup = trial["success_thresholds"][
        "minimum_material_speedup"
    ]
    improved = [
        item
        for item in accepted
        if item["speedup"] is not None
        and item["speedup"] >= minimum_material_speedup
    ]
    heldout = [
        item for item in correct if item["heldout_correctness"] == "PASS"
    ]
    environment = read_object(
        validate_identity(
            trial_dir, trial["environment_input"], "trial runtime environment"
        )
    )
    constraints = " ".join(
        str(item).lower() for item in environment.get("known_constraints", [])
    )
    integration_environment_missing = (
        trial["source_checkout"]["repository"].lower().endswith("/vllm")
        and "no installed" in constraints
        and (
            "development environment" in constraints
            or "integration environment" in constraints
        )
    )
    assessment = {
        "schema_version": ASSESSMENT_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "SINGLE_TRIAL_OBSERVATION",
        "trial_identity": identity_for(trial_dir / "trial.json", trial_dir),
        "result_identity": identity_for(result_path, trial_dir),
        "suite_id": trial["suite_id"],
        "task_id": trial["task_id"],
        "repeat_index": trial["repeat_index"],
        "arm": trial["arm"],
        "success_thresholds": trial["success_thresholds"],
        "metrics": {
            "time_to_first_correct_seconds": nullable_min(
                [item["evaluated_at_seconds"] for item in correct]
            ),
            "time_to_first_improvement_seconds": nullable_min(
                [item["evaluated_at_seconds"] for item in improved]
            ),
            "best_speedup": nullable_max(
                [
                    float(item["speedup"])
                    for item in accepted
                    if item["speedup"] is not None
                ]
            ),
            "architecture_family_count": len(
                {item["architecture_family"] for item in result["candidates"]}
            ),
            "heldout_pass_count": len(heldout),
            "best_whole_model_speedup": nullable_max(
                [
                    float(item["whole_model_speedup"])
                    for item in heldout
                    if item["whole_model_speedup"] is not None
                ]
            ),
            "upstream_ready_count": (
                0
                if integration_environment_missing
                else sum(1 for item in heldout if item["upstream_ready"])
            ),
            "method_realization_disposition": method_disposition,
            "method_realized_candidate_count": method_realized_candidate_count,
            "frontier_contract_passed": ranked_architecture_count is not None,
            "ranked_architecture_count": ranked_architecture_count,
            "community_realization_disposition": community_disposition,
            "community_realized_candidate_count": community_realized_candidate_count,
        },
        "budget_usage": usage,
    }
    assessment_errors = validate_instance(
        assessment,
        read_object(root / "schemas" / "community_trial_assessment.schema.json"),
    )
    if assessment_errors:
        raise ValueError("invalid trial assessment: " + "; ".join(assessment_errors))
    atomic_json(trial_dir / "assessment.json", assessment)
    return assessment


def difference(control: float | int | None, community: float | int | None) -> float | None:
    if control is None or community is None:
        return None
    return float(community) - float(control)


def seconds_saved(control: float | None, community: float | None) -> float | None:
    if control is None or community is None:
        return None
    return float(control) - float(community)


def compare_trials(
    control_dir: Path,
    community_dir: Path,
    output: Path,
    root: Path | None = None,
) -> dict:
    root = root or repository_root()
    control = assess_trial(control_dir, root)
    community = assess_trial(community_dir, root)
    if control["arm"] != "CONTROL" or community["arm"] != "COMMUNITY_AUGMENTED":
        raise ValueError("compare requires CONTROL then COMMUNITY_AUGMENTED")
    for field in ("suite_id", "task_id", "repeat_index"):
        if control[field] != community[field]:
            raise ValueError(f"paired trials differ in {field}")
    if control["success_thresholds"] != community["success_thresholds"]:
        raise ValueError("paired trials differ in success thresholds")
    control_metrics = control["metrics"]
    community_metrics = community["metrics"]
    community_event_prior_realized = (
        community_metrics.get("community_realization_disposition")
        == "REALIZED_IN_CANDIDATE"
    )
    method_prior_realized = (
        community_metrics.get("method_realization_disposition")
        == "REALIZED_IN_CANDIDATE"
    )
    any_prior_realized = community_event_prior_realized or method_prior_realized
    control_path = control_dir.resolve() / "assessment.json"
    community_path = community_dir.resolve() / "assessment.json"
    report = {
        "schema_version": REPORT_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "PAIRED_TRIAL_ONLY",
        "suite_id": control["suite_id"],
        "task_id": control["task_id"],
        "repeat_index": control["repeat_index"],
        "control_assessment": {
            "path": str(control_path),
            "sha256": sha256_file(control_path),
        },
        "community_assessment": {
            "path": str(community_path),
            "sha256": sha256_file(community_path),
        },
        "deltas": {
            "time_to_first_correct_seconds_saved": seconds_saved(
                control_metrics["time_to_first_correct_seconds"],
                community_metrics["time_to_first_correct_seconds"],
            ),
            "time_to_first_improvement_seconds_saved": seconds_saved(
                control_metrics["time_to_first_improvement_seconds"],
                community_metrics["time_to_first_improvement_seconds"],
            ),
            "best_speedup_gain": difference(
                control_metrics["best_speedup"], community_metrics["best_speedup"]
            ),
            "architecture_family_count_gain": difference(
                control_metrics["architecture_family_count"],
                community_metrics["architecture_family_count"],
            ),
            "heldout_pass_count_gain": difference(
                control_metrics["heldout_pass_count"],
                community_metrics["heldout_pass_count"],
            ),
            "best_whole_model_speedup_gain": difference(
                control_metrics["best_whole_model_speedup"],
                community_metrics["best_whole_model_speedup"],
            ),
            "upstream_ready_count_gain": difference(
                control_metrics["upstream_ready_count"],
                community_metrics["upstream_ready_count"],
            ),
        },
        "treatment_fidelity": {
            "community_event_prior_realized": community_event_prior_realized,
            "method_prior_realized": method_prior_realized,
            "any_prior_realized": any_prior_realized,
            "causal_interpretation": (
                "TREATMENT_REALIZED"
                if any_prior_realized
                else "ASSIGNMENT_WITHOUT_REALIZED_PRIOR"
            ),
        },
    }
    errors = validate_instance(
        report, read_object(root / "schemas" / "community_ab_report.schema.json")
    )
    if errors:
        raise ValueError("invalid A/B report: " + "; ".join(errors))
    atomic_json(output.resolve(), report)
    return report


def exact_two_sided_sign_p(wins: int, losses: int) -> float | None:
    observations = wins + losses
    if observations == 0:
        return None
    tail = min(wins, losses)
    probability = sum(math.comb(observations, k) for k in range(tail + 1))
    return min(1.0, 2.0 * probability / (2**observations))


def summarize_pair_rows(rows: list[dict]) -> dict:
    if len(rows) < 2:
        raise ValueError("at least two paired repeats are required")

    def values(field: str) -> list[float]:
        return [float(row[field]) for row in rows if row[field] is not None]

    def median_or_none(field: str) -> float | None:
        observed = values(field)
        return float(median(observed)) if observed else None

    def wins(field: str) -> tuple[int, int, int]:
        observed = values(field)
        return (
            sum(value > 0 for value in observed),
            sum(value < 0 for value in observed),
            sum(value == 0 for value in observed),
        )

    first_wins, first_losses, first_ties = wins("first_correct_seconds_saved")
    family_wins, family_losses, family_ties = wins("architecture_family_gain")
    speed_wins, speed_losses, speed_ties = wins("best_speedup_gain")
    elapsed_wins, elapsed_losses, elapsed_ties = wins("elapsed_seconds_saved")
    return {
        "paired_medians": {
            "elapsed_seconds_saved": median_or_none("elapsed_seconds_saved"),
            "time_to_first_correct_seconds_saved": median_or_none(
                "first_correct_seconds_saved"
            ),
            "architecture_family_count_gain": median_or_none(
                "architecture_family_gain"
            ),
            "best_speedup_gain": median_or_none("best_speedup_gain"),
        },
        "arm_medians": {
            arm: {
                "elapsed_seconds": median_or_none(f"{arm}_elapsed_seconds"),
                "time_to_first_correct_seconds": median_or_none(
                    f"{arm}_first_correct_seconds"
                ),
                "architecture_family_count": median_or_none(
                    f"{arm}_architecture_family_count"
                ),
                "best_speedup": median_or_none(f"{arm}_best_speedup"),
            }
            for arm in ("control", "community_augmented")
        },
        "paired_wins": {
            "faster_time_to_first_correct": {
                "community": first_wins,
                "control": first_losses,
                "ties": first_ties,
                "two_sided_exact_sign_p": exact_two_sided_sign_p(
                    first_wins, first_losses
                ),
            },
            "greater_architecture_family_coverage": {
                "community": family_wins,
                "control": family_losses,
                "ties": family_ties,
            },
            "higher_best_speedup": {
                "community": speed_wins,
                "control": speed_losses,
                "ties": speed_ties,
            },
            "lower_elapsed_seconds": {
                "community": elapsed_wins,
                "control": elapsed_losses,
                "ties": elapsed_ties,
            },
        },
        "material_improvement_repeats": {
            "control": sum(row["control_material_improvement"] for row in rows),
            "community_augmented": sum(
                row["community_augmented_material_improvement"] for row in rows
            ),
        },
    }


def aggregate_pair_reports(
    pair_paths: list[Path], output: Path, root: Path | None = None
) -> dict:
    root = root or repository_root()
    if len(pair_paths) < 2:
        raise ValueError("at least two pair reports are required")
    reports = []
    rows = []
    suite_id = None
    task_id = None
    repeats = set()
    for raw_path in pair_paths:
        pair_path = raw_path.resolve()
        errors = validate_json_file(
            pair_path, root / "schemas" / "community_ab_report.schema.json"
        )
        if errors:
            raise ValueError("invalid paired report: " + "; ".join(errors))
        report = read_object(pair_path)
        suite_id = suite_id or report["suite_id"]
        task_id = task_id or report["task_id"]
        if report["suite_id"] != suite_id or report["task_id"] != task_id:
            raise ValueError("pair reports must belong to one suite and task")
        if report["repeat_index"] in repeats:
            raise ValueError("duplicate repeat index in pair reports")
        repeats.add(report["repeat_index"])
        assessments = {}
        for arm, key in (
            ("CONTROL", "control_assessment"),
            ("COMMUNITY_AUGMENTED", "community_assessment"),
        ):
            assessment_path = validate_identity(
                pair_path.parent, report[key], f"{arm} assessment"
            )
            assessment_errors = validate_json_file(
                assessment_path,
                root / "schemas" / "community_trial_assessment.schema.json",
            )
            if assessment_errors:
                raise ValueError(
                    "invalid trial assessment: " + "; ".join(assessment_errors)
                )
            assessment = read_object(assessment_path)
            if (
                assessment["arm"] != arm
                or assessment["suite_id"] != suite_id
                or assessment["task_id"] != task_id
                or assessment["repeat_index"] != report["repeat_index"]
            ):
                raise ValueError("paired assessment identity does not match report")
            assessments[arm] = assessment
        control = assessments["CONTROL"]
        community = assessments["COMMUNITY_AUGMENTED"]
        control_metrics = control["metrics"]
        community_metrics = community["metrics"]
        rows.append(
            {
                "control_elapsed_seconds": control["budget_usage"]["elapsed_seconds"],
                "community_augmented_elapsed_seconds": community["budget_usage"][
                    "elapsed_seconds"
                ],
                "elapsed_seconds_saved": control["budget_usage"]["elapsed_seconds"]
                - community["budget_usage"]["elapsed_seconds"],
                "control_first_correct_seconds": control_metrics[
                    "time_to_first_correct_seconds"
                ],
                "community_augmented_first_correct_seconds": community_metrics[
                    "time_to_first_correct_seconds"
                ],
                "first_correct_seconds_saved": report["deltas"][
                    "time_to_first_correct_seconds_saved"
                ],
                "control_architecture_family_count": control_metrics[
                    "architecture_family_count"
                ],
                "community_augmented_architecture_family_count": community_metrics[
                    "architecture_family_count"
                ],
                "architecture_family_gain": report["deltas"][
                    "architecture_family_count_gain"
                ],
                "control_best_speedup": control_metrics["best_speedup"],
                "community_augmented_best_speedup": community_metrics["best_speedup"],
                "best_speedup_gain": report["deltas"]["best_speedup_gain"],
                "control_material_improvement": int(
                    control_metrics["time_to_first_improvement_seconds"] is not None
                ),
                "community_augmented_material_improvement": int(
                    community_metrics["time_to_first_improvement_seconds"] is not None
                ),
            }
        )
        reports.append(pair_path)

    output = output.resolve()
    summary = {
        "schema_version": REPEAT_SUMMARY_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "REPEATED_PAIRS_SINGLE_TASK",
        "suite_id": suite_id,
        "task_id": task_id,
        "repeat_count": len(rows),
        "pair_reports": [identity_for(path, output.parent) for path in reports],
        **summarize_pair_rows(rows),
    }
    errors = validate_instance(
        summary,
        read_object(root / "schemas" / "community_ab_repeat_summary.schema.json"),
    )
    if errors:
        raise ValueError("invalid repeat summary: " + "; ".join(errors))
    atomic_json(output, summary)
    return summary


META_DELTA_FIELDS = (
    "time_to_first_correct_seconds_saved",
    "time_to_first_improvement_seconds_saved",
    "best_speedup_gain",
    "architecture_family_count_gain",
    "heldout_pass_count_gain",
    "best_whole_model_speedup_gain",
    "upstream_ready_count_gain",
)


def pair_evidence_class(path: Path, report: dict, search_root: Path) -> str:
    fidelity = report.get("treatment_fidelity")
    if not isinstance(fidelity, dict):
        return "LEGACY_UNAUDITED"
    if fidelity.get("causal_interpretation") != "TREATMENT_REALIZED":
        return "ASSIGNMENT_ONLY"
    relative = path.resolve().relative_to(search_root.resolve()).as_posix().lower()
    return (
        "DIAGNOSTIC_REALIZED" if "diagnostic" in relative else "PRIMARY_REALIZED"
    )


def metric_meta_summary(reports: list[dict], field: str) -> dict:
    values = [
        float(report["deltas"][field])
        for report in reports
        if report["deltas"].get(field) is not None
    ]
    wins = sum(value > 0 for value in values)
    losses = sum(value < 0 for value in values)
    ties = sum(value == 0 for value in values)
    return {
        "observed": len(values),
        "community_wins": wins,
        "control_wins": losses,
        "ties": ties,
        "missing": len(reports) - len(values),
        "median_delta": float(median(values)) if values else None,
        "two_sided_exact_sign_p": exact_two_sided_sign_p(wins, losses),
    }


def build_ab_meta_analysis(
    search_root: Path, root: Path | None = None
) -> dict:
    """Inventory every pair report and separate assignment from realized treatment."""
    root = root or repository_root()
    search_root = search_root.resolve()
    if not search_root.is_dir():
        raise FileNotFoundError(f"A/B meta-analysis root is missing: {search_root}")
    rows = []
    primary_reports = []
    for path in sorted(search_root.rglob("*.json")):
        try:
            report = read_object(path)
        except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if report.get("schema_version") != REPORT_SCHEMA:
            continue
        evidence_class = pair_evidence_class(path, report, search_root)
        fidelity = report.get("treatment_fidelity")
        causal = (
            fidelity.get("causal_interpretation")
            if isinstance(fidelity, dict)
            else "LEGACY_UNAUDITED"
        )
        if evidence_class != "LEGACY_UNAUDITED":
            errors = validate_json_file(
                path, root / "schemas" / "community_ab_report.schema.json"
            )
            if errors:
                raise ValueError(
                    f"invalid non-legacy pair report {path}: " + "; ".join(errors)
                )
        row = {
            "path": path.relative_to(search_root).as_posix(),
            "sha256": sha256_file(path),
            "suite_id": str(report.get("suite_id", "")),
            "task_id": str(report.get("task_id", "")),
            "repeat_index": int(report.get("repeat_index", 0)),
            "evidence_class": evidence_class,
            "causal_interpretation": causal,
        }
        if row["repeat_index"] < 1:
            raise ValueError(f"pair report has invalid repeat index: {path}")
        rows.append(row)
        if evidence_class == "PRIMARY_REALIZED":
            primary_reports.append(report)
    classes = [row["evidence_class"] for row in rows]
    inventory = {
        "report_count": len(rows),
        "primary_realized_count": classes.count("PRIMARY_REALIZED"),
        "primary_task_count": len(
            {report["task_id"] for report in primary_reports}
        ),
        "diagnostic_realized_count": classes.count("DIAGNOSTIC_REALIZED"),
        "assignment_only_count": classes.count("ASSIGNMENT_ONLY"),
        "legacy_unaudited_count": classes.count("LEGACY_UNAUDITED"),
    }
    metrics = {
        field: metric_meta_summary(primary_reports, field)
        for field in META_DELTA_FIELDS
    }
    if (
        inventory["primary_realized_count"] < 8
        or inventory["primary_task_count"] < 4
    ):
        verdict = "INSUFFICIENT_PRIMARY_EVIDENCE"
    else:
        ttfc = metrics["time_to_first_correct_seconds_saved"]
        speedup = metrics["best_speedup_gain"]
        heldout = metrics["heldout_pass_count_gain"]
        advantage = (
            ttfc["community_wins"] > ttfc["control_wins"]
            and speedup["community_wins"] >= speedup["control_wins"]
            and heldout["control_wins"] == 0
        )
        verdict = "ADVANTAGE_OBSERVED" if advantage else "NO_ADVANTAGE_OBSERVED"
    result = {
        "schema_version": META_ANALYSIS_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "DESCRIPTIVE_CROSS_TASK_EVIDENCE_ONLY",
        "search_root": search_root.as_posix(),
        "policy": {
            "discovery": "RECURSIVE_SCHEMA_VERSION_SCAN",
            "diagnostic_path_token": "diagnostic",
            "minimum_primary_pairs": 8,
            "minimum_primary_tasks": 4,
            "advantage_rule": (
                "TTFC_MAJORITY_AND_SPEEDUP_MAJORITY_AND_NO_HELDOUT_LOSS"
            ),
        },
        "inventory": inventory,
        "primary_metrics": metrics,
        "reports": rows,
        "verdict": verdict,
    }
    errors = validate_instance(
        result,
        read_object(root / "schemas" / "community_ab_meta_analysis.schema.json"),
    )
    if errors:
        raise ValueError("invalid A/B meta-analysis: " + "; ".join(errors))
    return result


def validate_ab_meta_analysis(
    analysis_path: Path, root: Path | None = None
) -> dict:
    root = root or repository_root()
    errors = validate_json_file(
        analysis_path, root / "schemas" / "community_ab_meta_analysis.schema.json"
    )
    if errors:
        raise ValueError("invalid A/B meta-analysis: " + "; ".join(errors))
    analysis = read_object(analysis_path)
    expected = build_ab_meta_analysis(Path(analysis["search_root"]), root)
    observed_stable = {
        key: value for key, value in analysis.items() if key != "generated_at"
    }
    expected_stable = {
        key: value for key, value in expected.items() if key != "generated_at"
    }
    if observed_stable != expected_stable:
        raise ValueError("A/B meta-analysis is stale or was edited")
    return {
        "status": "PASS",
        "verdict": analysis["verdict"],
        **analysis["inventory"],
    }


def sign_counts(values: list[float | None]) -> dict:
    observed = [float(value) for value in values if value is not None]
    return {
        "wins": sum(value > 0 for value in observed),
        "losses": sum(value < 0 for value in observed),
        "ties": sum(value == 0 for value in observed),
        "missing": len(values) - len(observed),
    }


def aggregate_prior_observations(observations: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in observations:
        grouped.setdefault((row["prior_kind"], row["prior_id"]), []).append(row)
    aggregates = []
    for (prior_kind, prior_id), rows in sorted(grouped.items()):
        ttfc = sign_counts(
            [row["deltas"]["time_to_first_correct_seconds_saved"] for row in rows]
        )
        speedup = sign_counts(
            [row["deltas"]["best_speedup_gain"] for row in rows]
        )
        heldout_losses = sum(
            row["deltas"]["heldout_pass_count_gain"] is not None
            and float(row["deltas"]["heldout_pass_count_gain"]) < 0
            for row in rows
        )
        if heldout_losses:
            adjustment = "REQUIRE_CONTEXT_GUARD"
        elif len(rows) >= 2 and ttfc["losses"] > ttfc["wins"] and (
            speedup["losses"] >= speedup["wins"]
        ):
            adjustment = "DOWNRANK"
        elif len(rows) >= 2 and ttfc["wins"] > ttfc["losses"] and (
            speedup["wins"] >= speedup["losses"]
        ):
            adjustment = "UPRANK"
        else:
            adjustment = "UNCHANGED"
        aggregates.append(
            {
                "prior_kind": prior_kind,
                "prior_id": prior_id,
                "observation_count": len(rows),
                "task_count": len({row["task_id"] for row in rows}),
                "ttfc": ttfc,
                "best_speedup": speedup,
                "heldout_loss_count": heldout_losses,
                "routing_adjustment": adjustment,
            }
        )
    return aggregates


def validate_prior_outcome_ledger_consistency(ledger: dict) -> None:
    expected_aggregates = aggregate_prior_observations(ledger["observations"])
    if ledger["aggregates"] != expected_aggregates:
        raise ValueError("prior outcome ledger aggregates do not match observations")
    unique_pairs = {
        (row["pair_identity"]["path"], row["pair_identity"]["sha256"])
        for row in ledger["observations"]
    }
    expected_inventory = {
        "primary_pair_count": len(unique_pairs),
        "prior_observation_count": len(ledger["observations"]),
        "event_prior_count": sum(
            row["prior_kind"] == "EVENT" for row in expected_aggregates
        ),
        "method_prior_count": sum(
            row["prior_kind"] == "METHOD" for row in expected_aggregates
        ),
        "guarded_prior_count": sum(
            row["routing_adjustment"] == "REQUIRE_CONTEXT_GUARD"
            for row in expected_aggregates
        ),
        "downranked_prior_count": sum(
            row["routing_adjustment"] == "DOWNRANK" for row in expected_aggregates
        ),
        "upranked_prior_count": sum(
            row["routing_adjustment"] == "UPRANK" for row in expected_aggregates
        ),
    }
    if ledger["inventory"] != expected_inventory:
        raise ValueError("prior outcome ledger inventory does not match observations")


def build_prior_outcome_ledger(
    meta_path: Path, root: Path | None = None
) -> dict:
    """Turn primary realized held-out outcomes into bounded routing feedback."""
    root = root or repository_root()
    meta_path = meta_path.resolve()
    validate_ab_meta_analysis(meta_path, root)
    meta = read_object(meta_path)
    search_root = Path(meta["search_root"])
    observations = []
    primary_pair_count = 0
    for row in meta["reports"]:
        if row["evidence_class"] != "PRIMARY_REALIZED":
            continue
        primary_pair_count += 1
        pair_path = (search_root / row["path"]).resolve()
        if sha256_file(pair_path) != row["sha256"]:
            raise ValueError(f"meta-analysis pair changed: {pair_path}")
        pair = read_object(pair_path)
        assessment_identity = pair["community_assessment"]
        assessment_path = Path(assessment_identity["path"])
        if not assessment_path.is_absolute():
            assessment_path = pair_path.parent / assessment_path
        assessment_path = assessment_path.resolve()
        if (
            not assessment_path.is_file()
            or sha256_file(assessment_path) != assessment_identity["sha256"]
        ):
            raise ValueError(f"community assessment changed: {assessment_path}")
        assessment = read_object(assessment_path)
        result_identity = assessment["result_identity"]
        result_path = Path(result_identity["path"])
        if not result_path.is_absolute():
            result_path = assessment_path.parent / result_path
        result_path = result_path.resolve()
        if (
            not result_path.is_file()
            or sha256_file(result_path) != result_identity["sha256"]
        ):
            raise ValueError(f"community result changed: {result_path}")
        result_errors = validate_json_file(
            result_path, root / "schemas" / "community_trial_result.schema.json"
        )
        if result_errors:
            raise ValueError(
                "invalid realized community result: " + "; ".join(result_errors)
            )
        result = read_object(result_path)
        realized_priors = []
        knowledge = result.get("knowledge_realization", {})
        if knowledge.get("disposition") == "REALIZED_IN_CANDIDATE":
            realized_priors.extend(
                (
                    "EVENT",
                    event_id,
                    sorted(knowledge.get("candidate_ids", [])),
                )
                for event_id in knowledge.get("selected_event_ids", [])
            )
        method = result.get("method_realization", {})
        if method.get("disposition") == "REALIZED_IN_CANDIDATE":
            realized_priors.append(
                (
                    "METHOD",
                    method["selected_method_id"],
                    sorted(method.get("candidate_ids", [])),
                )
            )
        if not realized_priors:
            raise ValueError(
                f"primary realized pair names no selected prior: {pair_path}"
            )
        deltas = {
            field: pair["deltas"].get(field)
            for field in (
                "time_to_first_correct_seconds_saved",
                "best_speedup_gain",
                "heldout_pass_count_gain",
            )
        }
        for prior_kind, prior_id, candidate_ids in realized_priors:
            observations.append(
                {
                    "pair_identity": absolute_identity(pair_path),
                    "suite_id": pair["suite_id"],
                    "task_id": pair["task_id"],
                    "repeat_index": pair["repeat_index"],
                    "prior_kind": prior_kind,
                    "prior_id": prior_id,
                    "candidate_ids": candidate_ids,
                    "deltas": deltas,
                }
            )
    observations.sort(
        key=lambda row: (
            row["prior_kind"],
            row["prior_id"],
            row["suite_id"],
            row["repeat_index"],
        )
    )
    aggregates = aggregate_prior_observations(observations)
    result = {
        "schema_version": PRIOR_OUTCOME_LEDGER_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "ROUTING_FEEDBACK_NOT_TARGET_PERFORMANCE_PROOF",
        "meta_analysis_identity": absolute_identity(meta_path),
        "policy": {
            "learn_from": "PRIMARY_REALIZED_ONLY",
            "heldout_loss_action": "REQUIRE_CONTEXT_GUARD",
            "minimum_directional_observations": 2,
        },
        "inventory": {
            "primary_pair_count": primary_pair_count,
            "prior_observation_count": len(observations),
            "event_prior_count": sum(row["prior_kind"] == "EVENT" for row in aggregates),
            "method_prior_count": sum(row["prior_kind"] == "METHOD" for row in aggregates),
            "guarded_prior_count": sum(
                row["routing_adjustment"] == "REQUIRE_CONTEXT_GUARD"
                for row in aggregates
            ),
            "downranked_prior_count": sum(
                row["routing_adjustment"] == "DOWNRANK" for row in aggregates
            ),
            "upranked_prior_count": sum(
                row["routing_adjustment"] == "UPRANK" for row in aggregates
            ),
        },
        "observations": observations,
        "aggregates": aggregates,
    }
    errors = validate_instance(
        result,
        read_object(root / "schemas" / "community_prior_outcome_ledger.schema.json"),
    )
    if errors:
        raise ValueError("invalid prior outcome ledger: " + "; ".join(errors))
    validate_prior_outcome_ledger_consistency(result)
    return result


def validate_prior_outcome_ledger(
    ledger_path: Path, root: Path | None = None
) -> dict:
    root = root or repository_root()
    errors = validate_json_file(
        ledger_path,
        root / "schemas" / "community_prior_outcome_ledger.schema.json",
    )
    if errors:
        raise ValueError("invalid prior outcome ledger: " + "; ".join(errors))
    ledger = read_object(ledger_path)
    validate_prior_outcome_ledger_consistency(ledger)
    meta_identity = ledger["meta_analysis_identity"]
    meta_path = Path(meta_identity["path"])
    if not meta_path.is_file() or sha256_file(meta_path) != meta_identity["sha256"]:
        raise ValueError("prior outcome ledger meta-analysis changed")
    expected = build_prior_outcome_ledger(meta_path, root)
    observed_stable = {
        key: value for key, value in ledger.items() if key != "generated_at"
    }
    expected_stable = {
        key: value for key, value in expected.items() if key != "generated_at"
    }
    if observed_stable != expected_stable:
        raise ValueError("prior outcome ledger is stale or was edited")
    return {"status": "PASS", **ledger["inventory"]}


def build_prior_routing_snapshot(
    ledger_path: Path, root: Path | None = None
) -> dict:
    """Produce a portable, pre-registrable routing surface without local paths."""
    root = root or repository_root()
    ledger_path = ledger_path.resolve()
    validate_prior_outcome_ledger(ledger_path, root)
    ledger = read_object(ledger_path)
    failed_tasks: dict[tuple[str, str], set[str]] = {}
    for row in ledger["observations"]:
        heldout_gain = row["deltas"]["heldout_pass_count_gain"]
        if heldout_gain is not None and float(heldout_gain) < 0:
            failed_tasks.setdefault(
                (row["prior_kind"], row["prior_id"]), set()
            ).add(row["task_id"])
    routes = [
        {
            "prior_kind": row["prior_kind"],
            "prior_id": row["prior_id"],
            "observation_count": row["observation_count"],
            "task_count": row["task_count"],
            "heldout_loss_count": row["heldout_loss_count"],
            "routing_adjustment": row["routing_adjustment"],
            "failed_task_ids": sorted(
                failed_tasks.get((row["prior_kind"], row["prior_id"]), set())
            ),
        }
        for row in ledger["aggregates"]
    ]
    result = {
        "schema_version": PRIOR_ROUTING_SNAPSHOT_SCHEMA,
        "generated_at": now(),
        "claim_boundary": (
            "PORTABLE_ROUTING_FEEDBACK_NOT_TARGET_PERFORMANCE_PROOF"
        ),
        "source_ledger": {
            "sha256": sha256_file(ledger_path),
            "generated_at": ledger["generated_at"],
        },
        "policy": ledger["policy"],
        "inventory": {
            "route_count": len(routes),
            "guarded_route_count": sum(
                row["routing_adjustment"] == "REQUIRE_CONTEXT_GUARD"
                for row in routes
            ),
            "downranked_route_count": sum(
                row["routing_adjustment"] == "DOWNRANK" for row in routes
            ),
            "upranked_route_count": sum(
                row["routing_adjustment"] == "UPRANK" for row in routes
            ),
        },
        "routes": routes,
    }
    errors = validate_instance(
        result,
        read_object(root / "schemas" / "community_prior_routing_snapshot.schema.json"),
    )
    if errors:
        raise ValueError("invalid prior routing snapshot: " + "; ".join(errors))
    return result


def validate_prior_routing_snapshot(
    snapshot_path: Path,
    ledger_path: Path,
    root: Path | None = None,
) -> dict:
    root = root or repository_root()
    errors = validate_json_file(
        snapshot_path,
        root / "schemas" / "community_prior_routing_snapshot.schema.json",
    )
    if errors:
        raise ValueError("invalid prior routing snapshot: " + "; ".join(errors))
    snapshot = read_object(snapshot_path)
    expected = build_prior_routing_snapshot(ledger_path, root)
    observed_stable = {
        key: value for key, value in snapshot.items() if key != "generated_at"
    }
    expected_stable = {
        key: value for key, value in expected.items() if key != "generated_at"
    }
    if observed_stable != expected_stable:
        raise ValueError("prior routing snapshot is stale or was edited")
    return {"status": "PASS", **snapshot["inventory"]}


PACKET_AUDIT_STOPWORDS = {
    "and", "are", "for", "from", "into", "only", "the", "this", "that",
    "then", "while", "with", "without", "existing", "already", "available",
}


def packet_audit_tokens(value: object) -> set[str]:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= 3 and token not in PACKET_AUDIT_STOPWORDS
    }


def audit_task_packets(
    suite_path: Path, output: Path, root: Path | None = None
) -> dict:
    """Detect task packets that reveal too much of their held-out oracle.

    This is a suite-authoring diagnostic, never an executor input: it reads the
    hidden oracle and therefore must remain outside every materialized trial.
    """
    root = root or repository_root()
    suite_path = suite_path.resolve()
    suite_errors = validate_json_file(
        suite_path, root / "schemas" / "community_temporal_suite.schema.json"
    )
    if suite_errors:
        raise ValueError("invalid temporal suite: " + "; ".join(suite_errors))
    suite = read_object(suite_path)
    rows = []
    for task in suite["tasks"]:
        packet_path = validate_identity(
            suite_path.parent, task["packet"], "task packet"
        )
        oracle_path = validate_identity(
            suite_path.parent, task["hidden_oracle"], "hidden oracle"
        )
        packet = read_object(packet_path)
        oracle = read_object(oracle_path)
        prospective_unknown = (
            oracle.get("prospective_seal", {}).get("solution_status")
            == "UNKNOWN_AT_SEAL"
        )
        mechanism = str(oracle.get("key_mechanism", ""))
        mechanism_tokens = set() if prospective_unknown else packet_audit_tokens(mechanism)
        packet_tokens = packet_audit_tokens(packet)
        recall = (
            len(mechanism_tokens & packet_tokens) / len(mechanism_tokens)
            if mechanism_tokens
            else 0.0
        )
        family_hits = []
        for family in ([] if prospective_unknown else oracle.get("solution_families", [])):
            family_tokens = packet_audit_tokens(str(family).replace("-", " "))
            # Family names are short and often contain domain nouns that a fair
            # task must mention (for example "top-p" or "metadata"). Require
            # the complete family phrase; the mechanism-recall score catches
            # broader paraphrases separately.
            if family_tokens and family_tokens <= packet_tokens:
                family_hits.append(str(family))
        if recall >= 0.60 or len(family_hits) >= 2:
            risk = "HIGH"
        elif recall >= 0.40 or family_hits:
            risk = "MEDIUM"
        else:
            risk = "LOW"
        reasons = []
        if recall >= 0.40:
            reasons.append(
                f"task packet contains {recall:.0%} of distinctive oracle mechanism tokens"
            )
        if family_hits:
            reasons.append("solution-family language appears in the task packet")
        if prospective_unknown:
            reasons.append(
                "prospective task had no winning mechanism available at seal time"
            )
        elif not reasons:
            reasons.append("no material lexical solution leakage detected")
        rows.append(
            {
                "task_id": task["task_id"],
                "risk": risk,
                "key_mechanism_token_recall": recall,
                "solution_family_hits": sorted(family_hits),
                "reasons": reasons,
            }
        )
    report = {
        "schema_version": TASK_PACKET_AUDIT_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "LEXICAL_SOLUTION_LEAKAGE_DIAGNOSTIC_ONLY",
        "suite_identity": identity_for(suite_path, suite_path.parent),
        "tasks": rows,
        "counts": {
            risk: sum(row["risk"] == risk for row in rows)
            for risk in ("LOW", "MEDIUM", "HIGH")
        },
    }
    errors = validate_instance(
        report,
        read_object(root / "schemas" / "community_task_packet_audit.schema.json"),
    )
    if errors:
        raise ValueError("invalid task-packet audit: " + "; ".join(errors))
    atomic_json(output.resolve(), report)
    return report


def summarize_schedule_run(
    schedule_path: Path, output: Path, root: Path | None = None
) -> dict:
    """Summarize compliant, invalid and unfinished trials without hiding failures."""
    root = root or repository_root()
    schedule_path = schedule_path.resolve()
    validate_schedule(schedule_path, root)
    schedule = read_object(schedule_path)
    rows = []
    for entry in schedule["entries"]:
        trial_dir = resolve_inside(schedule_path.parent, entry["trial_directory"])
        audit_path = trial_dir / "execution_audit.json"
        assessment_path = trial_dir / "assessment.json"
        status = "INCOMPLETE"
        violations = []
        audit_identity = None
        assessment_identity = None
        metrics = None
        completion_status = None
        material_improvement = None
        if audit_path.is_file():
            audit_errors = validate_json_file(
                audit_path,
                root / "schemas" / "community_trial_execution_audit.schema.json",
            )
            if audit_errors:
                status = "INVALID"
                violations = ["INVALID_EXECUTION_AUDIT"]
            else:
                audit = read_object(audit_path)
                audit_identity = identity_for(audit_path, schedule_path.parent)
                if audit["status"] != "PASS":
                    status = "INVALID"
                    violations = list(audit["violations"])
                elif assessment_path.is_file():
                    assessment_errors = validate_json_file(
                        assessment_path,
                        root / "schemas" / "community_trial_assessment.schema.json",
                    )
                    if assessment_errors:
                        status = "INVALID"
                        violations = ["INVALID_ASSESSMENT"]
                    else:
                        assessment = read_object(assessment_path)
                        result_path = trial_dir / "result.json"
                        result_errors = validate_json_file(
                            result_path,
                            root / "schemas" / "community_trial_result.schema.json",
                        )
                        if result_errors:
                            status = "INVALID"
                            violations = ["INVALID_RESULT"]
                            rows.append(
                                {
                                    "order_index": entry["order_index"],
                                    "task_id": entry["task_id"],
                                    "repeat_index": entry["repeat_index"],
                                    "arm": entry["arm"],
                                    "status": status,
                                    "completion_status": None,
                                    "material_improvement": None,
                                    "violations": violations,
                                    "audit_identity": audit_identity,
                                    "assessment_identity": None,
                                    "metrics": None,
                                }
                            )
                            continue
                        result = read_object(result_path)
                        status = "PASS"
                        assessment_identity = identity_for(
                            assessment_path, schedule_path.parent
                        )
                        metrics = assessment["metrics"]
                        completion_status = result["completion_status"]
                        material_improvement = (
                            metrics["time_to_first_improvement_seconds"] is not None
                        )
                else:
                    violations = ["ASSESSMENT_MISSING"]
        else:
            violations = ["EXECUTION_AUDIT_MISSING"]
        rows.append(
            {
                "order_index": entry["order_index"],
                "task_id": entry["task_id"],
                "repeat_index": entry["repeat_index"],
                "arm": entry["arm"],
                "status": status,
                "completion_status": completion_status,
                "material_improvement": material_improvement,
                "violations": violations,
                "audit_identity": audit_identity,
                "assessment_identity": assessment_identity,
                "metrics": metrics,
            }
        )
    pairs = []
    pair_keys = sorted({(row["task_id"], row["repeat_index"]) for row in rows})
    for task_id, repeat_index in pair_keys:
        members = [
            row
            for row in rows
            if row["task_id"] == task_id and row["repeat_index"] == repeat_index
        ]
        by_arm = {row["arm"]: row for row in members}
        pair_status = (
            "COMPARABLE"
            if set(by_arm) == set(ARMS)
            and all(by_arm[arm]["status"] == "PASS" for arm in ARMS)
            else "NOT_COMPARABLE"
        )
        pairs.append(
            {
                "task_id": task_id,
                "repeat_index": repeat_index,
                "status": pair_status,
                "arm_status": {
                    arm: by_arm.get(arm, {}).get("status", "INCOMPLETE")
                    for arm in ARMS
                },
            }
        )
    report = {
        "schema_version": SUITE_RUN_SUMMARY_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "PROTOCOL_COMPLIANCE_AND_OBSERVED_METRICS_ONLY",
        "schedule_identity": identity_for(schedule_path, schedule_path.parent),
        "trials": rows,
        "pairs": pairs,
        "counts": {
            arm: {
                status: sum(
                    row["arm"] == arm and row["status"] == status for row in rows
                )
                for status in ("PASS", "INVALID", "INCOMPLETE")
            }
            for arm in ARMS
        },
    }
    errors = validate_instance(
        report,
        read_object(root / "schemas" / "community_suite_run_summary.schema.json"),
    )
    if errors:
        raise ValueError("invalid suite run summary: " + "; ".join(errors))
    atomic_json(output.resolve(), report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    validate = subparsers.add_parser("validate-suite")
    validate.add_argument("--suite", type=Path, required=True)
    validate.add_argument("--corpus", type=Path, required=True)
    heldout = subparsers.add_parser("build-heldout-queue")
    heldout.add_argument("--receipt", type=Path, action="append", required=True)
    heldout.add_argument("--graph", type=Path, required=True)
    heldout.add_argument("--methods", type=Path)
    heldout.add_argument("--corpus", type=Path, required=True)
    heldout.add_argument("--cutoff-at", required=True)
    heldout.add_argument("--max-items", type=int, default=8)
    heldout.add_argument("--random-seed", type=int, required=True)
    heldout.add_argument("--output", type=Path, required=True)
    heldout_validate = subparsers.add_parser("validate-heldout-queue")
    heldout_validate.add_argument("--queue", type=Path, required=True)
    heldout_validate.add_argument("--corpus", type=Path, required=True)
    feasibility = subparsers.add_parser("build-feasibility-screen")
    feasibility.add_argument("--queue", type=Path, required=True)
    feasibility.add_argument("--policy", type=Path, required=True)
    feasibility.add_argument("--profile", type=Path, required=True)
    feasibility.add_argument("--corpus", type=Path, required=True)
    feasibility.add_argument("--output", type=Path, required=True)
    feasibility_validate = subparsers.add_parser("validate-feasibility-screen")
    feasibility_validate.add_argument("--screen", type=Path, required=True)
    feasibility_validate.add_argument("--corpus", type=Path, required=True)
    anchor = subparsers.add_parser("anchor-preregistration")
    anchor.add_argument("--preregistration", type=Path, required=True)
    anchor.add_argument("--git-commit", required=True)
    anchor.add_argument("--output", type=Path, required=True)
    anchor_validate = subparsers.add_parser("validate-preregistration-anchor")
    anchor_validate.add_argument("--anchor", type=Path, required=True)
    chain = subparsers.add_parser("audit-preselection-chain")
    chain.add_argument("--anchor", type=Path, required=True)
    chain.add_argument("--queue", type=Path, required=True)
    chain.add_argument("--screen", type=Path, required=True)
    chain.add_argument("--corpus", type=Path, required=True)
    chain.add_argument("--output", type=Path, required=True)
    chain_validate = subparsers.add_parser("validate-preselection-chain")
    chain_validate.add_argument("--audit", type=Path, required=True)
    chain_validate.add_argument("--corpus", type=Path, required=True)
    materialize = subparsers.add_parser("materialize-trial")
    materialize.add_argument("--suite", type=Path, required=True)
    materialize.add_argument("--corpus", type=Path, required=True)
    materialize.add_argument("--task", required=True)
    materialize.add_argument("--arm", choices=ARMS, required=True)
    materialize.add_argument("--repeat", type=int, default=1)
    materialize.add_argument("--output", type=Path, required=True)
    materialize_all = subparsers.add_parser("materialize-suite")
    materialize_all.add_argument("--suite", type=Path, required=True)
    materialize_all.add_argument("--corpus", type=Path, required=True)
    materialize_all.add_argument("--output", type=Path, required=True)
    validate_order = subparsers.add_parser("validate-schedule")
    validate_order.add_argument("--schedule", type=Path, required=True)
    prepare_source = subparsers.add_parser("prepare-source")
    prepare_source.add_argument("--trial", type=Path, required=True)
    prepare_source.add_argument("--repository", type=Path, required=True)
    validate_source = subparsers.add_parser("validate-source")
    validate_source.add_argument("--trial", type=Path, required=True)
    audit_execution = subparsers.add_parser("audit-execution")
    audit_execution.add_argument("--trial", type=Path, required=True)
    audit_execution.add_argument("--transcript", default="executor.jsonl")
    audit_execution.add_argument("--stderr", default="executor.stderr.log")
    audit_execution.add_argument(
        "--sandbox-mode",
        choices=("WORKSPACE_WRITE", "AUDITED_UNRESTRICTED"),
        default="AUDITED_UNRESTRICTED",
    )
    assess = subparsers.add_parser("assess-trial")
    assess.add_argument("--trial", type=Path, required=True)
    assess.add_argument("--require-execution-audit", action="store_true")
    compare = subparsers.add_parser("compare")
    compare.add_argument("--control", type=Path, required=True)
    compare.add_argument("--community", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    aggregate = subparsers.add_parser("aggregate-repeats")
    aggregate.add_argument("--pairs", type=Path, nargs="+", required=True)
    aggregate.add_argument("--output", type=Path, required=True)
    meta = subparsers.add_parser("meta-analyze")
    meta.add_argument("--search-root", type=Path, required=True)
    meta.add_argument("--output", type=Path, required=True)
    meta_validate = subparsers.add_parser("validate-meta-analysis")
    meta_validate.add_argument("--analysis", type=Path, required=True)
    ledger = subparsers.add_parser("build-prior-outcome-ledger")
    ledger.add_argument("--meta-analysis", type=Path, required=True)
    ledger.add_argument("--output", type=Path, required=True)
    ledger_validate = subparsers.add_parser("validate-prior-outcome-ledger")
    ledger_validate.add_argument("--ledger", type=Path, required=True)
    routing_snapshot = subparsers.add_parser("build-prior-routing-snapshot")
    routing_snapshot.add_argument("--ledger", type=Path, required=True)
    routing_snapshot.add_argument("--output", type=Path, required=True)
    routing_snapshot_validate = subparsers.add_parser(
        "validate-prior-routing-snapshot"
    )
    routing_snapshot_validate.add_argument("--snapshot", type=Path, required=True)
    routing_snapshot_validate.add_argument("--ledger", type=Path, required=True)
    task_packet_audit = subparsers.add_parser("audit-task-packets")
    task_packet_audit.add_argument("--suite", type=Path, required=True)
    task_packet_audit.add_argument("--output", type=Path, required=True)
    summarize_schedule = subparsers.add_parser("summarize-schedule")
    summarize_schedule.add_argument("--schedule", type=Path, required=True)
    summarize_schedule.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.operation == "validate-suite":
            result = validate_suite(args.suite, args.corpus)
        elif args.operation == "build-heldout-queue":
            result = build_heldout_queue(
                args.receipt,
                args.graph,
                args.methods,
                args.corpus,
                args.cutoff_at,
                args.max_items,
                args.random_seed,
            )
            atomic_json(args.output.resolve(), result)
            result = {**result["inventory"], "status": "PASS", "queue": str(args.output.resolve())}
        elif args.operation == "validate-heldout-queue":
            result = validate_heldout_queue(args.queue, args.corpus)
        elif args.operation == "build-feasibility-screen":
            result = build_feasibility_screen(
                args.queue, args.policy, args.profile, args.corpus
            )
            atomic_json(args.output.resolve(), result)
            result = {
                **result["inventory"],
                "registration": result["registration"],
                "status": "PASS",
                "screen": str(args.output.resolve()),
            }
        elif args.operation == "validate-feasibility-screen":
            result = validate_feasibility_screen(args.screen, args.corpus)
        elif args.operation == "anchor-preregistration":
            result = build_preselection_anchor(
                args.preregistration, args.git_commit
            )
            atomic_json(args.output.resolve(), result)
            result = {
                "status": "PASS",
                "commit": result["git_anchor"]["commit"],
                "committed_at": result["git_anchor"]["committed_at"],
                "cutoff_at": result["cutoff_at"],
                "anchor": str(args.output.resolve()),
            }
        elif args.operation == "validate-preregistration-anchor":
            result = validate_preselection_anchor(args.anchor)
        elif args.operation == "audit-preselection-chain":
            result = audit_preselection_chain(
                args.anchor, args.queue, args.screen, args.corpus
            )
            atomic_json(args.output.resolve(), result)
            result = {
                "status": "PASS",
                **result["observations"],
                "audit": str(args.output.resolve()),
            }
        elif args.operation == "validate-preselection-chain":
            result = validate_preselection_chain_audit(args.audit, args.corpus)
        elif args.operation == "materialize-trial":
            result = materialize_trial(
                args.suite,
                args.corpus,
                args.task,
                args.arm,
                args.repeat,
                args.output,
            )
        elif args.operation == "materialize-suite":
            result = materialize_suite(args.suite, args.corpus, args.output)
        elif args.operation == "validate-schedule":
            result = validate_schedule(args.schedule)
        elif args.operation == "prepare-source":
            result = prepare_trial_source(args.trial, args.repository)
        elif args.operation == "validate-source":
            result = validate_source_receipt(args.trial)
        elif args.operation == "audit-execution":
            result = audit_codex_execution(
                args.trial, args.transcript, args.stderr, args.sandbox_mode
            )
        elif args.operation == "assess-trial":
            result = assess_trial(
                args.trial,
                require_execution_audit=args.require_execution_audit,
            )
        elif args.operation == "aggregate-repeats":
            result = aggregate_pair_reports(args.pairs, args.output)
        elif args.operation == "meta-analyze":
            result = build_ab_meta_analysis(args.search_root)
            atomic_json(args.output.resolve(), result)
            result = {
                "status": "PASS",
                "verdict": result["verdict"],
                **result["inventory"],
                "analysis": str(args.output.resolve()),
            }
        elif args.operation == "validate-meta-analysis":
            result = validate_ab_meta_analysis(args.analysis)
        elif args.operation == "build-prior-outcome-ledger":
            result = build_prior_outcome_ledger(args.meta_analysis)
            atomic_json(args.output.resolve(), result)
            result = {
                "status": "PASS",
                **result["inventory"],
                "ledger": str(args.output.resolve()),
            }
        elif args.operation == "validate-prior-outcome-ledger":
            result = validate_prior_outcome_ledger(args.ledger)
        elif args.operation == "build-prior-routing-snapshot":
            result = build_prior_routing_snapshot(args.ledger)
            atomic_json(args.output.resolve(), result)
            result = {
                "status": "PASS",
                **result["inventory"],
                "snapshot": str(args.output.resolve()),
            }
        elif args.operation == "validate-prior-routing-snapshot":
            result = validate_prior_routing_snapshot(
                args.snapshot, args.ledger
            )
        elif args.operation == "audit-task-packets":
            result = audit_task_packets(args.suite, args.output)
        elif args.operation == "summarize-schedule":
            result = summarize_schedule_run(args.schedule, args.output)
        else:
            result = compare_trials(args.control, args.community, args.output)
    except Exception as error:
        print(f"ERROR: {error}", file=__import__("sys").stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
