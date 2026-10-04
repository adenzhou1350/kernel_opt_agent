"""CPU-only import preflight for a reviewed, hash-pinned CAKE source tree.

This does not install dependencies, build kernels, or qualify attention results.
The subprocess executes trusted source, not an untrusted-code sandbox.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def verified_file(root, relative, expected):
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError("expected SHA256 must be 64 lowercase hex characters")
    root = Path(root).resolve(strict=True)
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError("module escapes the selected source root")
    with path.open("rb") as stream:
        observed = hashlib.file_digest(stream, "sha256").hexdigest()
    if observed != expected:
        raise ValueError(f"source hash mismatch: {relative}")
    return root, path


CHILD = """
import importlib, importlib.metadata, json, pathlib, sys, torch
root = pathlib.Path(__import__('sys').argv[1]).resolve()
record = {'cuda_initialized_before': torch.cuda.is_initialized(), 'packages': {}}
for name in ('torch', 'apache-tvm-ffi', 'nvidia-cutlass-dsl', 'flashinfer-jit-cache'):
    try:
        record['packages'][name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        record['packages'][name] = None
try:
    if record['cuda_initialized_before']:
        raise RuntimeError('CUDA already initialized before source import')
    module = importlib.import_module('flashinfer.mla.cake_kimi_k3_mla')
    origin = pathlib.Path(module.__file__).resolve()
    if not origin.is_relative_to(root):
        raise RuntimeError('CAKE module resolved outside the selected source')
    record['module_path'] = str(origin)
    record['launcher'] = module.KimiK3MlaFp8PagedAttention.__module__
    record['status'] = 'CPU_IMPORT_PASS'
except Exception as error:
    record.update(status='ENVIRONMENT_IMPORT_BLOCKED', error_type=type(error).__name__, error=str(error))
record['loaded_modules'] = {}
for name in ('torch', 'tvm_ffi', 'cutlass.cute', 'flashinfer_jit_cache'):
    loaded = sys.modules.get(name)
    if loaded is not None:
        record['loaded_modules'][name] = {'path': getattr(loaded, '__file__', None),
                                        'version': getattr(loaded, '__version__', None)}
if len(sys.argv) > 2 and record['status'] == 'CPU_IMPORT_PASS':
    shim_root = pathlib.Path(sys.argv[2]).resolve()
    shim = record['loaded_modules'].get('flashinfer_jit_cache', {})
    if not shim.get('path') or not pathlib.Path(shim['path']).resolve().is_relative_to(shim_root):
        record.update(status='ENVIRONMENT_IMPORT_BLOCKED', error_type='RuntimeError',
                      error='JIT-cache shim resolved outside the selected source')
record['cuda_initialized_after'] = torch.cuda.is_initialized()
if record['cuda_initialized_after']:
    record['status'] = 'UNEXPECTED_CUDA_INITIALIZATION'
print('CAKE_IMPORT_RESULT=' + json.dumps(record))
raise SystemExit(0 if record['status'] == 'CPU_IMPORT_PASS' else 1)
"""


def preflight(source, source_sha256, shim_source=None, shim_sha256=None, timeout=60):
    source, _ = verified_file(
        source, "flashinfer/mla/cake_kimi_k3_mla.py", source_sha256
    )
    if bool(shim_source) != bool(shim_sha256):
        raise ValueError("shim source and hash must be supplied together")
    if not 1 <= timeout <= 120:
        raise ValueError("timeout must be between 1 and 120 seconds")
    paths = [str(source)]
    if shim_source:
        shim_source, _ = verified_file(
            shim_source, "flashinfer_jit_cache/__init__.py", shim_sha256
        )
        paths.append(str(shim_source))
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(paths),
        "PYTHONDONTWRITEBYTECODE": "1",
        "CUDA_VISIBLE_DEVICES": "-1",
        "FLASHINFER_DISABLE_JIT": "1",
        "FLASHINFER_NO_DOWNLOAD": "1",
    }
    started = time.monotonic()
    # Keep potentially verbose package initialization out of process memory.
    with tempfile.TemporaryDirectory(prefix="cake-import-") as cache:
        env["FLASHINFER_WORKSPACE_BASE"] = cache
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                command = [sys.executable, "-B", "-c", CHILD, str(source)]
                if shim_source:
                    command.append(str(shim_source))
                result = subprocess.run(
                    command,
                    cwd=source,
                    env=env,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=timeout,
                    check=False,
                )
                exit_code = result.returncode
            except subprocess.TimeoutExpired:
                exit_code = None
            tails = []
            for stream in (stdout, stderr):
                size = stream.seek(0, os.SEEK_END)
                stream.seek(max(0, size - 8192))
                tails.append(stream.read().decode("utf-8", errors="replace"))
    records = [
        line.removeprefix("CAKE_IMPORT_RESULT=")
        for line in tails[0].splitlines()
        if line.startswith("CAKE_IMPORT_RESULT=")
    ]
    observed = json.loads(records[-1]) if records else {}
    status = observed.get("status", "IMPORT_PROCESS_FAILED")
    if exit_code is None:
        status = "IMPORT_TIMEOUT"
    elif exit_code != 0 and status == "CPU_IMPORT_PASS":
        status = "IMPORT_PROCESS_FAILED"
    return {
        **observed,
        "status": status,
        "exit_code": exit_code,
        "source": str(source),
        "source_sha256": source_sha256,
        "shim_source": str(shim_source) if shim_source else None,
        "shim_sha256": shim_sha256,
        "wall_seconds": time.monotonic() - started,
        "stdout_tail": tails[0],
        "stderr_tail": tails[1],
        "scope": "CPU import only; no kernel, attention, performance or dependency-closure qualification",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--jit-cache-source")
    parser.add_argument("--jit-cache-sha256")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    result = preflight(
        args.source,
        args.source_sha256,
        args.jit_cache_source,
        args.jit_cache_sha256,
        args.timeout,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "CPU_IMPORT_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
