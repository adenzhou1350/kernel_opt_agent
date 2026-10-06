"""Run owner-reviewed repository pytest on one authorized NVIDIA Linux device.

Not a sandbox or an automatic Scout executor. No SSH, installs, model calls,
queue mutations, performance verdict or PR promotion. Reuses native JUnit/log
accounting and the existing full-UUID GPU admission/lock helpers.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import time

import kimi_scout_gpu_verify as gpu
import scout_native_run as native

MARKER = "SCOUT_NATIVE_GPU_IDENTITY="
BOOTSTRAP = '''import hashlib, importlib, json, pathlib, sys
import torch
uuid, memory_mib, modules = sys.argv[1:4]
root = pathlib.Path.cwd().resolve()
if torch.cuda.device_count() != 1:
    raise RuntimeError("expected exactly one visible CUDA device")
properties = torch.cuda.get_device_properties(0)
actual = str(getattr(properties, "uuid", ""))
if actual.lower().removeprefix("gpu-") != uuid.lower().removeprefix("gpu-"):
    raise RuntimeError("visible device UUID mismatch")
torch.cuda.set_device(0)
torch.cuda.set_per_process_memory_fraction(int(memory_mib)*1024*1024 / properties.total_memory, 0)
imports = {}
for name in json.loads(modules):
    module = importlib.import_module(name)
    path = pathlib.Path(module.__file__).resolve()
    if not path.is_relative_to(root):
        raise RuntimeError("import outside selected checkout: " + name)
    imports[name] = dict(path=str(path.relative_to(root)), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
record = dict(uuid=actual, visible_devices=1, memory_limit_mib=int(memory_mib),
              torch_version=torch.__version__, torch_path=torch.__file__, imports=imports)
print("SCOUT_NATIVE_GPU_IDENTITY=" + json.dumps(record), flush=True)
import pytest
code = pytest.main(sys.argv[4:])
torch.cuda.synchronize()
sys.exit(code)
'''


def identity(log, uuid, memory_mib, modules, source_hashes):
    records = [line[len(MARKER):] for line in log.splitlines() if line.startswith(MARKER)]
    if len(records) != 1:
        raise ValueError("missing or duplicate in-process GPU identity")
    record = json.loads(records[0])
    if (not isinstance(record, dict) or not isinstance(record.get("uuid"), str)
            or record["uuid"].lower().removeprefix("gpu-") != uuid.lower().removeprefix("gpu-")
            or record.get("visible_devices") != 1 or record.get("memory_limit_mib") != memory_mib
            or not isinstance(record.get("imports"), dict)
            or set(record["imports"]) != set(modules)):
        raise ValueError("GPU identity does not match reviewed invocation")
    for item in record["imports"].values():
        if (not isinstance(item, dict) or not isinstance(item.get("path"), str)
                or item.get("sha256") != source_hashes.get(item["path"])
                or item["path"] not in source_hashes):
            raise ValueError("observed import is not one of the reviewed source files")
    return record


def run(*, cwd, output, python, gpu_uuid, lock_dir, sources, expected_tests,
        modules, pytest_args, timeout=600, memory_mib=4096, environment=None):
    started = time.monotonic()
    if sys.platform != "linux":
        raise ValueError("use an authorized Linux worker; do not start local WSL")
    if not isinstance(gpu_uuid, str) or not re.fullmatch(gpu.UUID_RE, gpu_uuid):
        raise ValueError("a full GPU UUID is required")
    if type(memory_mib) is not int or not 1 <= memory_mib <= gpu.MAX_TORCH_ALLOC_MIB:
        raise ValueError("Torch allocation limit must be within 1..4096 MiB")
    if not 0 < timeout <= 3600 or not Path(python).is_absolute():
        raise ValueError("use an absolute interpreter and a timeout within 0..3600 seconds")
    if (not 1 <= len(modules) <= 16 or len(set(modules)) != len(modules)
            or any(not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", m) for m in modules)):
        raise ValueError("supply 1..16 distinct source import names")
    cwd = Path(cwd).resolve(strict=True)
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("use a fresh output directory")
    before = native.source_identities(cwd, sources)
    native.native.summarize("", format="pytest-junit", exit_code=0, expected_tests=expected_tests)
    environment = dict(environment or {})
    if environment.get("CUDA_VISIBLE_DEVICES", gpu_uuid) != gpu_uuid:
        raise ValueError("CUDA visibility override conflicts with selected UUID")
    environment.update(PYTHONPATH=str(cwd), PYTHONDONTWRITEBYTECODE="1",
                       TRITON_CACHE_DIR=str(output / "cache/triton"),
                       TORCH_EXTENSIONS_DIR=str(output / "cache/extensions"),
                       CUDA_CACHE_PATH=str(output / "cache/cuda"),
                       XDG_CACHE_HOME=str(output / "cache/xdg"))
    command = [str(python), "-B", "-c", BOOTSTRAP, gpu_uuid, str(memory_mib),
               json.dumps(list(modules)), *pytest_args]
    with gpu.gpu_lock(lock_dir, gpu_uuid):
        preflight = gpu.idle_samples(gpu_uuid)
        try:
            result = native.run(cwd=cwd, output=output, command=command, sources=sources,
                                format="pytest-junit", expected_tests=expected_tests,
                                environment=environment, timeout=timeout, _gpu_uuid=gpu_uuid)
        except Exception as error:  # Keep postflight evidence even when launch/accounting fails.
            output.mkdir(exist_ok=True)
            result = dict(status="INCONCLUSIVE", issues=["native invocation failed: " + str(error)],
                          summary=None, command=command, source_before=before,
                          boundary="No completed native test result. ")
        result["native_status"] = result["status"]
        result["gpu"] = dict(uuid=gpu_uuid, preflight=preflight,
                             lock_dir=str(Path(lock_dir).absolute()), memory_limit_mib=memory_mib)
        try:
            result["gpu"]["identity"] = identity(
                (output / "terminal.log").read_text(encoding="utf-8"),
                gpu_uuid, memory_mib, modules, before)
        except (OSError, ValueError, UnicodeError) as error:
            result["issues"].append(str(error))
        try:
            postflight = gpu.idle_samples(gpu_uuid)
            result["gpu"]["postflight"] = postflight
            # Preserve shared tasks. A new survivor is uncertain evidence, not
            # permission to signal an inventory PID.
            original = {p[1] for s in preflight for p in s["processes"]}
            if any(p[1] not in original for s in postflight for p in s["processes"]):
                result["issues"].append("new GPU process remains after owned child exit")
        except Exception as error:  # Any uncertain inventory prevents a PASS.
            result["issues"].append("postflight uncertain: " + str(error))
        if result["issues"]:
            result["status"] = "INCONCLUSIVE"
        result["total_wall_seconds"] = time.monotonic() - started
        result["boundary"] += (" Owner-reviewed native pytest only; observed CUDA mapping/imports "
                               "do not prove a complete environment or GPU kernel coverage. "
                               "Torch allocator cap does not limit non-Torch allocations; "
                               "device sharing is not performance qualification or a sandbox.")
        (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cwd", "output", "python", "gpu-uuid", "lock-dir"):
        parser.add_argument("--" + name, required=True)
    for name in ("source", "expect-test", "import-from-checkout"):
        parser.add_argument("--" + name, action="append", required=True)
    parser.add_argument("--env", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--memory-mib", type=int, default=4096)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        result = run(cwd=args.cwd, output=args.output, python=args.python,
                     gpu_uuid=args.gpu_uuid, lock_dir=args.lock_dir,
                     sources=native.assignments(args.source), expected_tests=args.expect_test,
                     modules=args.import_from_checkout,
                     pytest_args=args.pytest_args[1:] if args.pytest_args[:1] == ["--"] else args.pytest_args,
                     environment=dict(native.assignments(args.env, environment=True)),
                     timeout=args.timeout, memory_mib=args.memory_mib)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result))
    return {"TESTS_PASSED": 0, "TESTS_FAILED": 1, "INCONCLUSIVE": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
