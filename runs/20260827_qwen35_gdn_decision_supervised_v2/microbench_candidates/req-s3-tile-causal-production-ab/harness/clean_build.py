#!/usr/bin/env python3
"""Compile C0/C1 for both screening paths and archive exact PTX/cubins."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import torch

from experiment_common import (
    CANDIDATES,
    SCREENING_SEQUENCES,
    dump_compiled,
    identity,
    plans_for_sequence,
    target_device,
    verify_p0,
    verify_runtime_identity,
    write_json,
)


@torch.inference_mode()
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    experiment = run / "experiments/req-s3-tile-causal-production-ab"
    build_dir = experiment / "build"
    build_dir.mkdir(parents=True, exist_ok=True)

    runtime = verify_runtime_identity(run)
    p0 = verify_p0(run)
    device_index, uuid = target_device(run)
    device = torch.device(f"cuda:{device_index}")
    configurations = []
    for sequence in SCREENING_SEQUENCES:
        inputs, entries = plans_for_sequence(
            sequence, device, seed=20260827 + sequence
        )
        for candidate_id in CANDIDATES:
            plan = entries[candidate_id]["plan"]
            dumped = dump_compiled(
                plan.compiled,
                f"{candidate_id.lower()}_s{sequence}",
                build_dir / f"{candidate_id.lower()}_s{sequence}",
            )
            configurations.append(
                {
                    "candidate_id": candidate_id,
                    "sequence": sequence,
                    "abi_tag": plan.stage_abi_tag,
                    "binary": dumped,
                }
            )
        c0 = configurations[-2]["binary"]["cubin"]["sha256"]
        c1 = configurations[-1]["binary"]["cubin"]["sha256"]
        if c0 == c1:
            raise RuntimeError(f"S={sequence}: C0/C1 cubins are identical")
        del entries, inputs
        torch.cuda.empty_cache()

    manifest = {
        "schema_version": "qwen35-s3-tile-ab-build-v1",
        "status": "PASS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target": {"device_index": device_index, "uuid": uuid},
        "runtime_identity": runtime,
        "p0": p0,
        "configurations": configurations,
        "source_identities": [
            identity(path)
            for path in sorted(
                (run / "microbench_candidates/req-s3-tile-causal-production-ab").rglob("*")
            )
            if path.is_file() and path.suffix in {".py", ".md"}
        ],
    }
    write_json(build_dir / "manifest.json", manifest)


if __name__ == "__main__":
    main()
