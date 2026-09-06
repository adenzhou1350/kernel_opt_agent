#!/usr/bin/env python3
"""Fail closed when the replay source or immutable manifests have drifted."""

import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


root = Path(__file__).resolve().parents[2]
candidate = Path(__file__).resolve().parent
identity = json.loads((candidate / "vllm-source-identity.json").read_text())
for item in identity["files"]:
    path = Path(item["windows_path"])
    if digest(path) != item["sha256"]:
        raise SystemExit(f"source drift: {path}")
for name in ("session-manifest.json", "treatment-torch.json", "treatment-lossless-packed.json"):
    json.loads((candidate / name).read_text(encoding="utf-8"))
assert (root / "models/lmhead-phase-timing.json").is_file()
