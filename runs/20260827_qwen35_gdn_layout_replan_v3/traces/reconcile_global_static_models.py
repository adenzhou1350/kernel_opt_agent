#!/usr/bin/env python3
"""Rebind stale static request references after the admitted preapproval revision."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


RUN = Path("/workspace/dance/qwen35/kernel_opt_agent/runs/20260827_qwen35_gdn_layout_replan_v3")
OLD = "req-n2-static-layout-admissibility"
NEW = "req-n2-layout-view-static-v2"
TRACE = RUN / "traces/static_admissibility_revision_02/global_model_rebind"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path), "sha256": digest(path)}


def read(path: Path) -> object:
    return json.loads(path.read_text())


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def replace_exact(value: object) -> tuple[object, int]:
    if isinstance(value, str):
        return (NEW, 1) if value == OLD else (value, 0)
    if isinstance(value, list):
        output = []
        count = 0
        for item in value:
            changed, observed = replace_exact(item)
            output.append(changed)
            count += observed
        return output, count
    if isinstance(value, dict):
        output = {}
        count = 0
        for key, item in value.items():
            changed, observed = replace_exact(item)
            output[key] = changed
            count += observed
        return output, count
    return value, 0


def main() -> None:
    if TRACE.exists():
        raise FileExistsError(f"refusing to overwrite global-model rebind trace: {TRACE}")
    TRACE.mkdir(parents=True)
    resource_path = RUN / "models/resource_balance.json"
    state_path = RUN / "models/global_schedule_state.json"
    shutil.copy2(resource_path, TRACE / "resource_balance.before.json")
    shutil.copy2(state_path, TRACE / "global_schedule_state.before.json")

    resource, replacement_count = replace_exact(read(resource_path))
    if replacement_count <= 0:
        raise RuntimeError("no stale unresolved request references were found")
    if OLD in json.dumps(resource, sort_keys=True):
        raise RuntimeError("stale request remains after exact-value rebind")
    write(resource_path, resource)

    state = read(state_path)
    assert isinstance(state, dict)
    state["status"] = "MODEL_READY"
    state["decision_policy"]["objective"]["measurement_semantics"]["static_gate"] = (
        "compiler/type proof may only admit N2 logical layout feasibility; any failure is INVALID/BLOCKED"
    )
    state["decision_policy"]["active_static_policy"] = (
        "PASS_ONLY_INVALID; no performance ranking and no candidate rejection"
    )
    state["active_subdecision"] = {
        "request_id": NEW,
        "quantity_id": "n2_layout_view_feasible",
        "unit": "binary_pass",
        "performance_ranking": False,
        "candidate_rejection_authorized": False,
    }
    state.setdefault("revision_history", []).append({
        "revision": 2,
        "at": datetime.now(timezone.utc).isoformat(),
        "reason": "rebind unresolved resource evidence to PASS-only N2 layout-view request; numeric resource evidence unchanged",
    })
    write(state_path, state)

    receipt_path = TRACE / "receipt.json"
    write(receipt_path, {
        "schema_version": "global-static-model-rebind-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "old_request_id": OLD,
        "new_request_id": NEW,
        "exact_string_replacements": replacement_count,
        "numeric_resource_fields_changed": False,
        "resource_before_identity": identity(TRACE / "resource_balance.before.json"),
        "state_before_identity": identity(TRACE / "global_schedule_state.before.json"),
        "resource_after_identity": identity(resource_path),
        "state_after_identity": identity(state_path),
        "status": "MODEL_READY_PENDING_SUPERVISOR_DISPATCH",
    })
    print(json.dumps({"status": "PASS", "replacements": replacement_count, "receipt": str(receipt_path)}, sort_keys=True))


if __name__ == "__main__":
    main()
