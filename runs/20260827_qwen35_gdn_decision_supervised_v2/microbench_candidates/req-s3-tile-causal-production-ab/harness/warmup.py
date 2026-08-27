#!/usr/bin/env python3
"""Lifecycle cache/graph warmup gate; deliberately emits no timing sample."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import torch

from experiment_common import (
    CANDIDATES,
    SCREENING_SEQUENCES,
    assert_idle,
    launch,
    plans_for_sequence,
    run_receipt,
    smi,
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
    exp_rel = "experiments/req-s3-tile-causal-production-ab"
    runtime = verify_runtime_identity(run)
    p0 = verify_p0(run)
    gates = {
        name: run_receipt(run, f"{exp_rel}/{path}")["identity"]
        for name, path in (
            ("build", "build/manifest.json"),
            ("static", "static/instruction_audit.json"),
            ("correctness", "correctness.json"),
        )
    }
    index, uuid = target_device(run)
    before = smi(index)
    assert_idle(before)
    if before["uuid"] != uuid:
        raise RuntimeError("GPU UUID changed")
    device = torch.device(f"cuda:{index}")
    warmed = []
    for sequence in SCREENING_SEQUENCES:
        stream = torch.cuda.Stream(device=index)
        with torch.cuda.stream(stream):
            inputs, entries = plans_for_sequence(
                sequence, device, seed=2026082700 + sequence
            )
            for iteration in range(40):
                candidate = CANDIDATES[iteration % 2]
                entry = entries[candidate]
                launch(entry["plan"], inputs, entry["output"])
            stream.synchronize()
            graphs = {}
            for candidate in CANDIDATES:
                graph = torch.cuda.CUDAGraph()
                entry = entries[candidate]
                with torch.cuda.graph(graph, stream=stream):
                    launch(entry["plan"], inputs, entry["output"])
                graphs[candidate] = graph
            for iteration in range(20):
                graphs[CANDIDATES[iteration % 2]].replay()
            stream.synchronize()
        warmed.append({"sequence": sequence, "direct_launches": 40, "graph_replays": 20})
    after = smi(index)
    if after["uuid"] != uuid:
        raise RuntimeError("GPU UUID changed during warmup")
    write_json(
        run / exp_rel / "warmup_receipt.json",
        {
            "schema_version": "qwen35-s3-tile-ab-warmup-v1",
            "status": "PASS",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "runtime_identity": runtime,
            "p0": p0,
            "gates": gates,
            "environment_before": before,
            "environment_after": after,
            "warmed": warmed,
            "timing_samples_emitted": 0,
            "note": "This lifecycle process exits; measure performs its own in-process warmup.",
        },
    )


if __name__ == "__main__":
    main()
