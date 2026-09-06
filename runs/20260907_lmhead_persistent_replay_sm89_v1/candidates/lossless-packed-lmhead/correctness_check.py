#!/usr/bin/env python3
"""Validate that the two replay arms differ only in the requested backend."""

import json
from pathlib import Path


root = Path(__file__).resolve().parent
baseline = json.loads((root / "treatment-torch.json").read_text(encoding="utf-8"))
candidate = json.loads(
    (root / "treatment-lossless-packed.json").read_text(encoding="utf-8")
)
assert baseline["label"] == "baseline"
assert candidate["label"] == "candidate"
assert baseline["lm_head_backend"] == "torch"
assert candidate["lm_head_backend"] == "lossless_packed"
for key in baseline.keys() & candidate.keys():
    if key not in {"label", "lm_head_backend"}:
        assert baseline[key] == candidate[key], key
