#!/usr/bin/env python3
"""Required lifecycle phase; a deliberate zero-execution no-op."""

from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    EXPERIMENT_ROOT,
    dump,
    gate,
    require_run,
    verify_bound_sources,
    verify_experiment_source_seal,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = require_run(args.run)
    experiment = verify_experiment_source_seal(run)
    sources = verify_bound_sources()
    upstream = {
        "build": gate(EXPERIMENT_ROOT / "build/manifest.json")["identity"],
        "static": gate(EXPERIMENT_ROOT / "static/instruction_audit.json")["identity"],
        "correctness": gate(EXPERIMENT_ROOT / "correctness.json")["identity"],
    }
    dump(EXPERIMENT_ROOT / "warmup_receipt.json", {
        "schema_version": "qwen35-n1-n2-codegen-noop-v1",
        "status": "PASS",
        "phase": "warmup",
        "experiment_identity": experiment,
        "bound_sources": sources,
        "upstream_gates": upstream,
        "action": "NO_OP_STATIC_LIFECYCLE_GATE",
        "compiled_callable_invocations": 0,
        "cuda_kernel_launches": 0,
        "gpu_timers": 0,
        "performance_samples": 0,
    })
    print("PASS: zero-execution warmup lifecycle gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
