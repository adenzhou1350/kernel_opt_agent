#!/usr/bin/env python3
"""Optional, bounded CPU checks for trusted TIRx cases; no GPU allocation."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

PACKAGES = ("tirx-harness", "tirx-kernels", "apache-tvm", "numpy")


def versions():
    result = {}
    for name in PACKAGES:
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def save(path, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def evaluate(case, np, harness, cache):
    """A checker finding is FAIL; unsupported operations/execution errors are ERROR."""
    kernel = case["kernel"]
    kernel = getattr(kernel, "func", kernel)
    inputs = case["inputs"]
    expected = case["expected"]
    if not expected:
        raise ValueError("an independent expected-output mapping is required")
    rtol, atol = float(case["rtol"]), float(case["atol"])
    if any(not math.isfinite(x) or x < 0 for x in (rtol, atol)):
        raise ValueError("rtol/atol must be finite and nonnegative")
    if not set(expected).issubset(inputs):
        raise ValueError("expected output names must be bound in inputs")

    def fresh():
        return {key: value.copy() if isinstance(value, np.ndarray) else value
                for key, value in inputs.items()}

    checks = {}
    for name in ("synccheck", "racecheck"):
        try:
            report = getattr(harness, name)(kernel, inputs=fresh()).to_dict()
            # Unknown or incomplete verdicts must never become clean passes.
            verdict = report.get("verdict")
            status = "PASS" if verdict == "clean" else "FAIL" if verdict == "error" else "ERROR"
            checks[name] = {"status": status, "report": report}
        except Exception as exc:
            checks[name] = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
    if any(item["status"] != "PASS" for item in checks.values()):
        checks["numerical"] = {"status": "SKIPPED", "reason": "resolve checker findings/errors first"}
    else:
        try:
            module = harness.numsim.transpile(kernel, cache_dir=cache)
            simulation = harness.numsim.Engine(max_workers=1).run(
                module, inputs=fresh(), outputs=tuple(expected))
            outputs = {}
            for name, reference in expected.items():
                actual = np.asarray(simulation.outputs[name])
                reference = np.asarray(reference)
                if actual.shape != reference.shape:
                    outputs[name] = {"status": "FAIL", "reason": "shape mismatch"}
                    continue
                try:
                    np.testing.assert_allclose(actual, reference, rtol=rtol, atol=atol, equal_nan=False)
                    status = "PASS"
                except AssertionError:
                    status = "FAIL"
                delta = np.abs(actual.astype(np.float64) - reference.astype(np.float64))
                finite = bool(np.isfinite(actual).all() and np.isfinite(reference).all())
                outputs[name] = {"status": status if finite else "FAIL", "shape": list(actual.shape),
                                 "max_abs_error": float(delta.max()) if finite and delta.size else None}
            checks["numerical"] = {"status": "PASS" if all(x["status"] == "PASS" for x in outputs.values()) else "FAIL",
                                   "rtol": rtol, "atol": atol, "outputs": outputs,
                                   "diagnostics": repr(simulation.diagnostics)}
        except Exception as exc:
            checks["numerical"] = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
    statuses = {item["status"] for item in checks.values()}
    return {"status": "ERROR" if "ERROR" in statuses else "FAIL" if "FAIL" in statuses else "PASS", "checks": checks}


def worker(args):
    import numpy as np
    import tirx_harness as harness
    source = args.case_file.resolve()
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location("tirx_user_cases", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    cases = {}
    for name in args.case:
        started = time.monotonic()
        try:
            cases[name] = evaluate(module.make_case(name), np, harness, args.cache_dir)
        except Exception as exc:
            cases[name] = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
        cases[name]["elapsed_s"] = time.monotonic() - started
    after = hashlib.sha256(source.read_bytes()).hexdigest()
    states = {case["status"] for case in cases.values()}
    status = "ERROR" if before != after or "ERROR" in states else "FAIL" if "FAIL" in states else "PASS"
    save(args.output, {"status": status, "case_file": str(source), "source_sha256": before,
                      "source_unchanged": before == after, "versions": versions(), "cases": cases,
                      "scope": "CPU concrete-input checks; no GPU correctness or performance claim"})
    return 0 if status == "PASS" else 1 if status == "FAIL" else 2


def bounded_check(args):
    output = args.output.resolve()
    if output == args.case_file.resolve():
        raise ValueError("output must not overwrite the case source")
    output.parent.mkdir(parents=True, exist_ok=True)
    cache = args.cache_dir.resolve() if args.cache_dir else output.parent / "tirx-cache"
    cache.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "_check",
               "--case-file", str(args.case_file.resolve()), "--output", str(output),
               "--cache-dir", str(cache)]
    for name in args.case:
        command += ["--case", name]
    env = dict(os.environ, CUDA_VISIBLE_DEVICES="-1", PYTHONDONTWRITEBYTECODE="1",
               NUMSIM_CACHE_DIR=str(cache), NUMSIM_BUILD_CACHE_DIR=str(cache / "build"))
    started = time.monotonic()
    # Replace old results before launch so interrupted attempts cannot look successful.
    save(output, {"status": "RUNNING", "cases": args.case})
    with output.with_suffix(".stdout.log").open("w", encoding="utf-8") as stdout, output.with_suffix(".stderr.log").open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, env=env, stdout=stdout, stderr=stderr,
                                   start_new_session=os.name != "nt")
        try:
            code = process.wait(timeout=args.timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait()
            save(output, {"status": "ERROR", "reason": "timeout or interruption", "elapsed_s": time.monotonic() - started})
            return 2
    result = json.loads(output.read_text(encoding="utf-8"))
    if result["status"] == "RUNNING":
        save(output, {"status": "ERROR", "reason": "worker failed before producing results", "returncode": code})
        return 2
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("probe", help="package metadata only; no compiler or GPU imports")
    for action in ("check", "_check"):
        child = actions.add_parser(action)
        child.add_argument("--case-file", type=Path, required=True, help="trusted Python defining make_case(name)")
        child.add_argument("--case", action="append", required=True)
        child.add_argument("--output", type=Path, required=True)
        child.add_argument("--cache-dir", type=Path)
        child.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    if args.action == "probe":
        print(json.dumps({"python": sys.version, "versions": versions()}))
        return 0
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be finite and positive")
    return worker(args) if args.action == "_check" else bounded_check(args)


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
