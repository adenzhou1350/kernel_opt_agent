#!/usr/bin/env python3
"""Fail-closed zero-device wrapper for the six sealed experiment phases.

This file is a source scaffold only until the experiment is materialized and
independently approved.  At dispatch, every phase argv must be wrapped by this
program.  It performs a reachable Python-call-graph audit, builds or verifies
the sealed GNU LD_AUDIT interposer, injects it into the phase process tree, and
writes phase plus aggregate receipts from observed loader events.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
from collections import deque
from pathlib import Path

from common import (
    EXPERIMENT_ROOT,
    PYTHON,
    REQUEST_ID,
    RUN_ROOT,
    dump,
    identity,
    load,
    require_run,
    sha256,
    verify_bound_sources,
    verify_experiment_source_seal,
)


HARNESS_ROOT = Path(__file__).resolve().parent
INTERPOSER_SOURCE = HARNESS_ROOT / "zero_device_interposer.c"
AUDIT_ROOT = EXPERIMENT_ROOT / "zero_device_audit"
INTERPOSER_BINARY = AUDIT_ROOT / "build/libzero_device_audit.so"
INTERPOSER_MANIFEST = AUDIT_ROOT / "build/interposer_manifest.json"

PHASES = {
    "clean_build": "clean_build.py",
    "static_audit": "static_audit.py",
    "correctness": "correctness.py",
    "warmup": "warmup.py",
    "measure": "measure.py",
    "analyze": "analyze.py",
}
PHASE_ORDER = tuple(PHASES)
CALL_GRAPH_SOURCES = tuple(PHASES.values()) + ("common.py",)
SEALED_HARNESS_SOURCES = CALL_GRAPH_SOURCES + (
    "zero_device_audit.py",
    "zero_device_interposer.c",
)

CC = Path("/usr/bin/x86_64-linux-gnu-gcc-11")
NM = Path("/usr/bin/x86_64-linux-gnu-nm")
LOADER = Path("/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2")
LIBC = Path("/usr/lib/x86_64-linux-gnu/libc.so.6")
LIBCUDA = Path("/usr/lib/x86_64-linux-gnu/libcuda.so.1")
LIBCUDART = Path(
    "/usr/local/cuda/targets/x86_64-linux/lib/libcudart.so.13"
)
LIBCUPTI = Path("/usr/local/cuda/lib64/libcupti.so.13")
AUDITOR_DEPENDENCIES = (
    CC, NM, LOADER, LIBC, LIBCUDA, LIBCUDART, LIBCUPTI,
)

ZERO_COUNT_FIELDS = (
    "compiled_callable_invocations",
    "cuda_driver_launch_calls",
    "cuda_runtime_launch_calls",
    "cuda_graph_replay_calls",
    "cuda_event_or_timer_calls",
)

COVERAGE_BOUNDARY = {
    "covered": [
        "reachable calls rooted at main() in all six sealed Python phase files",
        "direct and PLT CUDA Driver/Runtime symbol binding in the phase process tree",
        "dlsym/dlvsym binding observed by GNU rtld la_symbind64",
        "cuGetProcAddress and cuGetProcAddress_v2 returned function pointers",
        "cudaGetDriverEntryPoint and ByVersion returned function pointers",
        "cuLaunch*/cudaLaunch*, cuGraphLaunch*/cudaGraphLaunch*, and all cuEvent*/cudaEvent* entries",
        "subprocesses that inherit LD_AUDIT and do not sanitize their environment",
    ],
    "not_covered_or_fail_closed": [
        "a component that issues raw NVIDIA device ioctls without a CUDA API symbol",
        "setuid/secure-execution children for which glibc discards LD_AUDIT",
        "a child that deliberately removes LD_AUDIT before exec",
        "foreign processes or persistent daemons outside the wrapped process tree",
        "undocumented hidden launch paths that bypass both exported bindings and CUDA function-pointer APIs",
    ],
    "policy": (
        "Missing AUDITOR|READY, an unsealed CUDA object origin, an unknown "
        "sensitive exported symbol, an auditor failure, or any sensitive "
        "invocation makes the phase INVALID. Raw-ioctl or environment-scrubbing "
        "code is outside this proof and is forbidden by the sealed source contract."
    ),
}


def call_name(node: ast.Call) -> str:
    try:
        return ast.unparse(node.func)
    except Exception:
        return ""


def module_name(path: Path) -> str:
    return path.stem


def is_cute_compile_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    text = ast.unparse(node.func)
    return text.startswith("cute.compile[")


def compiled_aliases(fn: ast.AST) -> set[str]:
    aliases = set()
    assignments = [
        node for node in ast.walk(fn)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    changed = True
    while changed:
        changed = False
        for statement in assignments:
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            value = statement.value
            seed = is_cute_compile_call(value)
            if isinstance(value, ast.Name) and value.id in aliases:
                seed = True
            if (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id in aliases
                and value.attr == "__call__"
            ):
                seed = True
            if not seed:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in aliases:
                    aliases.add(target.id)
                    changed = True
    return aliases


def classify_python_call(name: str, aliases: set[str]) -> str | None:
    if name in {"eval", "exec", "compile", "runpy.run_path", "runpy.run_module"}:
        return "DYNAMIC_PYTHON_EXECUTION_ENTRY"
    if name in aliases:
        return "COMPILED_CALLABLE_INVOKE"
    if any(
        name == f"{alias}.__call__" or name.startswith(f"{alias}.__call__.")
        for alias in aliases
    ):
        return "COMPILED_CALLABLE_INVOKE"
    if "_compiled_call" in name:
        return "COMPILED_CALLABLE_INVOKE"

    compact = name.replace("_", "").lower()
    if "graphlaunch" in compact or name.endswith(".replay") or name == "replay":
        return "CUDA_GRAPH_REPLAY_ENTRY"
    if (
        compact.startswith("culaunch")
        or compact.startswith("cudalaunch")
        or name.endswith(".launch")
        or name == "launch"
    ):
        return "CUDA_LAUNCH_ENTRY"
    if (
        compact.startswith("cuevent")
        or compact.startswith("cudaevent")
        or name in {"torch.cuda.Event", "cuda.Event"}
        or compact.startswith((
            "cuptiactivity", "cuptiprofiler", "cuptisubscribe",
            "cuptievent", "cuptimetric", "cuprofiler", "cudaprofiler",
        ))
    ):
        return "CUDA_EVENT_ENTRY"
    if name in {
        "time.time", "time.time_ns", "time.perf_counter",
        "time.perf_counter_ns", "time.monotonic",
        "time.monotonic_ns", "time.process_time", "time.process_time_ns",
        "torch.profiler.profile", "torch.autograd.profiler.profile",
    }:
        return "PERFORMANCE_TIMER_ENTRY"
    return None


def compiled_aliases_escaping(node: ast.AST, aliases: set[str]) -> set[str]:
    if isinstance(node, ast.Call) and call_name(node) == "artifact_value":
        if (
            len(node.args) == 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in aliases
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in {"__ptx__", "__cubin__"}
        ):
            return set()
    if isinstance(node, ast.Name) and node.id in aliases:
        return {node.id}
    result = set()
    for child in ast.iter_child_nodes(node):
        result.update(compiled_aliases_escaping(child, aliases))
    return result


def source_call_graph() -> dict:
    trees = {}
    functions = {}
    imports = {}
    source_identities = {}
    for filename in CALL_GRAPH_SOURCES:
        path = HARNESS_ROOT / filename
        module = module_name(path)
        tree = ast.parse(path.read_text(), filename=str(path))
        trees[module] = tree
        source_identities[module] = identity(path)
        functions[module] = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        mapping = {}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "common":
                for alias in node.names:
                    mapping[alias.asname or alias.name] = f"common.{alias.name}"
        imports[module] = mapping

    edges = set()
    external_calls = set()
    findings = []
    reachable = set()
    queue = deque(f"{Path(filename).stem}.main" for filename in PHASES.values())
    while queue:
        qualified = queue.popleft()
        if qualified in reachable:
            continue
        reachable.add(qualified)
        module, function_name = qualified.split(".", 1)
        fn = functions.get(module, {}).get(function_name)
        if fn is None:
            findings.append({
                "kind": "CALL_GRAPH_ROOT_OR_EDGE_UNRESOLVED",
                "function": qualified,
            })
            continue
        aliases = compiled_aliases(fn)
        for call in [node for node in ast.walk(fn) if isinstance(node, ast.Call)]:
            name = call_name(call)
            banned = classify_python_call(name, aliases)
            if banned is not None:
                findings.append({
                    "kind": banned,
                    "function": qualified,
                    "call": name,
                    "line": call.lineno,
                })
            escaped_aliases = sorted(set().union(*(
                compiled_aliases_escaping(argument, aliases)
                for argument in [
                    *call.args, *(item.value for item in call.keywords)
                ]
            ), set()))
            metadata_escape = (
                name == "artifact_value"
                and len(call.args) == 2
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id in aliases
                and isinstance(call.args[1], ast.Constant)
                and call.args[1].value in {"__ptx__", "__cubin__"}
            )
            if escaped_aliases and not metadata_escape:
                findings.append({
                    "kind": "COMPILED_CALLABLE_ESCAPE",
                    "function": qualified,
                    "call": name,
                    "aliases": escaped_aliases,
                    "line": call.lineno,
                })
            target = None
            if isinstance(call.func, ast.Name):
                if call.func.id in functions[module]:
                    target = f"{module}.{call.func.id}"
                elif call.func.id in imports[module]:
                    target = imports[module][call.func.id]
            if target is not None:
                edges.add((qualified, target))
                if target not in reachable:
                    queue.append(target)
            else:
                external_calls.add((qualified, name))
        for returned in [node for node in ast.walk(fn) if isinstance(node, ast.Return)]:
            if (
                isinstance(returned.value, ast.Name)
                and returned.value.id in aliases
            ):
                findings.append({
                    "kind": "COMPILED_CALLABLE_ESCAPE",
                    "function": qualified,
                    "call": "return",
                    "aliases": [returned.value.id],
                    "line": returned.lineno,
                })

    # Module-level code runs at import time.  Function and class bodies are not
    # executed by import, so inspect only the remaining statements.
    for module, tree in trees.items():
        top_level = ast.Module(
            body=[
                node for node in tree.body
                if not isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                )
            ],
            type_ignores=[],
        )
        aliases = compiled_aliases(top_level)
        for call in [node for node in ast.walk(top_level) if isinstance(node, ast.Call)]:
            name = call_name(call)
            banned = classify_python_call(name, aliases)
            if banned is not None:
                findings.append({
                    "kind": banned,
                    "function": f"{module}.<module>",
                    "call": name,
                    "line": call.lineno,
                })

    # Metadata accessors are the only dynamic call derived from the compiled
    # object.  Prove every artifact_value use requests PTX or cubin only.
    clean_tree = trees["clean_build"]
    metadata_calls = [
        node for node in ast.walk(clean_tree)
        if isinstance(node, ast.Call) and call_name(node) == "artifact_value"
    ]
    metadata_attributes = []
    for call in metadata_calls:
        if len(call.args) != 2 or not isinstance(call.args[1], ast.Constant):
            findings.append({
                "kind": "UNPROVEN_COMPILED_METADATA_ACCESSOR",
                "line": call.lineno,
            })
            continue
        metadata_attributes.append(call.args[1].value)
    if sorted(metadata_attributes) != ["__cubin__", "__ptx__"]:
        findings.append({
            "kind": "COMPILED_METADATA_SET_NOT_EXACT",
            "observed": metadata_attributes,
        })

    return {
        "status": "PASS" if not findings else "INVALID",
        "roots": [f"{Path(name).stem}.main" for name in PHASES.values()],
        "reachable_functions": sorted(reachable),
        "edges": [list(edge) for edge in sorted(edges)],
        "external_calls": [list(edge) for edge in sorted(external_calls)],
        "compiled_metadata_attributes": sorted(metadata_attributes),
        "findings": findings,
        "source_identities": source_identities,
    }


def sealed_identity_map(run: Path) -> tuple[dict, dict[Path, str]]:
    experiment_path = run / "experiments" / REQUEST_ID / "experiment.json"
    experiment = load(experiment_path)
    if experiment.get("status") != "MATERIALIZED":
        raise RuntimeError("INVALID_INFRA: zero-device audit requires MATERIALIZED")
    sealed = {}
    for item in experiment.get("source", {}).get("identities", []):
        path = Path(item["path"])
        if not path.is_absolute():
            path = run / path
        path = path.resolve()
        observed = sha256(path)
        if observed != item.get("sha256"):
            raise RuntimeError(
                f"INVALID_INFRA: source seal mismatch in zero-device audit: {path}"
            )
        sealed[path] = observed
    return identity(experiment_path), sealed


def verify_zero_device_source_seal(run: Path) -> dict:
    experiment_identity, sealed = sealed_identity_map(run)
    required = [HARNESS_ROOT / name for name in SEALED_HARNESS_SOURCES]
    required.extend(path.resolve() for path in AUDITOR_DEPENDENCIES)
    missing = [str(path.resolve()) for path in required if path.resolve() not in sealed]
    if missing:
        raise RuntimeError(
            "INVALID_INFRA: zero-device source/toolchain seal omits: "
            f"{missing}"
        )
    harness = [identity(HARNESS_ROOT / name) for name in SEALED_HARNESS_SOURCES]
    dependencies = [identity(path.resolve()) for path in AUDITOR_DEPENDENCIES]
    return {
        "experiment": experiment_identity,
        "harness": harness,
        "dependencies": dependencies,
    }


def sensitive_kind(symbol: str) -> str | None:
    name = symbol.split("@", 1)[0]
    if name.startswith(("cuGraphLaunch", "cudaGraphLaunch")):
        return "cuda_graph_replay"
    if name.startswith(("cuEvent", "cudaEvent")):
        return "cuda_event_or_timer"
    if name.startswith((
        "cuptiActivity", "cuptiProfiler", "cuptiSubscribe",
        "cuptiEvent", "cuptiMetric", "cuProfiler", "cudaProfiler",
    )):
        return "cuda_event_or_timer"
    if name.startswith("cuLaunch"):
        return "cuda_driver_launch"
    if name.startswith(("cudaLaunch", "__cudaLaunch")):
        return "cuda_runtime_launch"
    return None


def exported_sensitive_symbols(path: Path) -> list[dict]:
    completed = subprocess.run(
        [str(NM), "-D", "--defined-only", str(path.resolve())],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    records = []
    for line in completed.stdout.splitlines():
        fields = line.split()
        if not fields:
            continue
        symbol = fields[-1]
        kind = sensitive_kind(symbol)
        if kind is not None:
            records.append({"symbol": symbol, "kind": kind})
        elif (
            symbol.split("@", 1)[0].startswith(("cu", "cuda", "__cuda"))
            and "Launch" in symbol
        ):
            raise RuntimeError(
                f"INVALID_INFRA: unknown sensitive CUDA export: {path}:{symbol}"
            )
    return records


def build_or_verify_interposer(phase: str, sealed: dict) -> dict:
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    INTERPOSER_BINARY.parent.mkdir(parents=True, exist_ok=True)
    if phase == "clean_build":
        if INTERPOSER_BINARY.exists() or INTERPOSER_MANIFEST.exists():
            raise RuntimeError(
                "INVALID_INFRA: zero-device interposer build is not clean"
            )
        temporary = INTERPOSER_BINARY.with_suffix(".so.tmp")
        command = [
            str(CC), "-shared", "-fPIC", "-O2", "-Wall", "-Wextra",
            "-Werror", "-std=c11", "-o", str(temporary),
            str(INTERPOSER_SOURCE), "-ldl",
        ]
        subprocess.run(command, check=True)
        os.replace(temporary, INTERPOSER_BINARY)
        exported = subprocess.run(
            [str(NM), "-D", "--defined-only", str(INTERPOSER_BINARY)],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout
        for required in ("la_version", "la_objopen", "la_symbind64"):
            if required not in exported:
                raise RuntimeError(
                    f"INVALID_INFRA: interposer lacks audit export: {required}"
                )
        manifest = {
            "schema_version": "qwen35-zero-device-interposer-build-v1",
            "status": "PASS",
            "source": identity(INTERPOSER_SOURCE),
            "compiler": identity(CC),
            "loader": identity(LOADER),
            "binary": identity(INTERPOSER_BINARY),
            "command": command,
            "sensitive_exports": {
                "libcuda": exported_sensitive_symbols(LIBCUDA),
                "libcudart": exported_sensitive_symbols(LIBCUDART),
                "libcupti": exported_sensitive_symbols(LIBCUPTI),
            },
            "sealed_sources": sealed,
        }
        dump(INTERPOSER_MANIFEST, manifest)
        return manifest

    manifest = load(INTERPOSER_MANIFEST)
    if manifest.get("status") != "PASS":
        raise RuntimeError("INVALID_INFRA: interposer manifest is not PASS")
    if identity(INTERPOSER_BINARY) != manifest.get("binary"):
        raise RuntimeError("INVALID_INFRA: interposer binary identity drift")
    if identity(INTERPOSER_SOURCE) != manifest.get("source"):
        raise RuntimeError("INVALID_INFRA: interposer source identity drift")
    return manifest


def expected_phase_argv(phase: str, run: Path) -> list[str]:
    return [
        str(PYTHON.resolve()),
        str((HARNESS_ROOT / PHASES[phase]).resolve()),
        "--run",
        str(run.resolve()),
    ]


def verify_phase_order(phase: str) -> list[dict]:
    index = PHASE_ORDER.index(phase)
    prior = []
    for predecessor in PHASE_ORDER[:index]:
        path = AUDIT_ROOT / "phases" / f"{predecessor}.json"
        payload = load(path)
        if payload.get("status") != "PASS":
            raise RuntimeError(
                f"INVALID_INFRA: predecessor audit is not PASS: {predecessor}"
            )
        prior.append(identity(path))
    return prior


def parse_audit_log(path: Path) -> dict:
    if not path.is_file():
        raise RuntimeError("INVALID_INFRA: LD_AUDIT produced no log")
    records = []
    for raw in path.read_text(errors="replace").splitlines():
        kind, separator, value = raw.partition("|")
        if not separator:
            raise RuntimeError(f"INVALID_INFRA: malformed audit log line: {raw!r}")
        records.append({"kind": kind, "value": value})
    ready = sum(
        record == {"kind": "AUDITOR", "value": "READY"}
        for record in records
    )
    if ready == 0:
        raise RuntimeError("INVALID_INFRA: GNU LD_AUDIT was not active")
    failures = [record for record in records if record["kind"] == "AUDITOR_FAILURE"]
    if failures:
        raise RuntimeError(f"INVALID_INFRA: interposer failure: {failures}")

    invocation_map = {
        "cuda_driver_launch": "cuda_driver_launch_calls",
        "cuda_runtime_launch": "cuda_runtime_launch_calls",
        "cuda_graph_replay": "cuda_graph_replay_calls",
        "cuda_event_or_timer": "cuda_event_or_timer_calls",
    }
    counts = {field: 0 for field in ZERO_COUNT_FIELDS}
    for record in records:
        if record["kind"] == "INVOKE" and record["value"] in invocation_map:
            counts[invocation_map[record["value"]]] += 1

    allowed_cuda_objects = {
        LIBCUDA.resolve(),
        LIBCUDART.resolve(),
        LIBCUPTI.resolve(),
    }
    cuda_objects = []
    for record in records:
        if record["kind"] != "OBJECT":
            continue
        raw = record["value"]
        basename = Path(raw).name
        if not basename.startswith(("libcuda.so", "libcudart.so", "libcupti.so")):
            continue
        if not Path(raw).is_absolute():
            raise RuntimeError(
                f"INVALID_INFRA: CUDA object origin is not absolute: {raw}"
            )
        origin = Path(raw).resolve()
        if origin not in allowed_cuda_objects:
            raise RuntimeError(
                f"INVALID_INFRA: unsealed CUDA object loaded: {origin}"
            )
        cuda_objects.append(identity(origin))

    return {
        "ready_record_count": ready,
        "records": records,
        "bindings": [record for record in records if record["kind"] == "BIND"],
        "dynamic_rewrites": [
            record for record in records
            if record["kind"] == "DYNAMIC_REWRITE"
        ],
        "cuda_objects": cuda_objects,
        "counts": counts,
        "log_identity": identity(path),
    }


def aggregate_receipt(source_seal: dict, call_graph: dict) -> dict:
    phase_receipts = []
    totals = {field: 0 for field in ZERO_COUNT_FIELDS}
    for phase in PHASE_ORDER:
        path = AUDIT_ROOT / "phases" / f"{phase}.json"
        payload = load(path)
        if payload.get("status") != "PASS":
            raise RuntimeError(
                f"INVALID_INFRA: cannot finalize failed phase audit: {phase}"
            )
        phase_receipts.append(identity(path))
        for field in ZERO_COUNT_FIELDS:
            totals[field] += payload["five_zero_counts"][field]
    if any(totals.values()):
        raise RuntimeError(
            f"INVALID_INFRA: aggregate zero-device counts are nonzero: {totals}"
        )
    return {
        "schema_version": "qwen35-zero-device-audit-receipt-v1",
        "status": "PASS",
        "request_id": REQUEST_ID,
        "mechanism": "GNU_LD_AUDIT_SYMBOL_REBIND_AND_BLOCK",
        "auditor_identity": {
            "wrapper": identity(Path(__file__).resolve()),
            "interposer_source": identity(INTERPOSER_SOURCE),
            "interposer_binary": identity(INTERPOSER_BINARY),
            "interposer_manifest": identity(INTERPOSER_MANIFEST),
        },
        "source_and_harness_identity": source_seal,
        "python_call_graph": call_graph,
        "phase_receipts": phase_receipts,
        "five_zero_counts": totals,
        "coverage_boundary": COVERAGE_BOUNDARY,
    }


def run_phase(run: Path, phase: str, argv: list[str]) -> int:
    require_run(run)
    verify_experiment_source_seal(run)
    verify_bound_sources()
    source_seal = verify_zero_device_source_seal(run)
    call_graph = source_call_graph()
    if call_graph["status"] != "PASS":
        raise RuntimeError(
            f"INVALID_INFRA: forbidden Python call-graph entry: {call_graph['findings']}"
        )
    expected = expected_phase_argv(phase, run)
    if argv != expected:
        raise RuntimeError(
            f"INVALID_INFRA: unsealed phase argv; expected={expected}, observed={argv}"
        )
    prior = verify_phase_order(phase)

    receipt_path = AUDIT_ROOT / "phases" / f"{phase}.json"
    log_path = AUDIT_ROOT / "logs" / f"{phase}.log"
    if receipt_path.exists() or log_path.exists():
        raise RuntimeError(
            f"INVALID_INFRA: stale zero-device artifact for phase {phase}"
        )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    interposer = build_or_verify_interposer(phase, source_seal)

    forbidden_environment = [
        name for name in (
            "LD_AUDIT", "LD_PRELOAD", "CUDA_INJECTION64_PATH",
            "CUDA_PROFILE", "CUDA_PROFILE_LOG",
        )
        if os.environ.get(name)
    ]
    if forbidden_environment:
        raise RuntimeError(
            "INVALID_INFRA: conflicting injection/profiling environment: "
            f"{forbidden_environment}"
        )
    environment = os.environ.copy()
    environment.update({
        "LD_AUDIT": str(INTERPOSER_BINARY.resolve()),
        "LD_BIND_NOW": "1",
        "KERNEL_OPT_ZERO_DEVICE_LOG": str(log_path.resolve()),
    })

    completed = subprocess.run(argv, cwd=str(run), env=environment, check=False)
    parsed = parse_audit_log(log_path)
    parsed["counts"]["compiled_callable_invocations"] = len([
        finding for finding in call_graph["findings"]
        if finding["kind"] == "COMPILED_CALLABLE_INVOKE"
    ])
    zero = not any(parsed["counts"].values())
    status = "PASS" if completed.returncode == 0 and zero else "INVALID"
    receipt = {
        "schema_version": "qwen35-zero-device-phase-receipt-v1",
        "status": status,
        "phase": phase,
        "argv": argv,
        "child_returncode": completed.returncode,
        "auditor_identity": {
            "wrapper": identity(Path(__file__).resolve()),
            "interposer_source": identity(INTERPOSER_SOURCE),
            "interposer_binary": interposer["binary"],
        },
        "phase_source_identity": identity(HARNESS_ROOT / PHASES[phase]),
        "source_and_harness_identity": source_seal,
        "python_call_graph": call_graph,
        "prior_phase_receipts": prior,
        "audit_log": parsed,
        "five_zero_counts": parsed["counts"],
        "coverage_boundary": COVERAGE_BOUNDARY,
    }
    dump(receipt_path, receipt)
    if status != "PASS":
        return 193
    if phase == "analyze":
        dump(
            EXPERIMENT_ROOT / "zero_device_receipt.json",
            aggregate_receipt(source_seal, call_graph),
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run-phase")
    run_parser.add_argument("--run", type=Path, required=True)
    run_parser.add_argument("--phase", choices=PHASE_ORDER, required=True)
    run_parser.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = list(args.argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        raise RuntimeError("INVALID_INFRA: missing wrapped phase argv")
    return run_phase(args.run.resolve(), args.phase, argv)


if __name__ == "__main__":
    raise SystemExit(main())
