#!/usr/bin/env python3
"""Single-process graph-batched screening measurement for C0/C1 at two shapes."""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timezone
from pathlib import Path

import torch

from experiment_common import (
    CANDIDATES,
    SCREENING_SEQUENCES,
    assert_idle,
    compare_boundaries,
    launch,
    plans_for_sequence,
    run_receipt,
    smi,
    snapshot_boundaries,
    target_device,
    verify_p0,
    verify_runtime_identity,
    write_json,
)

PAIRED_BLOCKS = 15
GRAPH_BATCH = 64


def elapsed_graph_us(graph: torch.cuda.CUDAGraph, stream: torch.cuda.Stream) -> float:
    start = torch.cuda.Event(enable_timing=True)
    stop = torch.cuda.Event(enable_timing=True)
    start.record(stream)
    for _ in range(GRAPH_BATCH):
        graph.replay()
    stop.record(stream)
    stop.synchronize()
    return float(start.elapsed_time(stop) * 1000.0 / GRAPH_BATCH)


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
            ("warmup", "warmup_receipt.json"),
        )
    }
    index, uuid = target_device(run)
    before = smi(index)
    assert_idle(before)
    if before["uuid"] != uuid:
        raise RuntimeError("GPU UUID changed")
    device = torch.device(f"cuda:{index}")
    shape_results = []

    for sequence in SCREENING_SEQUENCES:
        stream = torch.cuda.Stream(device=index)
        with torch.cuda.stream(stream):
            inputs, entries = plans_for_sequence(
                sequence, device, seed=2026082700 + sequence
            )
            direct_values = {}
            for candidate in CANDIDATES:
                entry = entries[candidate]
                launch(entry["plan"], inputs, entry["output"])
                direct_values[candidate] = snapshot_boundaries(
                    entry["plan"], entry["output"]
                )
            stream.synchronize()
            direct_preflight = compare_boundaries(
                direct_values["C0"], direct_values["C1"]
            )
            if direct_preflight["status"] != "PASS":
                raise RuntimeError(f"direct bitwise preflight failed at S={sequence}")
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

            orders = [["C0", "C1"]] * 8 + [["C1", "C0"]] * 7
            random.Random(20260827 + sequence).shuffle(orders)
            blocks = []
            for block_index, order in enumerate(orders):
                observed = {
                    candidate: elapsed_graph_us(graphs[candidate], stream)
                    for candidate in order
                }
                blocks.append(
                    {
                        "block": block_index,
                        "order": order,
                        "graph_batch": GRAPH_BATCH,
                        "c0_us": observed["C0"],
                        "c1_us": observed["C1"],
                        "delta_c1_minus_c0_us": observed["C1"] - observed["C0"],
                    }
                )
        shape_results.append(
            {
                "sequence": sequence,
                "direct_bitwise_preflight": direct_preflight,
                "paired_graph_blocks": blocks,
                "direct_latency_distribution": None,
            }
        )
    after = smi(index)
    if after["uuid"] != uuid:
        raise RuntimeError("GPU UUID changed during measurement")
    flat_deltas = [
        block["delta_c1_minus_c0_us"]
        for shape in shape_results
        for block in shape["paired_graph_blocks"]
    ]
    write_json(
        run / exp_rel / "raw/samples.json",
        {
            "schema_version": "qwen35-s3-tile-ab-raw-v1",
            "status": "PASS",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "runtime_identity": runtime,
            "p0": p0,
            "gates": gates,
            "environment_before": before,
            "environment_after": after,
            "timer": "CUDA events on one explicit stream",
            "measurement_semantics": "Only 15 paired graph blocks per shape; each latency is one event bracket divided by 64 graph replays.",
            "cupti": "NOT_COLLECTED_IN_SCREENING_DISTRIBUTION",
            "uncaptured_direct": "BITWISE_PREFLIGHT_ONLY_NO_LATENCY_SAMPLE",
            "samples": flat_deltas,
            "shapes": shape_results,
        },
    )


if __name__ == "__main__":
    main()
