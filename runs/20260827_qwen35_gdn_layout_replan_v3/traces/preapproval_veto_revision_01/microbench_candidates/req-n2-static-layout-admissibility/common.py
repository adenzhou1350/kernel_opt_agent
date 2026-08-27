"""Shared immutable-path and JSON helpers for the static proof phases."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


REQUEST_ID = "req-n2-static-layout-admissibility"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def experiment_dir(run: Path) -> Path:
    return run / "experiments" / REQUEST_ID


def candidate_dir(run: Path) -> Path:
    return run / "microbench_candidates" / REQUEST_ID


def production_sources() -> dict[str, Path]:
    root = Path("/workspace/dance/qwen35/flashinfer/flashinfer/gdn_kernels/delta_rule_dsl")
    return {
        "short": root / "qwen35_fla_s3_short_raw_sm120.py",
        "long": root / "qwen35_fla_s3_long_raw_sm120.py",
    }
