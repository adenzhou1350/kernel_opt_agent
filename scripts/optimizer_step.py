#!/usr/bin/env python3
"""Select the next evidence-driven action for a run; optionally apply safe planning steps."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from evidence_utils import read_object, validate_hardware_evidence
from opportunity_map import validate_map as validate_opportunity_map


def action(kind: str, reason: str, commands: list[list[str]], blocking_inputs=None) -> dict:
    return {
        "schema_version": "optimizer-next-action-v1",
        "action": kind,
        "reason": reason,
        "commands": commands,
        "blocking_inputs": list(blocking_inputs or []),
    }


def discovery_action(run: Path, scripts: Path) -> dict | None:
    """Route fast candidate work before expensive evidence closure.

    Discovery results only decide which implementation deserves supervised
    qualification. They never bypass the existing acceptance gates.
    """
    path = run / "models" / "candidate_pool.json"
    if not path.is_file():
        return None
    pool = read_object(path)
    if pool.get("schema_version") != "candidate-pool-v1":
        return None
    if pool.get("status") == "PAUSED":
        return action(
            "DISCOVERY_BUDGET_REVIEW",
            "the discovery wall-clock budget expired; do not start more measurement until the portfolio and budget are reviewed",
            [],
            [{"required": "review candidate failures/survivors and explicitly resume, replace the plan, or stop"}],
        )
    if pool.get("status") != "ACTIVE":
        return None
    baseline = read_object(run / "models" / "baseline.json")
    if baseline.get("status") != "VALID" or baseline.get("correctness", {}).get("status") != "PASS":
        return action(
            "CAPTURE_DISCOVERY_BASELINE",
            "candidate discovery needs a correct production baseline, but full resource-model closure is not required yet",
            [],
            [{"required": "models/baseline.json status VALID with correctness PASS", "claim_scope": "DISCOVERY_ONLY"}],
        )
    opportunity_path = run / "models" / "opportunity_map.json"
    if not opportunity_path.is_file():
        return action(
            "BUILD_OPPORTUNITY_MAP",
            "the baseline is valid, but no quantified map connects model terms to globally material rewrites",
            [[sys.executable, str(scripts / "kernel_opt.py"), "opportunity", "init", "--run", str(run)]],
            [{"required": "derive conditional gain ceilings from the work ledger and schedule, then add 4-12 opportunities"}],
        )
    opportunities = read_object(opportunity_path)
    if opportunities.get("schema_version") != "opportunity-map-v1":
        return action("BLOCK_INVALID_OPPORTUNITY_MAP", "the opportunity map schema is missing or unsupported", [], [])
    if opportunities.get("status") == "PAUSED":
        return action("OPPORTUNITY_REVIEW", "the opportunity program is paused and cannot authorize more implementation or measurement", [], [])
    opportunity_rows = opportunities.get("opportunities", [])
    opportunity_policy = opportunities.get("policy", {})
    rewrite_families = {family for item in opportunity_rows for family in item.get("rewrite_families", [])}
    if (
        len(opportunity_rows) < int(opportunity_policy.get("min_opportunities", 1))
        or len(rewrite_families) < int(opportunity_policy.get("min_rewrite_families", 1))
    ):
        return action(
            "EXPAND_OPPORTUNITY_MAP",
            "enumerate several globally distinct rewrites before implementing or measuring a favorite local idea",
            [],
            [{
                "opportunity_count": len(opportunity_rows),
                "required_opportunities": int(opportunity_policy.get("min_opportunities", 1)),
                "rewrite_family_count": len(rewrite_families),
                "required_rewrite_families": int(opportunity_policy.get("min_rewrite_families", 1)),
                "required_action": "add quantified opportunity specs with kernel_opt.py opportunity add",
            }],
        )
    if opportunities.get("status") != "READY":
        return action(
            "RANK_OPPORTUNITIES",
            "rank expected global gain per implementation minute before spending hardware-measurement budget",
            [[sys.executable, str(scripts / "kernel_opt.py"), "opportunity", "rank", "--run", str(run)]],
        )
    try:
        validate_opportunity_map(opportunities, require_ready=True, run=run)
    except ValueError as error:
        return action(
            "BLOCK_INVALID_OPPORTUNITY_MAP",
            "a READY opportunity map failed recomputation; do not implement or measure from hand-edited priorities",
            [],
            [{"error": str(error)}],
        )
    candidates = pool.get("candidates", [])
    policy = pool.get("policy", {})
    families = {item.get("family") for item in candidates if item.get("family")}
    covered_opportunities = {item.get("opportunity_id") for item in candidates if item.get("opportunity_id")}
    minimum_opportunity_coverage = int(opportunity_policy.get("min_candidate_opportunities", 1))
    if (
        len(candidates) < int(policy.get("min_candidates", 1))
        or len(families) < int(policy.get("min_families", 1))
        or len(covered_opportunities) < minimum_opportunity_coverage
    ):
        target = next(
            (item for item in opportunity_rows if item.get("opportunity_id") not in covered_opportunities),
            opportunity_rows[0] if opportunity_rows else None,
        )
        return action(
            "EXPAND_DISCOVERY_PORTFOLIO",
            "implement high-ranked, materially different global opportunities before polishing one local idea",
            [],
            [{
                "candidate_count": len(candidates),
                "required_candidates": int(policy.get("min_candidates", 1)),
                "family_count": len(families),
                "required_families": int(policy.get("min_families", 1)),
                "opportunity_count": len(covered_opportunities),
                "required_opportunity_count": minimum_opportunity_coverage,
                "next_ranked_uncovered_opportunity": target,
                "required_action": "write run-local candidate source and register it with kernel_opt.py candidate add",
            }],
        )
    opportunity_ranks = {
        item.get("opportunity_id"): int(item.get("priority_rank", 10**9))
        for item in opportunity_rows
    }
    developing_rows = [item for item in candidates if item.get("status") in {"PROPOSED", "DEVELOPING"}]
    developing = min(
        developing_rows,
        key=lambda item: (
            opportunity_ranks.get(item.get("opportunity_id"), 10**9),
            0 if item.get("status") == "DEVELOPING" else 1,
            str(item.get("candidate_id", "")),
        ),
        default=None,
    )
    if developing:
        kind = "IMPLEMENT_DISCOVERY_CANDIDATE" if developing.get("status") == "PROPOSED" else "REPAIR_DISCOVERY_CANDIDATE"
        return action(
            kind,
            "compile/correctness failures are repairable discovery events and do not reject the performance hypothesis",
            [[
                sys.executable, str(scripts / "kernel_opt.py"), "candidate", "run",
                "--run", str(run), "--candidate-id", str(developing["candidate_id"]),
            ]],
            [{
                "candidate_id": developing["candidate_id"],
                "opportunity_id": developing.get("opportunity_id"),
                "family": developing.get("family"),
                "hypothesis": developing.get("hypothesis"),
                "latest_failure": developing.get("latest_failure"),
            }],
        )
    promoted = [item for item in candidates if item.get("status") == "PROMOTED_TO_QUALIFICATION"]
    if promoted:
        queue = read_object(run / "models" / "experiment_queue.json")
        linked_ids = {
            request.get("discovery_candidate_id")
            for request in queue.get("requests", [])
        }
        unlinked = next((item for item in promoted if item.get("candidate_id") not in linked_ids), None)
        if unlinked:
            return action(
                "BUILD_QUALIFICATION_CONTRACT",
                "a discovery survivor exists; bind it to the top-two supervised A/B flow instead of returning to open-ended microbenchmarking",
                [],
                [{"candidate_id": unlinked["candidate_id"], "promotion": unlinked.get("promotion")}],
            )
    survivors = [item for item in candidates if item.get("status") == "QUALIFICATION_READY"]
    if survivors and len(promoted) < int(policy.get("max_promotions", 2)):
        survivor = max(
            survivors,
            key=lambda item: float(item.get("screening", {}).get("improvement_percent", float("-inf"))),
        )
        return action(
            "PROMOTE_DISCOVERY_CANDIDATE",
            "promote the strongest remaining discovery survivor for sealed production-matched qualification",
            [[
                sys.executable, str(scripts / "kernel_opt.py"), "candidate", "promote",
                "--run", str(run), "--candidate-id", str(survivor["candidate_id"]),
            ]],
            [{"candidate_id": survivor["candidate_id"], "improvement_percent": survivor.get("screening", {}).get("improvement_percent")}],
        )
    if not any(item.get("status") in {"QUALIFICATION_READY", "PROMOTED_TO_QUALIFICATION"} for item in candidates):
        if len(candidates) < int(policy.get("max_candidates", len(candidates))):
            return action(
                "GENERATE_REPLACEMENT_CANDIDATES",
                "the current portfolio produced no survivor; create a new architecture family within the discovery budget",
                [],
                [{"screened_or_blocked": [item.get("candidate_id") for item in candidates]}],
            )
        return action(
            "DISCOVERY_PORTFOLIO_EXHAUSTED",
            "the maximum candidate portfolio produced no survivor; further measurement is blocked until the architecture plan changes",
            [],
            [{"candidates": [item.get("candidate_id") for item in candidates]}],
        )
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--apply-safe", action="store_true")
    args = parser.parse_args()
    run = args.run.resolve()
    scripts = Path(__file__).resolve().parent
    state = read_object(run / "run_state.json")
    hardware = read_object(run / "hardware.json")
    synthetic_legacy = state.get("schema_version") == "optimization-run-state-v2" and str(hardware.get("target", {}).get("vendor", "")).upper() == "TEST"
    if not synthetic_legacy and (
        state.get("schema_version") != "optimization-run-state-v4"
        or state.get("framework_contract_version") != "evidence-closed-v2"
    ):
        result = action(
            "BLOCK_INVALID_FRAMEWORK_CONTRACT",
            "missing or unknown evidence-closed contract cannot fall back to legacy validation",
            [],
            [{"required_schema": "optimization-run-state-v4", "required_contract": "evidence-closed-v2"}],
        )
        output = run / "traces/next_action.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    result = discovery_action(run, scripts) if not synthetic_legacy else None
    if result is not None:
        output = run / "traces/next_action.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if not synthetic_legacy:
        pool = read_object(run / "models" / "candidate_pool.json")
        working = [
            item for item in pool.get("candidates", [])
            if item.get("opportunity_id") and item.get("status") in {"QUALIFICATION_READY", "PROMOTED_TO_QUALIFICATION"}
        ]
        if not working:
            result = action(
                "BLOCK_MEASUREMENT_WITHOUT_WORKING_CANDIDATE",
                "hardware evidence and microbenchmarks are not the next action until opportunity-linked production code survives smoke screening",
                [],
                [{"required": "at least one opportunity-linked QUALIFICATION_READY or PROMOTED_TO_QUALIFICATION candidate"}],
            )
            output = run / "traces/next_action.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
    hardware_evidence_path = run / "hardware_evidence.json"
    hardware_path = run / "hardware.json"
    hardware_errors = validate_hardware_evidence(hardware_evidence_path, hardware_path) if hardware_evidence_path.exists() else ["manifest missing"]
    if hardware_errors:
        manifest = read_object(hardware_evidence_path) if hardware_evidence_path.exists() else {}
        result = action(
            "COLLECT_OFFICIAL_HARDWARE_EVIDENCE",
            "hardware facts and resource mappings are fail-closed until exact vendor-official documents are archived and validated",
            [[sys.executable, str(scripts / "validate_hardware_evidence.py"), str(hardware_evidence_path), "--hardware", str(hardware_path)]],
            [manifest.get("developer_input_request", {"message": "provide exact official document locations"})],
        )
    else:
        discovery_path = run / "models/resource_discovery.json"
        discovery = read_object(discovery_path) if discovery_path.exists() else {}
        if discovery.get("status") != "READY" or discovery.get("unresolved_mappings"):
            result = action(
                "DISCOVER_FINAL_BINARY_RESOURCES",
                "material resources must be generated from the launched binary and official hardware evidence, not a hand-written list",
                [[sys.executable, str(scripts / "archive_final_binary_sass.py"), "--binary", "<exact-launched-binary-inside-run>", "--output-sass", str(run / "static/final.sass"), "--output-receipt", str(run / "static/disassembly_receipt.json"), "--vendor", "<vendor>", "--device-name", "<exact-device-name>", "--compute-capability", "<compute-capability>"],
                 [sys.executable, str(scripts / "count_sass.py"), "--input", str(run / "static/final.sass"), "--binary", "<exact-launched-binary-inside-run>", "--disassembly-receipt", str(run / "static/disassembly_receipt.json"), "--output", str(run / "static/sass-summary.json")],
                 [sys.executable, str(scripts / "discover_resources.py"), "--sass-summary", str(run / "static/sass-summary.json"), "--hardware-evidence", str(hardware_evidence_path), "--output", str(discovery_path)]],
            )
        else:
            microbench = read_object(run / "models/microbenchmark_plan.json")
            queue = read_object(run / "models/experiment_queue.json")
            if microbench.get("levels", {}).get("P0", {}).get("status") != "PASS":
                result = action(
                    "CALIBRATE_MEASUREMENT_SYSTEM_P0",
                    "no performance experiment may run before timer, DCE, graph/direct, cache, clock and replication controls pass",
                    [],
                )
            else:
                requests = sorted(queue.get("requests", []), key=lambda item: item.get("priority", 10**9))
                proposed = next((item for item in requests if item.get("status") == "PROPOSED"), None)
                planned = next((item for item in requests if item.get("status") == "PLANNED"), None)
                awaiting_review = next((item for item in requests if item.get("status") == "AWAITING_SUPERVISOR_REVIEW"), None)
                replan = next((item for item in requests if item.get("status") == "HALT_AND_REPLAN"), None)
                running = next((item for item in requests if item.get("status") == "RUNNING"), None)
                dispatched = next((item for item in requests if item.get("status") == "DISPATCHED"), None)
                reconciliation = next((item for item in requests if item.get("status") == "RESOLVED" and item.get("result_binding", {}).get("model_reconciliation", {}).get("status") != "APPLIED"), None)
                if replan:
                    result = action(
                        "HALT_AND_REBUILD_CANDIDATE_FRONTIER",
                        "the causal hypothesis was rejected; the same experiment may not be retried until the global scheduler issues a new decision contract and the supervisor approves it",
                        [],
                        [{"request_id": replan["request_id"], "required": "new frontier identity, new decision id and updated candidate ordering"}],
                    )
                elif awaiting_review:
                    result = action(
                        "AWAIT_GLOBAL_SUPERVISOR_REVIEW",
                        "a technical failure never returns automatically to PLANNED; the supervisor must stop, authorize a budgeted same-question revision, or demand replanning",
                        [[sys.executable, str(scripts / "approve_experiment.py"), "--run", str(run), "--request-id", awaiting_review["request_id"], "--supervisor-id", "<registered-supervisor-id>", "--rationale", "<independent review>"]],
                    )
                elif reconciliation:
                    request_id = reconciliation["request_id"]
                    result = action(
                        "RECONCILE_RESULT_IN_GLOBAL_MODEL",
                        "validated measurements must update resource balance, schedule DAG, frontier and queue before another hypothesis is ranked",
                        [
                            [sys.executable, str(scripts / "apply_model_updates.py"), "--run", str(run), "--request-id", request_id, "--plan", f"<model-update-plan-for-{request_id}.json>"],
                            [sys.executable, str(scripts / "reconcile_experiment_result.py"), "--run", str(run), "--request-id", request_id, "--decision", "<ACCEPT|REJECT|INCONCLUSIVE>", "--explanation", "<boundary-aware explanation>", "--model-update-receipt", f"<semantic-model-update-receipt-for-{request_id}.json>"],
                        ],
                        [reconciliation["result_binding"]["model_reconciliation"]],
                    )
                elif proposed:
                    if not proposed.get("decision_contract") or not proposed.get("measurability_contract"):
                        result = action(
                            "BUILD_CANDIDATE_DECISION_CONTRACT",
                            "an unknown resource is not an experiment request; first rank 2-4 candidates and register the single uncertainty that can flip the top-two decision",
                            [],
                            [{"request_id": proposed["request_id"], "required": "decision-contract-v1 and measurability-contract-v1"}],
                        )
                        output = run / "traces/next_action.json"
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
                        print(json.dumps(result, indent=2, sort_keys=True))
                        return 0
                    commands = [[sys.executable, str(scripts / "rank_experiments.py"), "--run", str(run)], [sys.executable, str(scripts / "materialize_experiment.py"), "--run", str(run), "--request-id", proposed["request_id"]]]
                    if args.apply_safe:
                        for command in commands:
                            completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                            if completed.returncode:
                                raise RuntimeError(completed.stdout + completed.stderr)
                    result = action("MATERIALIZE_HIGHEST_VALUE_EXPERIMENT", "global model selected the highest-ranked unresolved causal question", commands)
                elif planned:
                    if not planned.get("supervisor_approval"):
                        result = action(
                            "REQUEST_GLOBAL_SUPERVISOR_APPROVAL",
                            "a sealed experiment remains non-runnable until an independent supervisor verifies candidate relevance, identifiability, precision, budget and role separation",
                            [[sys.executable, str(scripts / "approve_experiment.py"), "--run", str(run), "--request-id", planned["request_id"], "--supervisor-id", "<registered-supervisor-id>", "--rationale", "<independent review>"]],
                        )
                    else:
                        result = action(
                            "DISPATCH_SUPERVISOR_APPROVED_EXPERIMENT",
                            "the immutable candidate decision, measurement method, budget and experiment have an independent hash-bound approval",
                            [[sys.executable, str(scripts / "dispatch_experiment.py"), "--run", str(run), "--request-id", planned["request_id"]]],
                        )
                elif running:
                    result = action(
                        "VALIDATE_AND_BIND_RUNNING_EXPERIMENT",
                        "execution already completed; validate the immutable result or record a precise blocker, but never execute a RUNNING request again",
                        [
                            [sys.executable, str(scripts / "bind_experiment_result.py"), "--run", str(run), "--request-id", running["request_id"], "--result", f"<validated-result-for-{running['request_id']}.json>"],
                        ],
                        [{"alternative": "block_experiment.py", "requirement": "immutable external blocker evidence and any partial mechanism result"}],
                    )
                elif dispatched:
                    result = action(
                        "EXECUTE_AND_BIND_EXPERIMENT",
                        "execute only the materialized command contract, preserve immutable raw evidence, then bind the validated result",
                        [
                            [sys.executable, str(scripts / "execute_experiment.py"), "--run", str(run), "--request-id", dispatched["request_id"]],
                            [sys.executable, str(scripts / "bind_experiment_result.py"), "--run", str(run), "--request-id", dispatched["request_id"], "--result", f"<result-for-{dispatched['request_id']}.json>"],
                        ],
                    )
                else:
                    next_phase = state.get("allowed_next_phase")
                    result = action(
                        "CHECK_PHASE_GATE",
                        "no runnable unresolved request remains; validate the next phase instead of inventing another experiment",
                        [[sys.executable, str(scripts / "advance_run.py"), "--run", str(run), "--to", str(next_phase), "--check-only"]],
                    )
    output = run / "traces/next_action.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
