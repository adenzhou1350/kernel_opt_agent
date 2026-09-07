#!/usr/bin/env python3
"""Create or validate a CPU-only, hash-bound runtime readiness receipt."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from community_knowledge import atomic_json, now, read_object, sha256_file  # noqa: E402
from schema_utils import validate_json_file  # noqa: E402


SCHEMA_VERSION = "community-runtime-preflight-receipt-v1"
CHILD_PROBE = r"""
import importlib
import json
import sys

rows = []
for name in json.loads(sys.argv[1]):
    try:
        module = importlib.import_module(name)
        version = getattr(module, "__version__", None)
        origin = getattr(module, "__file__", None)
        rows.append({
            "module": name,
            "status": "PASS",
            "version": None if version is None else str(version),
            "origin": None if origin is None else str(origin),
            "origin_allowed": False,
            "error_type": None,
            "error_message": None,
        })
    except Exception as error:
        rows.append({
            "module": name,
            "status": "FAIL",
            "version": None,
            "origin": None,
            "origin_allowed": False,
            "error_type": type(error).__name__,
            "error_message": str(error)[:1000],
        })

torch_module = sys.modules.get("torch")
cuda_initialized = None
if torch_module is not None and hasattr(torch_module, "cuda"):
    cuda_initialized = bool(torch_module.cuda.is_initialized())
print(json.dumps({"probes": rows, "cuda_initialized": cuda_initialized}))
"""

INTERPRETER_PROBE = r"""
import json
import platform
import sys

print(json.dumps({
    "python_version": platform.python_version(),
    "sys_executable": sys.executable,
    "sys_prefix": sys.prefix,
    "sys_base_prefix": sys.base_prefix,
}))
"""


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def entry_is_within(path: Path, root: Path) -> bool:
    """Check the requested path without dereferencing a legitimate venv symlink."""
    entry = Path(os.path.abspath(path))
    boundary = Path(os.path.abspath(root))
    try:
        entry.relative_to(boundary)
    except ValueError:
        return False
    return True


def git_output(checkout: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(checkout), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout.strip()


def run_preflight(args: argparse.Namespace) -> dict:
    python = Path(os.path.abspath(args.python))
    resolved_python = python.resolve()
    environment_root = args.environment_root.resolve()
    source_checkout = args.source_checkout.resolve()
    pythonpath_roots = [path.resolve() for path in args.pythonpath_root]
    forbidden_roots = [path.resolve() for path in args.forbidden_root]
    if not python.is_file():
        raise ValueError(f"Python executable is missing: {python}")
    if not environment_root.is_dir():
        raise ValueError(f"environment root is missing: {environment_root}")
    if not source_checkout.is_dir():
        raise ValueError(f"source checkout is missing: {source_checkout}")
    for path in pythonpath_roots:
        if not path.is_dir():
            raise ValueError(f"PYTHONPATH root is missing: {path}")

    python_inside = entry_is_within(python, environment_root)
    environment_outside_forbidden = not any(
        is_within(environment_root, root) or is_within(root, environment_root)
        for root in forbidden_roots
    )
    try:
        observed_commit = git_output(source_checkout, "rev-parse", "HEAD")
        dirty = bool(git_output(source_checkout, "status", "--porcelain"))
    except (OSError, subprocess.SubprocessError):
        observed_commit = None
        dirty = None

    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if pythonpath_roots:
        prefix = os.pathsep.join(str(path) for path in pythonpath_roots)
        environment["PYTHONPATH"] = (
            prefix + os.pathsep + environment.get("PYTHONPATH", "")
        )
    interpreter = subprocess.run(
        [str(python), "-s", "-c", INTERPRETER_PROBE],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )
    interpreter_identity = json.loads(interpreter.stdout.strip())
    observed_prefix = Path(interpreter_identity["sys_prefix"])
    prefix_matches = observed_prefix.resolve() == environment_root.resolve()
    try:
        completed = subprocess.run(
            [str(python), "-s", "-c", CHILD_PROBE, json.dumps(args.require_import)],
            check=False,
            capture_output=True,
            text=True,
            timeout=args.timeout_seconds,
            env=environment,
        )
        child = (
            json.loads(completed.stdout.strip()) if completed.returncode == 0 else {}
        )
        probes = child.get("probes", [])
        cuda_initialized = child.get("cuda_initialized")
        if not probes:
            probes = [
                {
                    "module": "_preflight_process",
                    "status": "FAIL",
                    "version": None,
                    "origin": None,
                    "origin_allowed": False,
                    "error_type": "ChildProcessError",
                    "error_message": (
                        completed.stderr.strip()[:1000]
                        or f"return code {completed.returncode}"
                    ),
                }
            ]
    except subprocess.TimeoutExpired:
        probes = [
            {
                "module": "_preflight_process",
                "status": "FAIL",
                "version": None,
                "origin": None,
                "origin_allowed": False,
                "error_type": "TimeoutExpired",
                "error_message": f"preflight exceeded {args.timeout_seconds} seconds",
            }
        ]
        cuda_initialized = None

    allowed_origins = [environment_root, *pythonpath_roots]
    for probe in probes:
        origin = probe["origin"]
        probe["origin_allowed"] = bool(
            probe["status"] == "PASS"
            and (
                origin is None
                or any(is_within(Path(origin), root) for root in allowed_origins)
            )
        )
    checks = {
        "all_imports_passed": all(item["status"] == "PASS" for item in probes),
        "all_origins_allowed": all(item["origin_allowed"] for item in probes),
        "source_commit_matches": observed_commit == args.expected_source_commit,
        "source_checkout_clean": dirty is False,
        "python_inside_environment_root": python_inside,
        "python_prefix_matches_environment_root": prefix_matches,
        "environment_outside_forbidden_roots": environment_outside_forbidden,
        "cuda_initialized_after_imports": cuda_initialized,
    }
    status = (
        "PASS"
        if all(
            (
                checks["all_imports_passed"],
                checks["all_origins_allowed"],
                checks["source_commit_matches"],
                checks["source_checkout_clean"],
                checks["python_inside_environment_root"],
                checks["python_prefix_matches_environment_root"],
                checks["environment_outside_forbidden_roots"],
                cuda_initialized in {False, None},
            )
        )
        else "FAIL"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "observed_at": now(),
        "claim_boundary": "CPU_ONLY_IMPORT_AND_SOURCE_IDENTITY_NOT_GPU_EXECUTION",
        "status": status,
        "resource_id": args.resource_id,
        "environment": {
            "root": environment_root.as_posix(),
            "python_executable": python.as_posix(),
            "python_binary_resolved": resolved_python.as_posix(),
            "python_executable_sha256": sha256_file(resolved_python),
            "python_version": interpreter_identity["python_version"],
            "observed_sys_executable": Path(
                interpreter_identity["sys_executable"]
            ).as_posix(),
            "observed_sys_prefix": observed_prefix.as_posix(),
            "observed_sys_base_prefix": Path(
                interpreter_identity["sys_base_prefix"]
            ).as_posix(),
            "python_inside_environment_root": python_inside,
            "python_prefix_matches_environment_root": prefix_matches,
        },
        "pythonpath_roots": [path.as_posix() for path in pythonpath_roots],
        "forbidden_roots": [path.as_posix() for path in forbidden_roots],
        "source_checkout": {
            "path": source_checkout.as_posix(),
            "expected_commit": args.expected_source_commit,
            "observed_commit": observed_commit,
            "dirty": dirty,
        },
        "probes": probes,
        "checks": checks,
        "actions": {
            "packages_installed_by_preflight": False,
            "compilation_requested_by_preflight": False,
            "gpu_benchmarks_started": 0,
        },
    }


def validate_receipt(path: Path, root: Path | None = None) -> dict:
    root = root or repository_root()
    errors = validate_json_file(
        path.resolve(), root / "schemas/community_runtime_preflight_receipt.schema.json"
    )
    if errors:
        raise ValueError("invalid runtime preflight receipt: " + "; ".join(errors))
    receipt = read_object(path.resolve())
    checks = receipt["checks"]
    if (
        receipt["environment"]["python_inside_environment_root"]
        != checks["python_inside_environment_root"]
    ):
        raise ValueError("runtime preflight environment check is inconsistent")
    if (
        receipt["environment"]["python_prefix_matches_environment_root"]
        != checks["python_prefix_matches_environment_root"]
    ):
        raise ValueError("runtime preflight interpreter prefix is inconsistent")
    if checks["source_checkout_clean"] != (
        receipt["source_checkout"]["dirty"] is False
    ):
        raise ValueError("runtime preflight source cleanliness is inconsistent")
    expected_pass = all(
        (
            checks["all_imports_passed"],
            checks["all_origins_allowed"],
            checks["source_commit_matches"],
            checks["source_checkout_clean"],
            checks["python_inside_environment_root"],
            checks["python_prefix_matches_environment_root"],
            checks["environment_outside_forbidden_roots"],
            checks["cuda_initialized_after_imports"] in {False, None},
            all(item["status"] == "PASS" for item in receipt["probes"]),
            all(item["origin_allowed"] for item in receipt["probes"]),
        )
    )
    if (receipt["status"] == "PASS") != expected_pass:
        raise ValueError("runtime preflight status is inconsistent with checks")
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    run = commands.add_parser("run")
    run.add_argument("--python", type=Path, required=True)
    run.add_argument("--environment-root", type=Path, required=True)
    run.add_argument("--resource-id", required=True)
    run.add_argument("--source-checkout", type=Path, required=True)
    run.add_argument("--expected-source-commit", required=True)
    run.add_argument("--pythonpath-root", type=Path, action="append", default=[])
    run.add_argument("--forbidden-root", type=Path, action="append", default=[])
    run.add_argument("--require-import", action="append", required=True)
    run.add_argument("--timeout-seconds", type=int, default=120)
    run.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if (
        getattr(args, "timeout_seconds", 1) < 1
        or getattr(args, "timeout_seconds", 1) > 120
    ):
        parser.error("--timeout-seconds must be in [1, 120]")
    return args


def main() -> int:
    args = parse_args()
    if args.operation == "run":
        receipt = run_preflight(args)
        atomic_json(args.output.resolve(), receipt)
        validate_receipt(args.output)
        result = {"status": receipt["status"], "receipt": str(args.output.resolve())}
    else:
        receipt = validate_receipt(args.receipt)
        result = {"status": "PASS", "receipt_status": receipt["status"]}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
