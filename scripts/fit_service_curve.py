#!/usr/bin/env python3
"""Fit T(x)=alpha+beta*x from raw CSV points with bootstrap uncertainty."""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
from pathlib import Path


def ols(x, y):
    xm, ym = statistics.mean(x), statistics.mean(y)
    denom = sum((value - xm) ** 2 for value in x)
    if denom == 0:
        raise ValueError("x must contain at least two distinct values")
    beta = sum((a - xm) * (b - ym) for a, b in zip(x, y)) / denom
    alpha = ym - beta * xm
    residual = sum((b - alpha - beta * a) ** 2 for a, b in zip(x, y))
    total = sum((b - ym) ** 2 for b in y)
    return alpha, beta, 1.0 - residual / total if total else 1.0


def quantile(values, fraction):
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--x", default="repeat")
    parser.add_argument("--y", default="gpu_us")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap", type=int, default=20000)
    parser.add_argument("--filter", action="append", default=[], help="exact CSV filter COLUMN=VALUE; repeatable")
    parser.add_argument("--min-x", type=float)
    parser.add_argument("--max-x", type=float)
    args = parser.parse_args()
    filters = {}
    for expression in args.filter:
        if "=" not in expression:
            raise ValueError("--filter must use COLUMN=VALUE")
        key, value = expression.split("=", 1)
        filters[key] = value
    groups = {}
    with args.input.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if any(row.get(key) != value for key, value in filters.items()):
                continue
            x_value = float(row[args.x])
            if args.min_x is not None and x_value < args.min_x:
                continue
            if args.max_x is not None and x_value > args.max_x:
                continue
            groups.setdefault(x_value, []).append(float(row[args.y]))
    if len(groups) < 2:
        raise ValueError("at least two distinct x values remain after filtering")
    xs = sorted(groups)
    ys = [statistics.median(groups[x]) for x in xs]
    alpha, beta, r2 = ols(xs, ys)
    rng = random.Random(20260826)
    slopes = []
    for _ in range(args.bootstrap):
        sampled = [rng.choice(groups[x]) for x in xs]
        slopes.append(ols(xs, sampled)[1])
    local = [
        {"from": a, "to": b, "slope": (ys[i + 1] - ys[i]) / (b - a)}
        for i, (a, b) in enumerate(zip(xs, xs[1:]))
    ]
    result = {
        "schema_version": "service-curve-fit-v1",
        "model": "T(x)=alpha+beta*x",
        "input": str(args.input),
        "x": args.x,
        "y": args.y,
        "filters": filters,
        "x_range": {"min": args.min_x, "max": args.max_x},
        "points": [{"x": x, "samples": groups[x], "median": y} for x, y in zip(xs, ys)],
        "fit": {"alpha": alpha, "beta": beta, "r_squared": r2, "beta_p025": quantile(slopes, 0.025), "beta_p975": quantile(slopes, 0.975)},
        "local_slopes": local,
        "interpretation_required": ["intercept work", "one-repeat work", "cache semantics", "DCE guard", "source/sink pollution", "allowed and forbidden claims"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["fit"], sort_keys=True))


if __name__ == "__main__":
    main()
