#!/usr/bin/env python3
"""Bitwise direct-repeat and graph/direct admission at S404 and S768."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import torch

from experiment_common import (
    CANDIDATES,
    SCREENING_SEQUENCES,
    compare_boundaries,
    launch,
    plans_for_sequence,
    run_receipt,
    snapshot_boundaries,
    target_device,
    verify_p0,
    verify_runtime_identity,
    write_json,
)


def capture(plan, inputs, output, stream: torch.cuda.Stream) -> torch.cuda.CUDAGraph:
    graph = torch.cuda.CUDAGraph()
    with torch.cuda.graph(graph, stream=stream):
        launch(plan, inputs, output)
    return graph


@torch.inference_mode()
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    exp_rel = "experiments/req-s3-tile-causal-production-ab"
    runtime = verify_runtime_identity(run)
    p0 = verify_p0(run)
    build = run_receipt(run, f"{exp_rel}/build/manifest.json")
    static = run_receipt(run, f"{exp_rel}/static/instruction_audit.json")
    index, uuid = target_device(run)
    device = torch.device(f"cuda:{index}")
    cases = []

    for sequence in SCREENING_SEQUENCES:
        for domain, extreme in (("random", False), ("extreme_finite", True)):
            stream = torch.cuda.Stream(device=index)
            with torch.cuda.stream(stream):
                inputs, entries = plans_for_sequence(
                    sequence,
                    device,
                    seed=2026082700 + sequence + (10000 if extreme else 0),
                    extreme=extreme,
                )
                direct = {}
                repeats = {}
                for candidate in CANDIDATES:
                    entry = entries[candidate]
                    launch(entry["plan"], inputs, entry["output"])
                    direct[candidate] = snapshot_boundaries(
                        entry["plan"], entry["output"]
                    )
                    launch(entry["plan"], inputs, entry["output"])
                    repeats[candidate] = snapshot_boundaries(
                        entry["plan"], entry["output"]
                    )
                stream.synchronize()

                repeat_checks = {
                    candidate: compare_boundaries(direct[candidate], repeats[candidate])
                    for candidate in CANDIDATES
                }
                candidate_check = compare_boundaries(direct["C0"], direct["C1"])
                graphs = {
                    candidate: capture(
                        entries[candidate]["plan"],
                        inputs,
                        entries[candidate]["output"],
                        stream,
                    )
                    for candidate in CANDIDATES
                }
                graph_values = {}
                for candidate in CANDIDATES:
                    graphs[candidate].replay()
                    graph_values[candidate] = snapshot_boundaries(
                        entries[candidate]["plan"], entries[candidate]["output"]
                    )
                stream.synchronize()
                graph_direct = {
                    candidate: compare_boundaries(
                        direct[candidate], graph_values[candidate]
                    )
                    for candidate in CANDIDATES
                }
                graph_candidate = compare_boundaries(
                    graph_values["C0"], graph_values["C1"]
                )

            passed = (
                candidate_check["status"] == "PASS"
                and graph_candidate["status"] == "PASS"
                and all(v["status"] == "PASS" for v in repeat_checks.values())
                and all(v["status"] == "PASS" for v in graph_direct.values())
            )
            cases.append(
                {
                    "sequence": sequence,
                    "domain": domain,
                    "status": "PASS" if passed else "FAIL",
                    "c0_vs_c1_direct": candidate_check,
                    "direct_repeat": repeat_checks,
                    "graph_vs_direct": graph_direct,
                    "c0_vs_c1_graph": graph_candidate,
                }
            )
            if not passed:
                raise RuntimeError(f"correctness failed: S={sequence}, {domain}")

    payload = {
        "schema_version": "qwen35-s3-tile-ab-correctness-v1",
        "status": "PASS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target": {"device_index": index, "uuid": uuid},
        "runtime_identity": runtime,
        "p0": p0,
        "build_gate": build["identity"],
        "static_gate": static["identity"],
        "cases": cases,
        "timing_samples_emitted": 0,
    }
    write_json(run / exp_rel / "correctness.json", payload)


if __name__ == "__main__":
    main()
