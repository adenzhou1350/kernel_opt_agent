#!/usr/bin/env python3
"""Create an isolated run-local reusable-microbenchmark candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from repository_rules import CANDIDATE_STATUS, DEFINITION_SCHEMA, PROMOTION_SCHEMA


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--id", required=True)
    parser.add_argument("--publish-path", required=True)
    parser.add_argument("--vendor", required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument("--question", action="append", required=True)
    args = parser.parse_args()

    slug = re.sub(r"[^a-z0-9_-]+", "-", args.id.lower()).strip("-")
    candidate_root = args.run.resolve() / "microbench_candidates"
    if not candidate_root.is_dir():
        raise ValueError(f"run does not own microbench_candidates/: {args.run}")
    state_path = args.run.resolve() / "run_state.json"
    if not state_path.exists():
        raise ValueError(f"run state is missing: {state_path}")
    state = json.loads(state_path.read_text())
    if state.get("current_phase") not in {"MODELING", "EXPERIMENT"}:
        raise ValueError("microbenchmark candidates may be created only during MODELING or EXPERIMENT")
    destination = candidate_root / slug
    if destination.exists():
        raise FileExistsError(f"candidate already exists: {destination}")
    destination.mkdir()

    definition = {
        "schema_version": DEFINITION_SCHEMA,
        "id": args.id,
        "publish_path": args.publish_path,
        "status": CANDIDATE_STATUS,
        "vendor": args.vendor,
        "family": args.family,
        "questions": args.question,
        "controlled_variables": [],
        "source_files": [],
        "driver_files": [],
        "analyzer_files": [],
        "measurement_semantics": {
            "timing_scope": None,
            "cache_state": None,
            "repetitions": None,
            "launch_geometry": None,
        },
        "correctness_controls": [],
        "dce_guard": None,
        "portability": {"hardware_parameters_explicit": [], "constraints": []},
        "known_pollution": [],
        "claims_allowed": [],
        "claims_forbidden": [],
        "qualification": {
            "highest_status": "DRAFT",
            "levels": [],
            "static_validation": "PENDING",
            "mechanism_validation": "PENDING",
            "device_calibration": "PENDING",
            "production_prediction": "UNASSESSED",
        },
        "genericity": {
            "application_independent": True,
            "production_dependencies": [],
            "hardware_parameters_explicit": True,
            "generated_artifacts_committed": False,
        },
    }
    definition_path = destination / "benchmark.json"
    definition_path.write_text(json.dumps(definition, indent=2, sort_keys=True) + "\n")
    evidence = {
        "schema_version": PROMOTION_SCHEMA,
        "candidate_id": args.id,
        "candidate_identity": {
            "path": str(definition_path),
            "sha256": hashlib.sha256(definition_path.read_bytes()).hexdigest(),
        },
        "checks": {
            name: {"status": "PENDING", "conclusion": None, "evidence": []}
            for name in (
                "correctness", "positive_and_negative_controls", "measurement_smoke",
                "clean_build", "cold_start_reproduction", "genericity_review",
                "static_instruction_validation", "mechanism_validation",
                "measurement_system_calibrated", "production_prediction_validation",
            )
        },
        "application_terms_removed": [],
        "reproduction_receipts": [],
        "registered_measurement_ids": [],
    }
    evidence_path = candidate_root / f"{slug}.promotion.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"candidate": str(destination), "promotion_evidence": str(evidence_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}")
        raise SystemExit(1)
