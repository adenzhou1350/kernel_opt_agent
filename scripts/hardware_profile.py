#!/usr/bin/env python3
"""Read-only device discovery and conditional, offline resource-gap arithmetic."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value


def number(value, label, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{label} must be a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value < 0 or (positive and value == 0):
        raise ValueError(
            f"{label} must be finite and {'positive' if positive else 'nonnegative'}"
        )
    return value


def estimate(model):
    """Calculate supplied constraints; never discover or certify their truth."""
    if not isinstance(model, dict):
        raise ValueError("model must be an object")
    context = {key: text(model.get(key), key) for key in ("device", "workload")}
    assumptions = model.get("assumptions")
    if not isinstance(assumptions, list) or not assumptions:
        raise ValueError("assumptions must describe the algorithm, precision and scope")
    for assumption in assumptions:
        text(assumption, "assumption")
    resources = model.get("resources")
    if not isinstance(resources, list):
        raise ValueError("resources must be a list")
    terms, unknowns, names, contradictions = [], [], set(), []
    for row in resources:
        if not isinstance(row, dict):
            raise ValueError("resource must be an object")
        name = text(row.get("name"), "resource name")
        if name in names:
            raise ValueError(f"duplicate resource: {name}")
        names.add(name)
        unit = row.get("unit")
        if unit not in ("bytes", "FLOP", "instructions"):
            raise ValueError(f"{name}: unit must be bytes, FLOP or instructions")
        minimum = row.get("minimum_work")
        if minimum is not None:
            number(minimum, f"{name} minimum_work")
            text(row.get("minimum_work_basis"), f"{name} minimum_work_basis")
        term = {"resource": name, "unit": unit, "lower_us": None, "reference_us": None}
        upper = row.get("upper_rate_per_second")
        if upper is not None:
            number(upper, f"{name} upper_rate_per_second", positive=True)
            text(row.get("upper_rate_basis"), f"{name} upper_rate_basis")
            if minimum is not None:
                term["lower_us"] = number(minimum / upper * 1e6, f"{name} lower_us")
        if term["lower_us"] is None:
            unknowns.append(f"{name}: no minimum-work/upper-capacity bound")
        measured = row.get("measured_rate_per_second")
        if measured is not None:
            number(measured, f"{name} measured_rate_per_second", positive=True)
            text(row.get("measurement_basis"), f"{name} measurement_basis")
            reference_work = number(row.get("reference_work"), f"{name} reference_work")
            if minimum is not None and reference_work < minimum:
                raise ValueError(
                    f"{name}: reference_work is below claimed minimum_work"
                )
            term["reference_us"] = number(
                reference_work / measured * 1e6, f"{name} reference_us"
            )
            if upper is not None and measured > upper:
                contradictions.append(
                    f"{name}: measured rate exceeds claimed upper capacity"
                )
        terms.append(term)
    dependency = model.get("dependency_lower_us")
    if dependency is not None:
        number(dependency, "dependency_lower_us")
        text(model.get("dependency_basis"), "dependency_basis")
    else:
        unknowns.append("dependency path not modeled")
    lower_terms = [row["lower_us"] for row in terms if row["lower_us"] is not None]
    if dependency is not None:
        lower_terms.append(dependency)
    lower = max(lower_terms) if lower_terms else None
    references = [
        row["reference_us"] for row in terms if row["reference_us"] is not None
    ]
    observed = model.get("observed_us")
    if observed is not None:
        number(observed, "observed_us", positive=True)
        text(model.get("observation_basis"), "observation_basis")
    if lower is not None and observed is not None and observed < lower:
        contradictions.append("observed time is below the conditional lower bound")
    contradicted = bool(contradictions)
    gap = None
    if lower and observed is not None and not contradicted:
        gap = number(observed / lower, "conditional_speedup_ceiling", positive=True)
    return {
        **context,
        "status": "MODEL_CONTRADICTION"
        if contradicted
        else "CONDITIONAL_ESTIMATE"
        if lower is not None
        else "NO_BOUND",
        "conditional_lower_us": lower,
        "empirical_resource_reference_us": max(references) if references else None,
        "observed_us": observed,
        "conditional_speedup_ceiling": gap,
        "limiting_known_resources": [
            row["resource"]
            for row in terms
            if lower is not None and row["lower_us"] == lower
        ],
        "terms": terms,
        "assumptions": assumptions,
        "unknowns": unknowns,
        "contradictions": contradictions,
        "limitations": [
            "Input evidence and applicability are supplied, not independently verified. No optimality or readiness certificate.",
            "Bounds require valid minimum work and upper capacities for this device, precision, algorithm class and execution scope.",
            "The maximum is a bound from known constraints, not an executable schedule. Forced serial dependencies belong in the dependency bound.",
            "Empirical references are not physical ceilings or full runtime predictions; compare matched shape, layout, cache, clocks and runtime.",
            "A model contradiction invalidates the gap claim; investigate assumptions, scope and measurement rather than claiming a super-physical result.",
        ],
    }


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser(
        "inspect", help="NVIDIA metadata only; no compile, install or workload"
    )
    inspect.add_argument("--output", type=Path)
    inspect.add_argument(
        "--cuda",
        action="store_true",
        help="query CUDA driver attributes in a bounded child; initializes driver, no context/kernel/build",
    )
    inspect.add_argument(
        "--topology",
        action="store_true",
        help="query management topology with before/after UUID checks; no transfers",
    )
    analyze = commands.add_parser(
        "estimate", help="offline arithmetic, not an automatic peak finder"
    )
    analyze.add_argument("--model", type=Path, required=True)
    analyze.add_argument("--output", type=Path)
    handoff = commands.add_parser(
        "handoff",
        help="brief a fresh agent from a captured profile; not a numeric optimum",
    )
    handoff.add_argument("--profile", type=Path, required=True)
    handoff.add_argument(
        "--device", help="exact UUID; mandatory if more than one device is visible"
    )
    handoff.add_argument(
        "--rates",
        type=Path,
        help="optional profile/UUID-bound documented or measured claims",
    )
    handoff.add_argument("--format", choices=("markdown", "json"), default="markdown")
    handoff.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            from hardware_probe import inspect_nvidia

            result = inspect_nvidia()
            if args.cuda:
                from hardware_cuda import inspect_cuda

                result["cuda_driver"] = inspect_cuda()
                if result["cuda_driver"]["status"] == "OBSERVED":
                    result["status"] = "OBSERVED"
            if args.topology:
                from hardware_topology import inspect_topology

                result["topology"] = inspect_topology(result["devices"])
        elif args.command == "estimate":
            raw = args.model.read_bytes()
            result = estimate(
                json.loads(raw.decode("utf-8-sig"), object_pairs_hook=no_duplicate_keys)
            )
            result["input_sha256"] = hashlib.sha256(raw).hexdigest()
        else:
            from hardware_handoff import build_handoff, render_handoff

            raw = args.profile.read_bytes()
            profile = json.loads(
                raw.decode("utf-8-sig"), object_pairs_hook=no_duplicate_keys
            )
            rates = None
            if args.rates:
                rates_raw = args.rates.read_bytes()
                rates = json.loads(
                    rates_raw.decode("utf-8-sig"), object_pairs_hook=no_duplicate_keys
                )
            result = build_handoff(
                profile,
                profile_sha256=hashlib.sha256(raw).hexdigest(),
                device_uuid=args.device,
                rates=rates,
            )
            result["profile_source"] = str(args.profile.resolve())
            if args.rates:
                result["rates_source"] = str(args.rates.resolve())
                result["rates_sha256"] = hashlib.sha256(rates_raw).hexdigest()
        if args.command == "handoff" and args.format == "markdown":
            serialized = render_handoff(result)
        else:
            serialized = json.dumps(result, indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            # Never replace previous measurements or even the input model.
            with args.output.open("x", encoding="utf-8", newline="\n") as output:
                output.write(serialized)
        print(serialized, end="")
        return 1 if result["status"] in ("UNAVAILABLE", "MODEL_CONTRADICTION") else 0
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
