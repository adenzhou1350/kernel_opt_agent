"""Shadow-test an option scorer for research next actions, without dispatching.

Only synthetic or explicitly public/sanitized text may be sent to the endpoint.
The reported conditional probabilities are uncalibrated and never grant authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
import urllib.request
from pathlib import Path


def load_cases(
    path: Path,
    extra_fields: frozenset[str] = frozenset(),
    *,
    unlabeled: bool = False,
) -> list[dict]:
    cases = []
    seen = set()
    required = {
        "id",
        "question",
        "state",
        "options",
        "expected_action",
        "data_classification",
    }
    if unlabeled:
        required.remove("expected_action")
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or set(row) != required | extra_fields:
            raise ValueError(f"line {number}: unexpected fields")
        if row["data_classification"] not in {"synthetic", "public_sanitized"}:
            raise ValueError(f"line {number}: unapproved data classification")
        if not isinstance(row["id"], str) or not row["id"] or row["id"] in seen:
            raise ValueError(f"line {number}: invalid or duplicate id")
        if any(
            not isinstance(row[k], str) or not 1 <= len(row[k]) <= limit
            for k, limit in (("question", 1000), ("state", 6000))
        ):
            raise ValueError(f"line {number}: invalid question/state")
        options = row["options"]
        if not isinstance(options, list) or not 2 <= len(options) <= 12:
            raise ValueError(f"line {number}: expected 2..12 options")
        ids = set()
        for option in options:
            if not isinstance(option, dict) or set(option) != {"id", "description"}:
                raise ValueError(f"line {number}: invalid option")
            if (
                not isinstance(option["id"], str)
                or not option["id"]
                or option["id"] in ids
                or not isinstance(option["description"], str)
                or not 1 <= len(option["description"]) <= 500
            ):
                raise ValueError(f"line {number}: invalid/duplicate option")
            ids.add(option["id"])
        if not unlabeled and row["expected_action"] not in ids:
            raise ValueError(f"line {number}: expected action is not an option")
        seen.add(row["id"])
        cases.append(row)
    if not cases:
        raise ValueError("no cases")
    return cases


def query_score(endpoint: str, case: dict, options: list[dict], timeout: float) -> dict:
    body = {
        "id": case["id"],
        "question": case["question"],
        "state": case["state"],
        "options": options,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def query_health(endpoint: str, timeout: float) -> dict:
    with urllib.request.urlopen(endpoint, timeout=timeout) as response:
        value = json.load(response)
    if not isinstance(value, dict) or value.get("ok") is not True:
        raise ValueError("service health check did not pass")
    return {
        key: value.get(key)
        for key in ("model", "model_revision", "semif_commit", "threshold")
    }


def top_choice(value: dict, expected_ids: list[str]) -> tuple[str, float]:
    ids, scores = value.get("option_ids"), value.get("probabilities")
    if ids != expected_ids or not isinstance(scores, list) or len(scores) != len(ids):
        raise ValueError("score response does not match requested options")
    if any(
        type(score) not in (float, int)
        or not math.isfinite(score)
        or not 0 <= score <= 1
        for score in scores
    ) or not math.isclose(sum(scores), 1.0, rel_tol=1e-5, abs_tol=1e-5):
        raise ValueError("invalid option probabilities")
    index = max(range(len(scores)), key=lambda i: scores[i])
    return ids[index], scores[index]


def evaluate(cases: list[dict], score) -> dict:
    rows = []
    call_seconds = []

    def timed_score(case, options):
        started = time.perf_counter()
        try:
            return score(case, options)
        finally:
            call_seconds.append(time.perf_counter() - started)

    for case in cases:
        try:
            options = case["options"]
            forward = timed_score(case, options)
            reverse = timed_score(case, list(reversed(options)))
            first, first_p = top_choice(forward, [option["id"] for option in options])
            second, second_p = top_choice(
                reverse, [option["id"] for option in reversed(options)]
            )
            forward_probs = dict(
                zip(forward["option_ids"], forward["probabilities"], strict=True)
            )
            reverse_probs = dict(
                zip(reverse["option_ids"], reverse["probabilities"], strict=True)
            )
            rows.append(
                {
                    "id": case["id"],
                    "state_sha256": hashlib.sha256(case["state"].encode()).hexdigest(),
                    "expected_action": case.get("expected_action"),
                    "forward_choice": first,
                    "forward_probabilities": forward_probs,
                    "forward_top_probability": first_p,
                    "forward_prompt_sha256": forward.get("prompt_sha256"),
                    "forward_total_seconds": forward.get("total_seconds"),
                    "reverse_choice": second,
                    "reverse_probabilities": reverse_probs,
                    "reverse_top_probability": second_p,
                    "reverse_prompt_sha256": reverse.get("prompt_sha256"),
                    "reverse_total_seconds": reverse.get("total_seconds"),
                    "consensus_action": first if first == second else None,
                    "order_probability_total_variation": 0.5
                    * sum(
                        abs(forward_probs[key] - reverse_probs[key])
                        for key in forward_probs
                    ),
                }
            )
        except (OSError, ValueError, KeyError, TypeError) as error:
            rows.append({"id": case["id"], "error": type(error).__name__})
    valid = [row for row in rows if "forward_choice" in row]
    consensus = [row for row in valid if row["consensus_action"] is not None]
    labeled = [row for row in valid if row["expected_action"] is not None]
    labeled_consensus = [row for row in consensus if row["expected_action"] is not None]
    ordered_seconds = sorted(call_seconds)

    def percentile(fraction):
        if not ordered_seconds:
            return None
        position = (len(ordered_seconds) - 1) * fraction
        lower = math.floor(position)
        upper = math.ceil(position)
        return ordered_seconds[lower] + (position - lower) * (
            ordered_seconds[upper] - ordered_seconds[lower]
        )

    return {
        "schema_version": "semantic-option-shadow-v1",
        "status": "COMPLETE" if len(valid) == len(rows) else "INCOMPLETE",
        "note": "Synthetic/public-sanitized pilot; uncalibrated scores; no automatic routing. Unlabeled cases measure stability and latency, not accuracy.",
        "summary": {
            "cases": len(rows),
            "valid": len(valid),
            "labeled_valid": len(labeled),
            "forward_correct": sum(
                r["forward_choice"] == r["expected_action"] for r in labeled
            )
            if labeled
            else None,
            "reverse_correct": sum(
                r["reverse_choice"] == r["expected_action"] for r in labeled
            )
            if labeled
            else None,
            "order_disagreements": len(valid) - len(consensus),
            "order_probability_total_variation": {
                "mean": sum(r["order_probability_total_variation"] for r in valid)
                / len(valid)
                if valid
                else None,
                "max": max(r["order_probability_total_variation"] for r in valid)
                if valid
                else None,
            },
            "consensus_coverage": len(consensus) / len(valid) if valid else None,
            "consensus_correct": sum(
                r["consensus_action"] == r["expected_action"] for r in labeled_consensus
            )
            if labeled
            else None,
            "score_calls": len(call_seconds),
            "client_seconds": {
                "total": sum(call_seconds),
                "p50": percentile(0.5),
                "p95": percentile(0.95),
                "includes": "request/response round trip, including failed calls",
            },
        },
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--health-url")
    parser.add_argument(
        "--unlabeled",
        action="store_true",
        help="Measure order stability and latency without accuracy labels",
    )
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    cases = load_cases(args.input, unlabeled=args.unlabeled)
    report = evaluate(
        cases,
        lambda case, options: query_score(args.endpoint, case, options, args.timeout),
    )
    if args.health_url:
        report["service"] = query_health(args.health_url, args.timeout)
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0 if report["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
