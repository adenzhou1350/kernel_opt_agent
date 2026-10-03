"""Offline cost vectors for research arms; never infer missing cost as zero.

No model, network or code execution. Call durations are additive invocation work,
not end-to-end latency: overlapping calls and shared setup need separate accounting.
Coverage is a caller declaration, not proof that no omitted attempt exists.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


STAGES = ("selection", "acquisition", "review", "verification")
UNITS = ("model_tokens", "call_seconds", "body_bytes", "gpu_seconds")
STATUSES = ("success", "failure", "not_run")


def nonnegative(value, name):
    if value is None:
        return None
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{name} must be a finite nonnegative number or null")
    if name in ("model_tokens", "body_bytes") and type(value) is not int:
        raise ValueError(f"{name} must be an integer or null")
    return value


def summarize_arm(attempts, *, inventory_complete=False, elapsed_wall_seconds=None):
    """Include failures/retries; require explicit zero for non-applicable units.

    One record per non-overlapping attempt; unique IDs prevent accidental duplicate
    accounting, not evidence forgery. A skipped stage still needs an explicit
    not_run record with measured/known zeroes. A missing measurement is null.
    """
    if type(inventory_complete) is not bool or not isinstance(attempts, list):
        raise ValueError("expected a boolean inventory_complete and an attempts list")
    elapsed = nonnegative(elapsed_wall_seconds, "elapsed_wall_seconds")
    known = dict.fromkeys(UNITS, 0)
    unknown = {unit: [] for unit in UNITS}
    seen, stages = set(), set()
    failures = 0
    for attempt in attempts:
        if not isinstance(attempt, dict) or set(attempt) - {
            "id", "stage", "status", *UNITS
        }:
            raise ValueError("invalid attempt fields")
        identity = attempt.get("id")
        stage, status = attempt.get("stage"), attempt.get("status")
        if not isinstance(identity, str) or not identity.strip() or len(identity) > 160:
            raise ValueError("invalid attempt id")
        if identity in seen:
            raise ValueError("duplicate attempt id")
        if stage not in STAGES or status not in STATUSES:
            raise ValueError("invalid stage/status")
        seen.add(identity)
        stages.add(stage)
        failures += status == "failure"
        for unit in UNITS:
            value = nonnegative(attempt.get(unit), unit)
            if value is None:
                unknown[unit].append(identity)
            else:
                if status == "not_run" and value != 0:
                    raise ValueError("not_run cannot have nonzero measured cost")
                known[unit] += value
                try:
                    finite = math.isfinite(known[unit])
                except OverflowError:
                    finite = False
                if not finite:
                    raise ValueError("cost sum overflow")
    missing = [stage for stage in STAGES if stage not in stages]
    # Complete in one unit does not make the other units complete.
    totals = {
        unit: known[unit] if inventory_complete and not missing and not unknown[unit]
        else None
        for unit in UNITS
    }
    return {
        "attempts": len(attempts),
        "failed_attempts": failures,
        "inventory_complete_declared": inventory_complete,
        "missing_stages": missing,
        "known_subtotals": known,
        "unknown_attempts_by_unit": unknown,
        "totals": totals,
        "elapsed_wall_seconds": elapsed,
        "claim_boundary": (
            "Caller-declared inventory only; call_seconds is not elapsed latency. "
            "No price conversion, matched-budget, independent quality or superiority claim."
        ),
    }


def summarize(arms):
    if not isinstance(arms, dict) or not arms:
        raise ValueError("expected nonempty arms object")
    result = {}
    for name, arm in arms.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(arm, dict):
            raise ValueError("invalid arm")
        if set(arm) - {"attempts", "inventory_complete", "elapsed_wall_seconds"}:
            raise ValueError("invalid arm fields")
        result[name] = summarize_arm(
            arm.get("attempts"),
            inventory_complete=arm.get("inventory_complete", False),
            elapsed_wall_seconds=arm.get("elapsed_wall_seconds"),
        )
    return {"arms": result, "winner": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON object mapping arm names to attempts")
    args = parser.parse_args()
    print(json.dumps(summarize(json.loads(args.input.read_text(encoding="utf-8"))),
                     ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
