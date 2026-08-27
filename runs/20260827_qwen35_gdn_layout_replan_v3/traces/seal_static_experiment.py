#!/usr/bin/env python3
"""Seal the run-local static layout proof as a six-phase argv contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


REQUEST = "req-n2-static-layout-admissibility"
PYTHON = "/workspace/dance/qwen35/.venv-cu13/bin/python"
PHASES = ("clean_build", "static_audit", "correctness", "warmup", "measure", "analyze")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    experiment_path = run / "experiments" / REQUEST / "experiment.json"
    source = run / "microbench_candidates" / REQUEST
    experiment = json.loads(experiment_path.read_text())
    if experiment.get("status") != "PLANNED":
        raise ValueError("seal requires the freshly materialized PLANNED template")
    source_files = sorted(path for path in source.glob("*.py") if path.is_file())
    expected = {"layout_proof.py", "common.py", *{f"{phase}.py" for phase in PHASES}}
    observed = {path.name for path in source_files}
    if observed != expected:
        raise ValueError(f"source package mismatch: expected={sorted(expected)}, observed={sorted(observed)}")

    experiment.update({
        "status": "MATERIALIZED",
        "level": "P1",
        "source": {
            "mode": "CREATE_RUN_LOCAL",
            "package_id": None,
            "candidate_path": str(source),
            "identities": [identity(path) for path in source_files],
        },
        "commands": {
            phase: [[PYTHON, str(source / f"{phase}.py"), "--run", str(run)]]
            for phase in PHASES
        },
        "parameter_matrix": [
            {"candidate_id": "N2", "production_path": "short", "layout": "D128_N64_to_N16", "gpu_launches": 0},
            {"candidate_id": "N2", "production_path": "long", "layout": "D128_N64_to_N16", "gpu_launches": 0},
        ],
        "controls": [
            "Positive control: all four same-iterator N16 views equal the exact eight-warp scoreV prototype.",
            "Negative control: the old single-warp append layout remains unequal and would fail admission.",
            "Zero-copy control: output.iterator is reused; any copy, shared/global handoff or barrier rejects N2.",
            "Live evidence control: PTX, cubin, SASS, compiler logs and source hashes are archived even though the compiled callable is never invoked.",
            "Numerical candidate correctness and GPU latency remain outside this static contract.",
        ],
        "execution_budget": {
            "samples_per_configuration": 1,
            "process_launches": 6,
            "max_wall_clock_minutes": 15,
        },
        "expected_sass": [
            "Proof cubin/SASS identity exists only to bind compiler lowering; no production instruction-count or latency claim is allowed."
        ],
        "model_update_contract": {
            "model_field": "N2 static admissibility before candidate performance ranking",
            "decision_changed": "Admit or reject N2; retain N0 and N1 regardless.",
            "summary_fields": ["static_admissibility", "n2_disposition", "cuda_kernel_launches", "gpu_performance_samples"],
        },
        "artifacts": {
            "raw_samples": f"experiments/{REQUEST}/raw/samples.json",
            "result": f"experiments/{REQUEST}/result.json",
            "static_audit": f"experiments/{REQUEST}/static/instruction_audit.json",
            "reproduction_log": f"experiments/{REQUEST}/reproduction.json",
        },
        "evidence": [
            *experiment.get("evidence", []),
            identity(run / "models/decision_contract.json"),
            identity(run / "models/measurability_contract.json"),
            identity(run / "traces/layout_replan_planning.json"),
        ],
        "sealed_at": datetime.now(timezone.utc).isoformat(),
    })
    dump(experiment_path, experiment)
    receipt = {
        "schema_version": "static-layout-experiment-seal-v1",
        "status": "PASS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "request_id": REQUEST,
        "experiment_identity": identity(experiment_path),
        "source_identities": experiment["source"]["identities"],
        "process_launches": 6,
        "cuda_kernel_launches_authorized": 0,
        "gpu_performance_samples_authorized": 0,
    }
    dump(run / "traces/static_layout_experiment_seal.json", receipt)
    print(json.dumps({"status": "PASS", "experiment": identity(experiment_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
