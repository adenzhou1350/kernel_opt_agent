#!/usr/bin/env python3
"""Create the sole VALID outcome: PASS-only static admission."""

from __future__ import annotations

import argparse
from pathlib import Path

from common import REQUEST_ID, candidate_dir, dump, experiment_dir, identity, load


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    experiment = experiment_dir(run)
    experiment_path = experiment / "experiment.json"
    raw_path = experiment / "raw/samples.json"
    correctness_path = experiment / "correctness/correctness.json"
    audit_path = experiment / "static/instruction_audit.json"
    manifest_path = experiment / "build/manifest.json"
    raw = load(raw_path)
    correctness = load(correctness_path)
    audit = load(audit_path)
    manifest = load(manifest_path)
    expected_value = float(manifest["binary_pass"])
    if raw.get("samples") != [expected_value, expected_value]:
        raise RuntimeError("short/long deterministic observations disagree with build outcome")
    if correctness.get("status") != "PASS" or audit.get("audit_status") != "PASS":
        raise RuntimeError("static evidence chain is not valid")
    outcome = manifest["predicate_outcome"]
    if outcome != "PASS" or manifest.get("binary_pass") != 1:
        raise RuntimeError("PASS-only admission cannot consume a non-PASS outcome")
    disposition = "LAYOUT_VIEW_FEASIBLE_PENDING_IMPLEMENTATION"
    allowed = ["N2 static logical same-backing/type admission"]
    first_binary_name = sorted(audit["binary_identities"])[0]
    first_sass_name = sorted(audit["sass_identities"])[0]
    p0 = run / "experiments/p0-reused/p0_receipt.json"
    result = {
        "schema_version": "benchmark-result-v2", "request_id": REQUEST_ID,
        "experiment_identity": identity(experiment_path),
        "hardware_identity": identity(run / "hardware.json"),
        "workload_identity": identity(run / "workload.json"),
        "benchmark": "exact same-backing accumulator-view static admissibility",
        "question": "Do exact short and long production O1 fragments admit four N16 scoreV C/D views?",
        "environment": {"target_arch": "sm_120a", "cuda_kernel_launches": 0, "gpu_performance_samples": 0},
        "source_identity": identity(candidate_dir(run) / "layout_proof.py"),
        "measurement": {
            "metric": "n2_layout_view_feasible",
            "semantics": "short and long each contribute one deterministic compiler/type observation; no timing interpretation",
            "unit": "binary_pass", "timer": "none_compiler_typecheck",
        },
        "raw_samples": raw["samples"], "raw_samples_identity": identity(raw_path),
        "summary": {
            "static_admissibility": outcome, "n2_disposition": disposition,
            "predicate_id": None,
            "survivor_set_update_authorized": True,
            "latency_model_update_authorized": False, "performance_top_two_update_authorized": False,
            "cuda_kernel_launches": 0, "gpu_performance_samples": 0,
        },
        "correctness": {"status": "PASS", "checks": correctness["checks"], "evidence_identity": identity(correctness_path)},
        "static_evidence": {
            "binary_identity": audit["binary_identities"][first_binary_name],
            "sass_identity": audit["sass_identities"][first_sass_name],
            "static_audit_identity": identity(audit_path),
            "resource_usage": {
                "claim": "proof/control codegen only, not production resource usage",
                "explicit_transport_allocations_in_static_view_expression": 0,
                "production_transport_claim": "DEFERRED_IMPLEMENTATION_GATE",
                "cuda_kernel_launches": 0,
            },
        },
        "runtime_evidence": {"compiled_callable_invocations": 0, "cuda_kernel_launches": 0, "cuda_events": 0},
        "measurement_system": {"p0_receipt": identity(p0)},
        "validity": {
            "status": "VALID",
            "dce_guard": "typed four-view scoreV C/D compile plus typed sink; proof callable not invoked; no production-SASS claim",
            "known_pollution": [], "claims_allowed": allowed,
            "claims_forbidden": [
                "candidate rejection", "GPU latency", "speedup", "numerical correctness", "K-loop accumulation order",
                "physical register continuity", "production SASS/resources", "performance Top2", "production acceptance",
            ],
        },
    }
    dump(experiment / "result.json", result)
    print(f"PASS: static result valid; n2_disposition={disposition}; no performance claim")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
