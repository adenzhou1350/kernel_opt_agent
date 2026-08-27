#!/usr/bin/env python3
"""Lifecycle control phase: assert that the static experiment has no warmup."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import dump, experiment_dir, identity


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    experiment = experiment_dir(run)
    manifest_path = experiment / "build/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("compiled_callable_invocations") != 0 or manifest.get("cuda_kernel_launches") != 0:
        raise RuntimeError("a compiled callable was invoked")
    output = experiment / "controls/no_gpu_warmup.json"
    dump(output, {
        "schema_version": "static-no-warmup-control-v1",
        "status": "PASS",
        "reason": "compiler/type proof has no dynamic warmup population",
        "compiled_callable_invocations": 0,
        "cuda_kernel_launches": 0,
        "build_manifest_identity": identity(manifest_path),
    })
    print("PASS: warmup is intentionally not applicable; CUDA launches=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
