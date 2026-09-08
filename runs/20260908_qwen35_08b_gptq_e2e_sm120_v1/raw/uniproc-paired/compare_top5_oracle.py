#!/usr/bin/env python3
"""Apply the preregistered reciprocal top-5 correctness comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    control = read(args.control)
    candidate = read(args.candidate)
    control_tokens = control["generated_token_ids"]
    candidate_tokens = candidate["generated_token_ids"]
    control_logprobs = control["top5_logprobs"]
    candidate_logprobs = candidate["top5_logprobs"]
    failures = []
    comparisons = []

    if not (
        len(control_tokens)
        == len(candidate_tokens)
        == len(control_logprobs)
        == len(candidate_logprobs)
    ):
        failures.append({"kind": "REQUEST_COUNT_MISMATCH"})
    else:
        for request_index, (ct, ut, cl, ul) in enumerate(
            zip(
                control_tokens,
                candidate_tokens,
                control_logprobs,
                candidate_logprobs,
            )
        ):
            if not (len(ct) == len(ut) == len(cl) == len(ul) == 64):
                failures.append(
                    {
                        "kind": "LENGTH_MISMATCH",
                        "request_index": request_index,
                        "lengths": [len(ct), len(ut), len(cl), len(ul)],
                    }
                )
                continue
            nonfinite = any(
                not math.isfinite(float(item["logprob"]))
                for positions in (cl, ul)
                for position in positions
                for item in position.values()
            )
            if nonfinite:
                failures.append(
                    {"kind": "NONFINITE_LOGPROB", "request_index": request_index}
                )
                continue
            first_mismatch = next(
                (index for index, pair in enumerate(zip(ct, ut)) if pair[0] != pair[1]),
                None,
            )
            if first_mismatch is None:
                comparisons.append(
                    {
                        "request_index": request_index,
                        "status": "EXACT",
                    }
                )
                continue
            control_token = ct[first_mismatch]
            candidate_token = ut[first_mismatch]
            reciprocal = (
                str(control_token) in ul[first_mismatch]
                and str(candidate_token) in cl[first_mismatch]
            )
            comparison = {
                "request_index": request_index,
                "status": "RECIPROCAL_TOP5" if reciprocal else "FAIL",
                "first_mismatch": first_mismatch,
                "control_token": control_token,
                "candidate_token": candidate_token,
                "control_token_in_candidate_top5": str(control_token)
                in ul[first_mismatch],
                "candidate_token_in_control_top5": str(candidate_token)
                in cl[first_mismatch],
            }
            comparisons.append(comparison)
            if not reciprocal:
                failures.append({"kind": "TOP5_ORACLE_FAILURE", **comparison})

    payload = {
        "schema_version": "vllm-top5-logprob-correctness-result-v1",
        "status": "PASS" if not failures else "FAIL",
        "oracle": "vLLM check_logprobs_close reciprocal top-5 rule at first divergent token",
        "control": {"path": str(args.control), "sha256": digest(args.control)},
        "candidate": {"path": str(args.candidate), "sha256": digest(args.candidate)},
        "comparisons": comparisons,
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
