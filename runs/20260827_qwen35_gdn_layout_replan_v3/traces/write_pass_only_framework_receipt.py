#!/usr/bin/env python3
"""Record the audited PASS-only static-lifecycle framework extension."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/workspace/dance/qwen35/kernel_opt_agent")
RUN = ROOT / "runs/20260827_qwen35_gdn_layout_replan_v3"
BACKUP = RUN / "traces/framework_pre_pass_only_lifecycle_v1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path), "sha256": digest(path)}


def main() -> None:
    path = RUN / "traces/framework_pass_only_lifecycle_v1_receipt.json"
    if path.exists():
        raise FileExistsError(f"refusing to overwrite framework receipt: {path}")
    before = [
        BACKUP / "approve_experiment.py",
        BACKUP / "supervision_utils.py",
        BACKUP / "candidate_admissibility_contract.schema.json",
        BACKUP / "test_static_admissibility_workflow.py",
    ]
    after = [
        ROOT / "scripts/approve_experiment.py",
        ROOT / "scripts/supervision_utils.py",
        ROOT / "schemas/candidate_admissibility_contract.schema.json",
        ROOT / "tests/test_static_admissibility_workflow.py",
    ]
    receipt = {
        "schema_version": "framework-patch-receipt-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "change": "add explicit PASS_ONLY_INVALID static lifecycle without weakening PASS_REJECT_INVALID support",
        "before_identities": [identity(item) for item in before],
        "after_identities": [identity(item) for item in after],
        "semantic_guards": [
            "PASS_ONLY_INVALID requires ADMIT and INVALID outcomes",
            "PASS_ONLY_INVALID forbids a REJECT outcome",
            "approval receipt emits the lifecycle actually registered by the contract",
            "static experiment remains zero-launch and non-performance",
        ],
        "tests": [
            {"name": "test_repository.py", "status": "PASS"},
            {"name": "test_evidence_closed_workflow.py", "status": "PASS"},
            {"name": "test_supervisor_replan_states.py", "status": "PASS"},
            {"name": "test_static_admissibility_workflow.py", "status": "PASS"},
            {"name": "audit_repository.py", "status": "PASS"},
        ],
        "generated_cache_quarantine": str(
            RUN / "traces/generated_cache_quarantine_20260827/scripts___pycache__"
        ),
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)
    print(json.dumps({"status": "PASS", "receipt": str(path)}, sort_keys=True))


if __name__ == "__main__":
    main()
