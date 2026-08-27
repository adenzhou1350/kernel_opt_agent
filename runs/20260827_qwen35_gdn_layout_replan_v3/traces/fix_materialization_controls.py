#!/usr/bin/env python3
"""Archive the first v3 seal and correct validator-facing control wording."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


RUN = Path("/workspace/dance/qwen35/kernel_opt_agent/runs/20260827_qwen35_gdn_layout_replan_v3")
REQUEST = "req-n2-layout-view-static-v2"
TRACE = RUN / "traces/static_admissibility_revision_02/pre_materialization_validation_fix"


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> None:
    if TRACE.exists():
        raise FileExistsError(f"refusing to overwrite validation-fix archive: {TRACE}")
    TRACE.mkdir(parents=True)
    queue_path = RUN / "models/experiment_queue.json"
    experiment_path = RUN / f"experiments/{REQUEST}/experiment.json"
    seal_path = RUN / "traces/static_admissibility_experiment_seal_v3.json"
    shutil.copy2(queue_path, TRACE / "experiment_queue.before.json")
    shutil.copy2(experiment_path, TRACE / "experiment.before.json")
    shutil.copy2(seal_path, TRACE / "seal.before.json")

    controls = [
        "Zero dynamic execution: no compiled callable invocation, CUDA launch, event or timer.",
        "Positive control: actual eight-warp O1 and scoreV CuTe TV/partition mappings must agree with an independent PTX oracle.",
        "Actual fragment slice offsets must join the original O1 backing offsets one-to-one.",
        "Negative control: exact prior one-warp fragment plus cute.append layout must differ from production O1 ownership/layout.",
        "Live type control: typed scoreV C/D views and typed sink must compile; this is not production SASS/resource evidence.",
    ]
    queue = read(queue_path)
    request = next(item for item in queue["requests"] if item["request_id"] == REQUEST)
    request["controls"] = controls
    request["status"] = "PROPOSED"
    request.pop("materialized_experiment", None)
    write(queue_path, queue)
    write(TRACE / "receipt.json", {
        "schema_version": "preapproval-materialization-validation-fix-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "request_id": REQUEST,
        "change_scope": [
            "make positive/negative/live static controls explicit for generic validator",
            "seal script writes required model_update_contract.summary_fields",
        ],
        "candidate_source_changed": False,
        "contract_changed": False,
        "compiled": False,
        "cuda_kernel_launches": 0,
    })
    print(json.dumps({"status": "PASS", "trace": str(TRACE)}, sort_keys=True))


if __name__ == "__main__":
    main()
