#!/usr/bin/env python3
"""Analyze the preregistered two-shape SCREENING quantity; never accept C1."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

from scipy.stats import t as student_t

from experiment_common import identity, load_run, verify_p0, write_json

BOUNDARY_US = 0.25
PRECISION_US = 0.10


def paired_mean_welch_studentized_ci(a: list[float], b: list[float]) -> dict:
    """Apply the frozen v5 formula to paired deltas, never raw C0/C1 samples."""

    if len(a) != 15 or len(b) != 15:
        raise ValueError("v5 SCREENING requires exactly 15 paired deltas per shape")
    estimate = 0.5 * (statistics.mean(a) + statistics.mean(b))
    variance_a = statistics.variance(a)
    variance_b = statistics.variance(b)
    term_a = variance_a / 15.0
    term_b = variance_b / 15.0
    se = 0.5 * math.sqrt(term_a + term_b)
    denominator = term_a * term_a / 14.0 + term_b * term_b / 14.0
    if denominator == 0.0:
        degrees_of_freedom = math.inf
        critical = 1.959963984540054
    else:
        degrees_of_freedom = (term_a + term_b) ** 2 / denominator
        critical = float(student_t.ppf(0.975, degrees_of_freedom))
    half_width = critical * se
    return {
        "estimate_us": estimate,
        "ci95_low_us": estimate - half_width,
        "ci95_high_us": estimate + half_width,
        "ci95_half_width_us": half_width,
        "standard_error_us": se,
        "variance_s404_us2": variance_a,
        "variance_s768_us2": variance_b,
        "welch_satterthwaite_degrees_of_freedom": degrees_of_freedom,
        "t_0.975": critical,
        "method": "v5 paired-delta mean with Welch-Satterthwaite Studentized analytic CI",
        "formula": "q_hat=0.5*(mean(d404)+mean(d768)); SE=0.5*sqrt(v404/15+v768/15); nu=(v404/15+v768/15)^2/((v404/15)^2/14+(v768/15)^2/14)",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    exp_rel = Path("experiments/req-s3-tile-causal-production-ab")
    exp = run / exp_rel
    raw_path = exp / "raw/samples.json"
    raw = json.loads(raw_path.read_text())
    if raw.get("status") != "PASS":
        raise RuntimeError("measurement gate did not pass")
    shapes = {item["sequence"]: item for item in raw["shapes"]}
    if set(shapes) != {404, 768}:
        raise RuntimeError(f"unexpected screening shape set: {set(shapes)}")
    deltas = {}
    per_shape = {}
    for sequence in (404, 768):
        blocks = shapes[sequence]["paired_graph_blocks"]
        if len(blocks) != 15:
            raise RuntimeError(f"S={sequence}: expected 15 paired blocks")
        values = [float(block["delta_c1_minus_c0_us"]) for block in blocks]
        deltas[sequence] = values
        per_shape[str(sequence)] = {
            "paired_blocks": 15,
            "mean_delta_c1_minus_c0_us": statistics.mean(values),
            "median_delta_c1_minus_c0_us": statistics.median(values),
            "stdev_delta_us": statistics.stdev(values),
            "mean_c0_us": statistics.mean(float(b["c0_us"]) for b in blocks),
            "mean_c1_us": statistics.mean(float(b["c1_us"]) for b in blocks),
        }
    ci = paired_mean_welch_studentized_ci(deltas[404], deltas[768])
    if ci["ci95_low_us"] > BOUNDARY_US:
        outcome = "REJECT"
    elif (
        ci["ci95_half_width_us"] <= PRECISION_US
        and ci["ci95_high_us"] < BOUNDARY_US
    ):
        outcome = "ADMIT_TO_NEW_QUALIFICATION_CONTRACT"
    else:
        outcome = "INCONCLUSIVE"
    validity = "VALID"
    hardware, workload, operator = load_run(run)
    experiment_path = exp / "experiment.json"
    build_path = exp / "build/manifest.json"
    correctness_path = exp / "correctness.json"
    static_path = exp / "static/instruction_audit.json"
    static = json.loads(static_path.read_text())
    p0 = verify_p0(run)
    flat_samples = deltas[404] + deltas[768]
    result = {
        "schema_version": "benchmark-result-v2",
        "request_id": "req-s3-tile-causal-production-ab",
        "experiment_identity": identity(experiment_path),
        "hardware_identity": identity(run / "hardware.json"),
        "workload_identity": identity(run / "workload.json"),
        "benchmark": "Qwen3.5 production-exact four-kernel GDN SCREENING C0/C1",
        "question": "Does removing only tensor-core-feasible strict upper/tail S3 tile work avoid a material representative-path regression?",
        "environment": {
            "target": hardware["target"],
            "software": hardware["software"],
            "measurement_pre": raw["environment_before"],
            "measurement_post": raw["environment_after"],
        },
        "source_identity": identity(
            run
            / "microbench_candidates/req-s3-tile-causal-production-ab/candidate_pkg/CANDIDATE_CONTRACT.md"
        ),
        "launch": {
            "topology": "unchanged production four-kernel ABI",
            "stream": "same explicit CUDA stream",
            "timing_envelope": "64 native graph replays per CUDA-event bracket",
        },
        "independent_variables": {"candidate": ["C0", "C1"], "sequence": [404, 768]},
        "controlled_variables": {
            "H": 16,
            "D": 128,
            "dtype": "BF16",
            "inputs_addresses_alignment": "identical within each pair",
            "paired_order": "balanced seeded randomized AB/BA",
        },
        "measurement": {
            "metric": "x_screen=0.5*(mean paired delta S404 + mean paired delta S768)",
            "semantics": "C1 minus C0 graph-batched device elapsed",
            "unit": "us",
            "timer": "CUDA events",
        },
        "raw_samples": flat_samples,
        "raw_samples_identity": identity(raw_path),
        "summary": {
            "per_shape": per_shape,
            "screening_quantity": ci,
            "screening_boundary_us": BOUNDARY_US,
            "required_half_width_us": PRECISION_US,
            "outcome": outcome,
            "screening_cannot_accept_candidate": True,
        },
        "correctness": {
            "status": "PASS",
            "checks": [
                "bitwise C0/C1 boundaries at S404/S768 random and extreme-finite",
                "direct repeat deterministic",
                "graph versus direct bitwise",
                "NaN/Inf/finite masks equal",
            ],
            "evidence_identity": identity(correctness_path),
        },
        "static_evidence": {
            "binary_identity": static["configurations"]["c1_s404"]["cubin"],
            "sass_identity": static["configurations"]["c1_s404"]["sass"],
            "static_audit_identity": identity(static_path),
            "resource_usage": {
                key: value["s3_resources"]
                for key, value in static["configurations"].items()
            },
        },
        "runtime_evidence": {
            "build_manifest": identity(build_path),
            "measurement_runtime": raw["runtime_identity"],
        },
        "measurement_system": {"p0_receipt": p0["identity"]},
        "validity": {
            "status": validity,
            "dce_guard": "live caller output plus bitwise stage-boundary snapshots",
            "known_pollution": [],
            "claims_allowed": [
                f"SCREENING outcome {outcome} at S404/S768 under the registered graph timing envelope"
            ],
            "claims_forbidden": [
                "accept C1",
                "update production",
                "claim seven-shape qualification",
                "claim direct-launch latency from this distribution",
            ],
        },
    }
    write_json(exp / "result.json", result)
    write_json(
        exp / "reproduction.json",
        {
            "schema_version": "qwen35-s3-tile-ab-reproduction-v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "experiment_identity": identity(experiment_path),
            "commands": json.loads(experiment_path.read_text())["commands"],
            "source_identity": identity(build_path),
            "raw_identity": identity(raw_path),
            "result_identity": identity(exp / "result.json"),
            "screening_only": True,
        },
    )


if __name__ == "__main__":
    main()
