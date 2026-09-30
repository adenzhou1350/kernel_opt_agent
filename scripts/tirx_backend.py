#!/usr/bin/env python3
"""Bounded TIRx CPU checks and generated-code inspection; no GPU allocation."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import re
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
            verdict = getattr(simulation, "verdict", None)
            checks["simulation"] = {"status": "PASS" if verdict == "clean" else "ERROR",
                                    "verdict": verdict, "diagnostics": simulation.diagnostics}
            outputs = {}
            for name, reference in expected.items():
                actual = np.asarray(simulation.outputs[name])
                reference = np.asarray(reference)
                if actual.shape != reference.shape:
                    outputs[name] = {"status": "FAIL", "reason": "shape mismatch"}
                    continue
                # Object integers retain all bits, including mixed signed/unsigned comparisons.
                exact = actual.dtype.kind in "biu" or reference.dtype.kind in "biu"
                left = actual.astype(object) if exact else actual.astype(np.complex128 if np.iscomplexobj(actual) else np.float64)
                right = reference.astype(object) if exact else reference.astype(np.complex128 if np.iscomplexobj(reference) else np.float64)
                try:
                    if exact:
                        np.testing.assert_array_equal(left, right)
                    else:
                        np.testing.assert_allclose(actual, reference, rtol=rtol, atol=atol, equal_nan=False)
                    status = "PASS"
                except AssertionError:
                    status = "FAIL"
                delta = np.abs(left - right)
                finite = bool(np.isfinite(actual).all() and np.isfinite(reference).all())
                max_error = delta.max() if finite and delta.size else None
                if isinstance(max_error, np.generic):
                    max_error = max_error.item()
                outputs[name] = {"status": status if finite else "FAIL", "shape": list(actual.shape),
                                 "max_abs_error": max_error}
            checks["numerical"] = {"status": "PASS" if all(x["status"] == "PASS" for x in outputs.values()) else "FAIL",
                                   "rtol": rtol, "atol": atol, "outputs": outputs}
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


def inspect_worker(args):
    from tirx_harness.dump_kernel import dump_module
    from tirx_kernels.runner import compile_kernel, cuda_initialization_guard, cuda_target
    source = args.case_file.resolve()
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location("tirx_user_cases", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    cases = {}
    with cuda_initialization_guard():
        for index, name in enumerate(args.case):
            started = time.monotonic()
            try:
                kernel = module.make_case(name)["kernel"]
                kernel = getattr(kernel, "func", kernel)
                with cuda_target():
                    executable = compile_kernel(kernel)
                # Use explicit architecture: inspection must not probe an arbitrary shared GPU.
                dumped = dump_module(executable, arch=args.arch, ptx=True, sass=True,
                                     outdir=str(args.output.parent / (args.output.stem + "-artifacts") / str(index)))
                artifacts = {key: {"path": path, "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
                             for key, path in dumped.paths.items()}
                cases[name] = {"status": "PASS" if dumped.ok else "ERROR", "arch": dumped.arch,
                               "symbols": dumped.symbols, "ptxas": dumped.ptxas, "errors": dumped.errors,
                               "artifacts": artifacts}
            except Exception as exc:
                cases[name] = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
            cases[name]["elapsed_s"] = time.monotonic() - started
    unchanged = before == hashlib.sha256(source.read_bytes()).hexdigest()
    status = "PASS" if unchanged and all(case["status"] == "PASS" for case in cases.values()) else "ERROR"
    save(args.output, {"status": status, "case_file": str(source), "source_sha256": before,
                      "source_unchanged": unchanged, "versions": versions(), "cases": cases,
                      "scope": "Compiler artifacts only; no GPU execution, correctness or performance claim"})
    return 0 if status == "PASS" else 2


def bounded_check(args):
    output = args.output.resolve()
    if output == args.case_file.resolve():
        raise ValueError("output must not overwrite the case source")
    output.parent.mkdir(parents=True, exist_ok=True)
    cache = args.cache_dir.resolve() if args.cache_dir else output.parent / "tirx-cache"
    cache.mkdir(parents=True, exist_ok=True)
    inspection = getattr(args, "action", "check") == "inspect"
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "_inspect" if inspection else "_check",
               "--case-file", str(args.case_file.resolve()), "--output", str(output),
               "--cache-dir", str(cache)]
    for name in args.case:
        command += ["--case", name]
    env = dict(os.environ, CUDA_VISIBLE_DEVICES="-1", PYTHONDONTWRITEBYTECODE="1",
               NUMSIM_CACHE_DIR=str(cache), NUMSIM_BUILD_CACHE_DIR=str(cache / "build"))
    if inspection:
        command += ["--arch", args.arch]
        env["TIRX_PREPARE_CUDA_ARCH"] = args.arch
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
    feedback = actions.add_parser("summarize", help="compact saved feedback; no compiler/model/GPU calls")
    feedback.add_argument("--result", type=Path, required=True)
    feedback.add_argument("--run", type=Path, help="optionally link raw evidence to an existing worklog")
    for action in ("check", "_check", "inspect", "_inspect"):
        child = actions.add_parser(action)
        child.add_argument("--case-file", type=Path, required=True, help="trusted Python defining make_case(name)")
        child.add_argument("--case", action="append", required=True)
        child.add_argument("--output", type=Path, required=True)
        child.add_argument("--cache-dir", type=Path)
        child.add_argument("--timeout", type=float, default=300)
        if action in ("inspect", "_inspect"):
            child.add_argument("--arch", required=True, help="explicit compiler target, e.g. sm_103a")
    args = parser.parse_args()
    if args.action == "probe":
        print(json.dumps({"python": sys.version, "versions": versions()}))
        return 0
    if args.action == "summarize":
        import tirx_feedback
        try:
            brief = tirx_feedback.summarize(args.result)
            if args.run:
                brief["notebook"] = tirx_feedback.record(args.run, brief, "tirx summarize (saved evidence only)")
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            parser.error(str(exc))
        print(json.dumps(brief, ensure_ascii=False, allow_nan=False))
        return 0
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be finite and positive")
    if args.action in ("inspect", "_inspect") and not re.fullmatch(r"sm_[0-9]+[af]?", args.arch):
        parser.error("arch must be an explicit CUDA SM target")
    if args.action == "_inspect":
        return inspect_worker(args)
    return worker(args) if args.action == "_check" else bounded_check(args)


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
