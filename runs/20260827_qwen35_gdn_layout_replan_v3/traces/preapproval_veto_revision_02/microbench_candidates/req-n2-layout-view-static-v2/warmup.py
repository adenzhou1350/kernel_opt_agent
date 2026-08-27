#!/usr/bin/env python3
"""Verify zero dynamic execution; this phase does not warm up a GPU."""

from __future__ import annotations

import argparse
from pathlib import Path

from common import candidate_dir, dump, experiment_dir, identity, load


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    experiment = experiment_dir(run)
    manifest_path = experiment / "build/manifest.json"
    manifest = load(manifest_path)
    if any(manifest.get(field) != 0 for field in ("compiled_callable_invocations", "cuda_kernel_launches", "gpu_performance_samples")):
        raise RuntimeError("dynamic execution counter is nonzero")
    source_root = candidate_dir(run)
    source_text = "\n".join(path.read_text() for path in source_root.glob("*.py") if path.name != "warmup.py")
    forbidden = ("torch.cuda.Event", "perf_counter", "timeit", "compiled(")
    observed = [token for token in forbidden if token in source_text]
    if observed:
        raise RuntimeError(f"forbidden dynamic/timing API in static proof: {observed}")
    output = experiment / "controls/no_gpu_warmup.json"
    dump(output, {
        "schema_version": "zero-dynamic-execution-control-v1", "status": "PASS",
        "phase_semantics": "control validation only; no GPU warmup is performed",
        "compiled_callable_invocations": 0, "cuda_kernel_launches": 0,
        "cuda_events": 0, "gpu_performance_samples": 0,
        "launch_sites_in_compiled_source": "allowed but compiled callable is never invoked",
        "manifest_identity": identity(manifest_path),
    })
    print("PASS: zero dynamic execution control; no GPU warmup performed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
