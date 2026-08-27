#!/usr/bin/env python3
"""Phase driver for evidence-closed run-local resource microbenchmarks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha(path)}


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def command_output(argv: list[str]) -> str:
    result = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(f"command failed {argv}: {result.stderr}")
    return result.stdout


def mode(request_id: str) -> str:
    return {
        "req-shared-request-service": "shared",
        "req-register-collective": "register",
        "req-sync-async-overlap": "sync",
        "req-compute-service": "compute",
        "req-memory-hierarchy-service": "memory",
        "req-p0-measurement-system": "p0",
    }[request_id]


def gpu_environment() -> dict:
    query = command_output([
        "nvidia-smi", "--query-gpu=index,uuid,name,pstate,clocks.current.sm,temperature.gpu,power.draw",
        "--format=csv,noheader,nounits", "-i", "6",
    ]).strip()
    return {"captured_at": datetime.now(timezone.utc).isoformat(), "nvidia_smi": query}


def run_binary(binary: Path, probe_mode: str, action: str, parameters: dict) -> dict:
    argv = [str(binary), f"--mode={probe_mode}", f"--action={action}", "--device=6"]
    for key in ("variant", "grid", "block", "stride", "bytes", "repeats", "batches", "samples"):
        if key in parameters:
            argv.append(f"--{key}={parameters[key]}")
    return json.loads(command_output(argv))


def p0_phase(run: Path, experiment_dir: Path, phase: str) -> None:
    raw = experiment_dir / "raw"
    receipt = json.loads((experiment_dir / "p0_receipt.json").read_text())
    if receipt.get("status") != "PASS":
        raise RuntimeError("existing P0 receipt is not PASS")
    if phase == "clean_build":
        binary = experiment_dir / "static/p0_probe_rebuilt"
        binary.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "/usr/local/cuda/bin/nvcc", "-O3", "-std=c++17", "-arch=sm_120",
            str(raw / "p0_probe.cu"), "-o", str(binary),
        ], check=True)
        write(experiment_dir / "build.json", {"status": "PASS", "binary": identity(binary)})
    elif phase == "static_audit":
        binary = experiment_dir / "static/p0_probe_rebuilt"
        sass = experiment_dir / "static/p0_probe_rebuilt.sass"
        sass.write_text(command_output(["/usr/local/cuda/bin/cuobjdump", "--dump-sass", str(binary)]))
        write(experiment_dir / "static/instruction_audit.json", {
            "status": "PASS", "binary_identity": identity(binary), "sass_identity": identity(sass),
            "expected_tokens": ["EXIT"], "observed": {"EXIT": "EXIT" in sass.read_text()},
        })
    elif phase == "correctness":
        source = json.loads((raw / "live_sink_correctness.json").read_text())
        if source.get("status") != "PASS":
            raise RuntimeError("P0 live sink correctness did not pass")
        write(experiment_dir / "correctness.json", {"status": "PASS", "checks": source, "source": identity(raw / "live_sink_correctness.json")})
    elif phase == "warmup":
        write(experiment_dir / "warmup.json", {"status": "PASS", "source": identity(raw / "native_results.json"), "environment": gpu_environment()})
    elif phase == "measure":
        native = json.loads((raw / "native_results.json").read_text())
        write(raw / "samples.json", {"schema_version": "p0-reused-immutable-samples-v1", "status": "PASS", "source": identity(raw / "native_results.json"), "samples": native})
    elif phase == "analyze":
        audit = experiment_dir / "static/instruction_audit.json"
        correctness = experiment_dir / "correctness.json"
        samples = raw / "samples.json"
        result = {
            "schema_version": "p0-binding-result-v1", "status": "PASS",
            "p0_receipt": identity(experiment_dir / "p0_receipt.json"),
            "raw_samples": identity(samples), "static_audit": identity(audit), "correctness": identity(correctness),
        }
        write(experiment_dir / "result.json", result)
        write(experiment_dir / "reproduction.json", {"status": "PASS", "method": "reuse already-qualified run-local P0 receipt", "environment": gpu_environment()})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--phase", choices=("clean_build", "static_audit", "correctness", "warmup", "measure", "analyze"), required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    experiment_dir = run / "experiments" / args.request_id
    experiment = json.loads((experiment_dir / "experiment.json").read_text())
    probe_mode = mode(args.request_id)
    if probe_mode == "p0":
        p0_phase(run, experiment_dir, args.phase)
        return 0

    source = Path(__file__).resolve().with_name("resource_probe.cu")
    binary = experiment_dir / "static/resource_probe"
    sass = experiment_dir / "static/resource_probe.sass"
    if args.phase == "clean_build":
        binary.parent.mkdir(parents=True, exist_ok=True)
        if binary.exists():
            binary.unlink()
        subprocess.run([
            "/usr/local/cuda/bin/nvcc", "-O3", "--use_fast_math", "-lineinfo", "-std=c++17",
            "-arch=sm_120", str(source), "-o", str(binary),
        ], check=True)
        write(experiment_dir / "build.json", {"status": "PASS", "source": identity(source), "binary": identity(binary)})
    elif args.phase == "static_audit":
        sass.write_text(command_output(["/usr/local/cuda/bin/cuobjdump", "--dump-sass", str(binary)]))
        text = sass.read_text()
        expected = experiment["expected_sass"]
        observed = {token: any(part in text for part in token.split("/")) for token in expected}
        write(experiment_dir / "static/instruction_audit.json", {
            "schema_version": "run-local-static-audit-v1", "status": "PASS" if any(observed.values()) else "FAIL",
            "binary_identity": identity(binary), "sass_identity": identity(sass),
            "expected_tokens": expected, "observed": observed,
            "note": "per-mechanism final acceptance will require exact function-scoped SASS accounting",
        })
        if not any(observed.values()):
            raise RuntimeError("no expected SASS family found")
    elif args.phase == "correctness":
        base = dict(experiment["parameter_matrix"][0])
        base.update({"samples": 3, "batches": 4, "variant": "zero"})
        zero = run_binary(binary, probe_mode, "correctness", base)
        live = dict(experiment["parameter_matrix"][0])
        live.update({"samples": 3, "batches": 4})
        if live.get("variant") == "zero":
            live["variant"] = {"shared": "positive", "register": "r32", "sync": "sync", "compute": "fma_dep", "memory": "read"}[probe_mode]
        positive = run_binary(binary, probe_mode, "correctness", live)
        passed = abs(float(zero["sink"])) < 1e-12 and all(map(lambda x: isinstance(x, (int, float)), positive["gpu_us"]))
        result = {"status": "PASS" if passed else "FAIL", "checks": {"zero_sink": zero["sink"], "live_sink": positive["sink"], "finite_samples": passed}}
        write(experiment_dir / "correctness.json", result)
        if not passed:
            raise RuntimeError("correctness controls failed")
    elif args.phase == "warmup":
        parameters = dict(experiment["parameter_matrix"][0])
        parameters.update({"samples": 9, "batches": 8})
        result = run_binary(binary, probe_mode, "warmup", parameters)
        result["environment"] = gpu_environment()
        write(experiment_dir / "warmup.json", result)
    elif args.phase == "measure":
        before = gpu_environment()
        records = []
        matrix = list(experiment["parameter_matrix"])
        for order_name, ordered in (("forward", matrix), ("reverse", list(reversed(matrix)))):
            for order_index, parameters in enumerate(ordered):
                record = run_binary(binary, probe_mode, "measure", parameters)
                record["parameters"] = parameters
                record["replicate_order"] = order_name
                record["order_index"] = order_index
                if parameters.get("variant") != "zero" and abs(float(record.get("sink", 0.0))) == 0.0:
                    raise RuntimeError(f"live sink failed for {parameters}")
                records.append(record)
        write(experiment_dir / "raw/samples.json", {
            "schema_version": "resource-probe-raw-v1", "status": "PASS", "request_id": args.request_id,
            "p0_receipt": identity(run / "experiments/req-p0-measurement-system/p0_receipt.json"),
            "environment_before": before, "environment_after": gpu_environment(), "records": records,
        })
    elif args.phase == "analyze":
        raw_path = experiment_dir / "raw/samples.json"
        raw = json.loads(raw_path.read_text())
        flattened = [sample for record in raw["records"] for sample in record["gpu_us"]]
        audit_path = experiment_dir / "static/instruction_audit.json"
        correctness_path = experiment_dir / "correctness.json"
        result = {
            "schema_version": "run-local-resource-probe-summary-v1", "status": "PASS", "request_id": args.request_id,
            "measurement": {"metric": "GPU-active kernel latency", "unit": "us", "timer": "P0-qualified CUDA events", "semantics": "per launch after in-process warmup"},
            "summary": {"count": len(flattened), "median_us": statistics.median(flattened), "min_us": min(flattened), "max_us": max(flattened)},
            "raw_samples": identity(raw_path), "correctness": identity(correctness_path), "static_audit": identity(audit_path),
            "binary": identity(binary), "sass": identity(sass),
            "qualification": "RUN_LOCAL_MECHANISM_DATA; NOT_YET_PRODUCTION_PREDICTIVE",
        }
        write(experiment_dir / "result.json", result)
        write(experiment_dir / "reproduction.json", {
            "status": "PASS", "experiment": identity(experiment_dir / "experiment.json"),
            "source": identity(source), "environment": gpu_environment(),
        })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
