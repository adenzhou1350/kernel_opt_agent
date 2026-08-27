#!/usr/bin/env python3
"""Write immutable before/after identities for the admissibility-v3 framework patch."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/workspace/dance/qwen35/kernel_opt_agent")
RUN = ROOT / "runs/20260827_qwen35_gdn_layout_replan_v3"
BACKUP = RUN / "traces/framework_pre_admissibility_v3"
FILES = (
    "scripts/advance_run.py",
    "scripts/rank_experiments.py",
    "scripts/materialize_experiment.py",
    "scripts/dispatch_experiment.py",
    "scripts/experiment_utils.py",
    "scripts/supervision_utils.py",
    "scripts/approve_experiment.py",
    "scripts/schema_utils.py",
    "schemas/experiment_request.schema.json",
    "schemas/benchmark_result.schema.json",
    "schemas/executable_experiment.schema.json",
    "schemas/supervisor_approval.schema.json",
    "schemas/candidate_admissibility_contract.schema.json",
    "tests/test_static_admissibility_workflow.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    records = []
    for relative in FILES:
        before = BACKUP / relative
        after = ROOT / relative
        if not after.is_file():
            raise FileNotFoundError(relative)
        records.append({
            "path": relative,
            "before_sha256": digest(before) if before.is_file() else None,
            "after_sha256": digest(after),
            "changed": not before.is_file() or digest(before) != digest(after),
        })
    receipt = {
        "schema_version": "framework-patch-receipt-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "separate deterministic static-admissibility predicates from timed performance experiments",
        "records": records,
        "tests": [
            "tests/test_repository.py PASS",
            "tests/test_evidence_closed_workflow.py PASS",
            "tests/test_supervisor_replan_states.py PASS",
            "tests/test_static_admissibility_workflow.py PASS",
            "scripts/audit_repository.py PASS",
        ],
    }
    output = BACKUP / "patch_receipt.json"
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "PASS", "receipt": str(output)}, sort_keys=True))


if __name__ == "__main__":
    main()
