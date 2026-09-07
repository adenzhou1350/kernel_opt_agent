#!/usr/bin/env python3
"""Exercise transfer-aware method matching and stale-receipt routing."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from method_library import build_snapshot, load_card_revisions
from optimizer_step import discovery_action


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cli(command: str, *args: str, expected: int = 0) -> dict:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/kernel_opt.py"), command, *args],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert completed.returncode == expected, (completed.stdout, completed.stderr)
    return json.loads(completed.stdout) if completed.stdout.strip() else {}


def opportunity(identifier: str, families: list[str], evidence_sha256: str) -> dict:
    evidence = [{"path": "models/baseline.json", "sha256": evidence_sha256, "claim": "current objective contribution"}]
    return {
        "opportunity_id": identifier,
        "name": identifier,
        "model_scope": "CURRENT_SCHEDULE",
        "source_model_term": identifier,
        "affected_stages": [identifier],
        "current_contribution_us": 10.0,
        "optimistic_gain_ceiling_us": 5.0,
        "likely_gain_interval_us": {"lower": 1.0, "upper": 3.0},
        "confidence": "MEDIUM",
        "rewrite_families": families,
        "implementation_budget_minutes": 10.0,
        "hypothesis": "remove globally visible work with a different architecture",
        "derivation": "baseline contribution multiplied by a bounded removable fraction",
        "evidence": evidence,
        "production_impact_gate": {
            "measurement_scope": "FROZEN_WORKLOAD_DECOMPOSITION",
            "baseline_end_to_end_us": 20.0,
            "target_component_us": 10.0,
            "candidate_component_speedup_ceiling": 2.0,
            "derived_amdahl_speedup_ceiling": 4.0 / 3.0,
            "material_speedup_floor": 1.01,
            "decision": "CLEARS_MATERIALITY_FLOOR",
            "derivation": "The frozen decomposition assigns half of end-to-end time to this component.",
            "evidence": evidence,
        },
    }


def main() -> None:
    validated = cli("method", "validate")
    assert validated["status"] == "PASS" and validated["card_count"] >= 10, validated
    assert validated["revision_count"] == validated["card_count"] + 1, validated
    revisions = [
        card
        for _, card in load_card_revisions(ROOT)
        if card["method_id"] == "community-incremental-prefix-state-machine"
    ]
    assert [card.get("revision", 1) for card in revisions] == [1, 2]
    cutoff_snapshot = build_snapshot("2026-08-31T23:59:59Z", ROOT)
    assert "cuda-hierarchical-scan-decomposition" in cutoff_snapshot["included_method_ids"]
    assert "triton-dynamic-extent-specialization-control" not in cutoff_snapshot[
        "included_method_ids"
    ]
    assert cutoff_snapshot["excluded_method_ids"] == []
    assert cutoff_snapshot["excluded_method_count"] >= 1
    assert cutoff_snapshot["withheld_revision_count"] >= 1
    assert "triton-dynamic-extent-specialization-control" not in json.dumps(
        cutoff_snapshot
    )
    assert "community-incremental-prefix-state-machine.v2.json" not in json.dumps(
        cutoff_snapshot
    )
    assert all(
        card["source"]["available_at"] <= "2026-08-31T23:59:59Z"
        for card in cutoff_snapshot["cards"]
    )
    current_snapshot = build_snapshot("2026-09-06T08:40:00Z", ROOT)
    primitive_ids = {
        card["method_id"]
        for card in current_snapshot["cards"]
        if card.get("community_provenance") is not None
    }
    legacy_primitive_ids = {
        "community-architecture-conditioned-fusion",
        "community-cross-layer-state-contract",
        "community-fast-path-reachability",
        "community-finite-range-before-reassociation",
        "community-host-loop-to-segmented-array",
        "community-validation-hoist-with-coherence",
    }
    assert primitive_ids == legacy_primitive_ids | {
        "community-incremental-prefix-state-machine",
        "distribution-equivalent-device-reformulation",
    }
    assert "community-incremental-prefix-state-machine" in cutoff_snapshot[
        "included_method_ids"
    ]
    historical_incremental = next(
        card
        for card in cutoff_snapshot["cards"]
        if card["method_id"] == "community-incremental-prefix-state-machine"
    )
    assert historical_incremental.get("revision", 1) == 1
    assert not legacy_primitive_ids.intersection(
        cutoff_snapshot["included_method_ids"]
    )
    assert all(
        card["community_provenance"]["entity_boundary"]
        == "DO_NOT_TREAT_AS_TARGET_PERFORMANCE_EVIDENCE"
        for card in current_snapshot["cards"]
        if card["method_id"] in primitive_ids
    )
    learned_snapshot = build_snapshot("2026-09-06T09:40:00Z", ROOT)
    assert "distribution-equivalent-device-reformulation" in {
        card["method_id"] for card in learned_snapshot["cards"]
    }
    learned = next(
        card
        for card in learned_snapshot["cards"]
        if card["method_id"] == "community-segmented-transfer-granularity"
    )
    assert learned["community_provenance"]["experiment_refs"][0][
        "claim_boundary"
    ] == "SEALED_SINGLE_TASK_EXPERIMENT"
    revised_snapshot = build_snapshot("2026-09-06T12:00:00Z", ROOT)
    revised_incremental = next(
        card
        for card in revised_snapshot["cards"]
        if card["method_id"] == "community-incremental-prefix-state-machine"
    )
    assert revised_incremental["revision"] == 2
    assert revised_incremental["community_provenance"]["source_event_ids"] == [
        "vllm.pr-40298.incremental-streaming-state-machine",
        "vllm.pr-55565.incremental-deepseek-delimiter-state",
    ]

    with tempfile.TemporaryDirectory() as chain_temporary:
        chain_root = Path(chain_temporary)
        (chain_root / "schemas").mkdir()
        (chain_root / "knowledge" / "primitives").mkdir(parents=True)
        (chain_root / "knowledge" / "method_revisions").mkdir(parents=True)
        shutil.copyfile(
            ROOT / "schemas" / "optimization_method.schema.json",
            chain_root / "schemas" / "optimization_method.schema.json",
        )
        shutil.copyfile(
            ROOT / "knowledge" / "primitives" / "incremental-prefix-state-machine.json",
            chain_root
            / "knowledge"
            / "primitives"
            / "incremental-prefix-state-machine.json",
        )
        revision_path = (
            chain_root
            / "knowledge"
            / "method_revisions"
            / "community-incremental-prefix-state-machine.v2.json"
        )
        tampered_revision = json.loads(
            (
                ROOT
                / "knowledge"
                / "method_revisions"
                / "community-incremental-prefix-state-machine.v2.json"
            ).read_text(encoding="utf-8")
        )
        tampered_revision["supersedes"]["sha256"] = "0" * 64
        write(revision_path, tampered_revision)
        try:
            load_card_revisions(chain_root)
        except ValueError as error:
            assert "predecessor hash mismatch" in str(error)
        else:
            raise AssertionError("tampered method predecessor was accepted")

    with tempfile.TemporaryDirectory() as temporary:
        run = Path(temporary) / "run"
        (run / "models").mkdir(parents=True)
        for name in ("operator.json", "workload.json", "hardware.json"):
            shutil.copyfile(ROOT / "tests" / "fixtures" / name, run / name)
        hardware = json.loads((run / "hardware.json").read_text(encoding="utf-8"))
        hardware["target"] = {"vendor": "NVIDIA", "device_name": "NVIDIA GeForce RTX 4060 Laptop GPU", "device_index": 0}
        write(run / "hardware.json", hardware)
        write(run / "models" / "baseline.json", {"status": "VALID", "correctness": {"status": "PASS"}})
        evidence_sha256 = hashlib.sha256((run / "models" / "baseline.json").read_bytes()).hexdigest()
        cli("candidate", "init", "--run", str(run), "--min-candidates", "2", "--max-candidates", "4", "--min-families", "2")
        cli("opportunity", "init", "--run", str(run), "--min-opportunities", "2", "--max-opportunities", "4", "--min-rewrite-families", "2", "--min-candidate-opportunities", "2")
        for spec in (
            opportunity("attention-overlap", ["async-pipeline"], evidence_sha256),
            opportunity("remove-intermediate", ["cross-stage-fusion"], evidence_sha256),
            opportunity(
                "awq-fp16-dequantization-hoist-overflow",
                ["loop-invariant-hoisting", "numerical-range-proof"],
                evidence_sha256,
            ),
            opportunity(
                "mtp-numerical-boundary",
                ["numerical-invariance", "decision-boundary-recompute"],
                evidence_sha256,
            ),
        ):
            path = run / "models" / f"{spec['opportunity_id']}.json"
            write(path, spec)
            cli("opportunity", "add", "--run", str(run), "--spec", str(path))
        cli("opportunity", "rank", "--run", str(run))

        retrieve = discovery_action(run, ROOT / "scripts")
        assert retrieve and retrieve["action"] == "RETRIEVE_OPTIMIZATION_METHODS", retrieve
        receipt = cli("method", "recommend", "--run", str(run))
        by_opportunity = {row["opportunity_id"]: row["matches"] for row in receipt["recommendations"]}
        attention = {row["method_id"]: row for row in by_opportunity["attention-overlap"]}
        assert attention["flashattention3-async-pipeline"]["transfer_status"] == "BLOCKED_UNVERIFIED_CAPABILITY", attention
        fusion = {row["method_id"]: row for row in by_opportunity["remove-intermediate"]}
        assert fusion["korch-fission-orchestration"]["transfer_status"] == "DIRECT", fusion
        guards = {row["method_id"]: row for row in receipt["evaluation_guards"]}
        assert guards["community-finite-range-before-reassociation"][
            "claim_boundary"
        ] == "DISCOVERY_PRIOR_ONLY"
        assert "community-fast-path-reachability" not in guards
        numerical = {
            row["method_id"]: row
            for row in by_opportunity["mtp-numerical-boundary"]
        }
        selective = numerical[
            "community-selective-precision-boundary-recompute"
        ]
        assert selective["transfer_status"] == "DIRECT", selective
        assert selective["candidate_archetypes"][0]["family"] == (
            "decision-boundary-recompute"
        )
        assert selective["claim_boundary"] == "DISCOVERY_PRIOR_ONLY"

        expand = discovery_action(run, ROOT / "scripts")
        assert expand and expand["action"] == "EXPAND_DISCOVERY_PORTFOLIO", expand
        assert expand["blocking_inputs"][0]["transfer_aware_method_matches"], expand

        receipt_path = run / "models" / "method_matches.json"
        edited = json.loads(receipt_path.read_text(encoding="utf-8"))
        edited["recommendations"][0]["matches"][0]["score"] += 1000
        write(receipt_path, edited)
        tampered = discovery_action(run, ROOT / "scripts")
        assert tampered and tampered["action"] == "RETRIEVE_OPTIMIZATION_METHODS", tampered
        assert "edited" in tampered["blocking_inputs"][0]["stale_or_missing_receipt"], tampered
        cli("method", "recommend", "--run", str(run))

        operator = json.loads((run / "operator.json").read_text(encoding="utf-8"))
        operator["name"] = "changed-after-match"
        write(run / "operator.json", operator)
        stale = discovery_action(run, ROOT / "scripts")
        assert stale and stale["action"] == "RETRIEVE_OPTIMIZATION_METHODS", stale
        assert "stale" in stale["blocking_inputs"][0]["stale_or_missing_receipt"], stale

    print("method library test: PASS")


if __name__ == "__main__":
    main()
