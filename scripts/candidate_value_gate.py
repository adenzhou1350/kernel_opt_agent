#!/usr/bin/env python3
"""Reject low-value candidates before expensive qualification work."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from schema_utils import validate_instance


REQUEST_VERSION = "candidate-value-gate-v1"
RESULT_VERSION = "candidate-value-decision-v1"


def root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_object(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def review_cost_points(surface: dict) -> float:
    """Estimate permanent review cost without pretending it is runtime cost."""

    return round(
        1.0
        + max(surface["production_files_changed"] - 1, 0) * 0.5
        + surface["production_lines_changed"] / 100.0
        + 2.0 * int(surface["adds_protocol_variant"])
        + 3.0 * int(surface["adds_public_api"]),
        6,
    )


def evaluate(request: dict) -> dict:
    schema = read_object(root() / "schemas/candidate_value_gate.schema.json")
    errors = validate_instance(request, schema)
    if errors:
        raise ValueError("invalid candidate value request: " + "; ".join(errors))
    if request["schema_version"] != REQUEST_VERSION:
        raise ValueError("unsupported candidate value request")

    gain = request["expected_gain"]
    lower = gain["whole_workload_lower_percent"]
    median = gain["whole_workload_median_percent"]
    upper = gain["whole_workload_upper_percent"]
    if (lower is None) != (median is None):
        raise ValueError("expected gain lower and median must both be known or null")
    if lower is not None and median is not None and not lower <= median <= upper:
        raise ValueError("expected gain interval is not ordered")
    if median is not None and median > upper:
        raise ValueError("expected gain median exceeds its upper bound")

    surface = request["maintenance_surface"]
    cost = review_cost_points(surface)
    density = round(upper / cost, 6)
    policy = request["policy"]
    evidence = request["delivery_evidence"]
    reasons: list[str] = []

    if request["production_path_reachability"] != "CONFIRMED":
        action = "PROVE_REACHABILITY_FIRST"
        reasons.append("production path is not confirmed")
    elif upper < policy["materiality_floor_percent"]:
        action = "STOP_LOW_VALUE_BEFORE_HEAVY_VALIDATION"
        reasons.append("optimistic whole-workload gain is below the materiality floor")
    elif not all(
        (
            evidence["focused_correctness_pass"],
            evidence["clean_commit"],
            evidence["reproduction_command_present"],
        )
    ):
        action = "COMPLETE_DRAFT_MINIMUM"
        reasons.append("focused correctness, clean commit, or reproduction is missing")
    elif (
        request["workload_coverage_fraction"] < policy["narrow_scope_fraction"]
        and (surface["adds_protocol_variant"] or surface["adds_public_api"])
        and density < policy["minimum_gain_density_percent_per_point"]
    ):
        action = "HOLD_AT_DRAFT_LOW_VALUE_DENSITY"
        reasons.append(
            "narrow workload coverage does not justify permanent interface cost"
        )
    elif not all(
        (
            evidence["real_workload_pass"],
            evidence["target_hardware_pass"],
            evidence["no_regression_pass"],
        )
    ):
        action = "OPEN_OR_KEEP_DRAFT_PENDING_QUALIFICATION"
        reasons.append(
            "draft minimum passes but production qualification is incomplete"
        )
    elif lower is None or lower < policy["materiality_floor_percent"]:
        action = "KEEP_DRAFT_MATERIALITY_UNCERTAIN"
        reasons.append("qualified lower bound does not clear the materiality floor")
    else:
        action = "READY_FOR_REVIEW"
        reasons.append("value, correctness, and production qualification gates pass")

    return {
        "schema_version": RESULT_VERSION,
        "generated_at": now(),
        "candidate_id": request["candidate_id"],
        "recommended_action": action,
        "review_cost_points": cost,
        "optimistic_gain_density_percent_per_point": density,
        "reasons": reasons,
        "claim_boundary": (
            "PRE_IMPLEMENTATION_VALUE_AND_DELIVERY_ROUTING_NOT_PERFORMANCE_PROOF"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    request_path = args.request.resolve()
    result = evaluate(read_object(request_path))
    result["request_identity"] = {
        "path": request_path.as_posix(),
        "sha256": sha256_file(request_path),
    }
    if args.output:
        atomic_json(args.output.resolve(), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
