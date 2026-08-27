#!/usr/bin/env python3
"""Seal the run-local N2 static gate with source, production and argv identities."""

from __future__ import annotations

import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/workspace/dance/qwen35/kernel_opt_agent")
RUN = ROOT / "runs/20260827_qwen35_gdn_layout_replan_v3"
REQUEST = "req-n2-layout-view-static-v2"
CANDIDATE = RUN / "microbench_candidates" / REQUEST
EXPERIMENT = RUN / "experiments" / REQUEST / "experiment.json"
CONTRACT = RUN / "models/admissibility_contracts/n2_zero_copy_layout_v1.json"
SOURCE_NAMES = (
    "analyze.py", "clean_build.py", "common.py", "correctness.py",
    "layout_proof.py", "measure.py", "static_audit.py", "warmup.py",
)
PRODUCTION = (
    Path("/workspace/dance/qwen35/flashinfer/flashinfer/gdn_kernels/delta_rule_dsl/qwen35_fla_s3_short_raw_sm120.py"),
    Path("/workspace/dance/qwen35/flashinfer/flashinfer/gdn_kernels/delta_rule_dsl/qwen35_fla_s3_long_raw_sm120.py"),
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path), "sha256": digest(path)}


def write(path: Path, data: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def call_name(node: ast.Call) -> str:
    function = node.func
    if isinstance(function, ast.Subscript):
        function = function.value
    parts = []
    while isinstance(function, ast.Attribute):
        parts.append(function.attr)
        function = function.value
    if isinstance(function, ast.Name):
        parts.append(function.id)
    return ".".join(reversed(parts))


def source_audit() -> dict:
    calls = []
    launch_sites = []
    compile_sites = []
    subprocess_sites = []
    forbidden = []
    for name in SOURCE_NAMES:
        path = CANDIDATE / name
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            qualified = call_name(node)
            calls.append((name, qualified, node.lineno))
            if qualified == "launch" or qualified.endswith(".launch"):
                launch_sites.append((name, node.lineno))
            if qualified == "cute.compile":
                compile_sites.append((name, node.lineno))
            if qualified == "subprocess.run":
                subprocess_sites.append((name, node.lineno))
            if qualified in {"time.perf_counter", "timeit.timeit", "torch.cuda.Event"}:
                forbidden.append((name, qualified, node.lineno))
            if isinstance(node.func, ast.Name) and node.func.id == "compiled":
                forbidden.append((name, "compiled_callable_invocation", node.lineno))
    if forbidden:
        raise RuntimeError(f"forbidden dynamic/timing calls: {forbidden}")
    if len(compile_sites) != 1 or compile_sites[0][0] != "clean_build.py":
        raise RuntimeError(f"expected one cute.compile source site in clean_build.py: {compile_sites}")
    if len(launch_sites) != 2 or any(name != "layout_proof.py" for name, _ in launch_sites):
        raise RuntimeError(f"launch sites must be limited to two compiled proof stubs: {launch_sites}")
    if len(subprocess_sites) != 1 or subprocess_sites[0][0] != "static_audit.py":
        raise RuntimeError(f"only static_audit cuobjdump subprocess is allowed: {subprocess_sites}")
    static_text = (CANDIDATE / "static_audit.py").read_text()
    if '"/usr/local/cuda/bin/cuobjdump"' not in static_text or '"--dump-sass"' not in static_text:
        raise RuntimeError("static_audit subprocess is not the exact cuobjdump whitelist")
    return {
        "status": "PASS", "compile_sites": compile_sites,
        "compiled_launch_sites": launch_sites, "subprocess_sites": subprocess_sites,
        "forbidden_dynamic_or_timing_calls": [],
    }


def main() -> None:
    experiment = json.loads(EXPERIMENT.read_text())
    if experiment.get("status") != "PLANNED" or experiment.get("request_id") != REQUEST:
        raise RuntimeError("experiment scaffold is not the expected PLANNED request")
    production_expected = {
        "qwen35_fla_s3_short_raw_sm120.py": "2b61b0da46b13802fcc75620fe7f87fe50d4de6660259327ee08696b0b83929f",
        "qwen35_fla_s3_long_raw_sm120.py": "2b647e3971a36929a2239c1ade1b4afec33894e0cb6ec638d6b0b046871e149f",
    }
    for path in PRODUCTION:
        if digest(path) != production_expected[path.name]:
            raise RuntimeError(f"production identity changed before seal: {path}")
    audit = source_audit()
    python = "/workspace/dance/qwen35/.venv-cu13/bin/python"
    commands = {}
    for phase in ("clean_build", "static_audit", "correctness", "warmup", "measure", "analyze"):
        commands[phase] = [[python, str(CANDIDATE / f"{phase}.py"), "--run", str(RUN)]]
    source_identities = [identity(CANDIDATE / name) for name in SOURCE_NAMES]
    source_identities.extend(identity(path) for path in PRODUCTION)
    experiment.update({
        "status": "MATERIALIZED", "sealed_at": datetime.now(timezone.utc).isoformat(),
        "commands": commands,
        "source": {
            "mode": "CREATE_RUN_LOCAL", "package_id": None,
            "candidate_path": str(CANDIDATE), "identities": source_identities,
        },
    })
    experiment["model_update_contract"]["summary_fields"] = [
        "static_admissibility", "n2_disposition", "predicate_id",
        "latency_model_update_authorized", "performance_top_two_update_authorized",
        "cuda_kernel_launches", "gpu_performance_samples",
    ]
    evidence_paths = [
        RUN / "experiments" / REQUEST / "catalog_query_receipt.json",
        CONTRACT,
        RUN / "models/production_constructor_bindings.json",
        RUN / "traces/preapproval_veto_revision_01/review_receipt.json",
        RUN / "traces/experiment_ranking_receipt.json",
        RUN / "traces/static_admissibility_replan_receipt.json",
    ]
    experiment["evidence"] = [identity(path) for path in evidence_paths]
    write(EXPERIMENT, experiment)

    queue_path = RUN / "models/experiment_queue.json"
    queue = json.loads(queue_path.read_text())
    request = next(item for item in queue["requests"] if item["request_id"] == REQUEST)
    request["status"] = "PLANNED"
    request["materialized_experiment"] = {**identity(EXPERIMENT), "status": "MATERIALIZED"}
    receipt = RUN / "experiments" / REQUEST / "catalog_query_receipt.json"
    queue["catalog_snapshot"] = {
        "status": "CURRENT",
        "catalog_identity": identity(ROOT / "microbench/catalog.json"),
        "request_receipts": [identity(receipt)],
    }
    write(queue_path, queue)

    seal_path = RUN / "traces/static_admissibility_experiment_seal_v2.json"
    write(seal_path, {
        "schema_version": "static-admissibility-experiment-seal-v2",
        "sealed_at": experiment["sealed_at"], "request_id": REQUEST,
        "experiment_identity": identity(EXPERIMENT), "queue_identity": identity(queue_path),
        "contract_identity": identity(CONTRACT), "source_identities": source_identities,
        "source_audit": audit, "process_launches": 6,
        "compiled_callable_invocations_authorized": 0, "cuda_kernel_launches_authorized": 0,
        "gpu_performance_samples_authorized": 0,
    })
    print(json.dumps({"status": "PASS", "seal": str(seal_path), "experiment_sha256": digest(EXPERIMENT)}, sort_keys=True))


if __name__ == "__main__":
    main()
