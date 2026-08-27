"""Immutable paths, hashing and atomic JSON helpers for the N2 static gate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


REQUEST_ID = "req-n2-layout-view-static-v2"
PRODUCTION_ROOT = Path("/workspace/dance/qwen35/flashinfer/flashinfer/gdn_kernels/delta_rule_dsl")
PRODUCTION_SOURCES = {
    "short": PRODUCTION_ROOT / "qwen35_fla_s3_short_raw_sm120.py",
    "long": PRODUCTION_ROOT / "qwen35_fla_s3_long_raw_sm120.py",
}
EXPECTED_PRODUCTION_HASHES = {
    "short": "2b61b0da46b13802fcc75620fe7f87fe50d4de6660259327ee08696b0b83929f",
    "long": "2b647e3971a36929a2239c1ade1b4afec33894e0cb6ec638d6b0b046871e149f",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def experiment_dir(run: Path) -> Path:
    return run / "experiments" / REQUEST_ID


def candidate_dir(run: Path) -> Path:
    return run / "microbench_candidates" / REQUEST_ID


def verify_production_sources() -> dict[str, dict]:
    bindings = {}
    for name, path in PRODUCTION_SOURCES.items():
        observed = sha256(path)
        expected = EXPECTED_PRODUCTION_HASHES[name]
        if observed != expected:
            raise RuntimeError(f"INFRA_FAILURE: production {name} identity changed: expected={expected}, observed={observed}")
        bindings[name] = identity(path)
    return bindings


__all__ = [
    "REQUEST_ID", "PRODUCTION_SOURCES", "EXPECTED_PRODUCTION_HASHES",
    "candidate_dir", "dump", "experiment_dir", "identity", "load", "sha256",
    "verify_production_sources",
]
