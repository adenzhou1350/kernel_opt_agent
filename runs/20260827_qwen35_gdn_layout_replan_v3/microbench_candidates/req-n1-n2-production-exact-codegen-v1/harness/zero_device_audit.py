#!/usr/bin/env python3
"""Pure zero-device audit library for the trusted experiment executor.

This module has no CLI and never builds binaries or starts phase processes.
The trusted framework executor imports it, checks the sealed source/call graph,
injects the independently materialized GNU LD_AUDIT binary into each of the six
direct phase launches, parses the six logs, and emits the framework receipt.
"""

from __future__ import annotations

import ast
from collections import deque
from pathlib import Path
from typing import Mapping, Sequence

from common import PYTHON, REQUEST_ID, identity, load, sha256


HARNESS_ROOT = Path(__file__).resolve().parent
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
    "ZERO_DEVICE_EXECUTOR_INTEGRATION.md",
)

FRAMEWORK_SCHEMA_VERSION = "zero-device-execution-receipt-v1"
FRAMEWORK_RECEIPT_FIELDS = frozenset({
    "schema_version", "status", "request_id", "experiment_identity",
    "auditor_identity", "source_identities", "harness_identities",
    "offline_compile_only", "static_callgraph_audit",
    "runtime_launch_audit", "counters",
})
COUNTER_FIELDS = frozenset({
    "cuda_kernel_launches", "gpu_performance_samples",
    "compiled_callable_invocations", "cuda_events", "graph_replays",
})
INTERPOSER_BUILD_SCHEMA = "zero-device-interposer-build-receipt-v1"
REQUIRED_AUDIT_EXPORTS = frozenset({
    "la_version", "la_objopen", "la_symbind64", "la_preinit",
})
CUDA_OBJECT_PREFIXES = ("libcuda.so", "libcudart.so", "libcupti.so")

COVERAGE_BOUNDARY = {
    "covered": [
        "reachable Python calls rooted at main() in all six sealed phase files",
        "module-level calls in all six phase files and common.py",
        "normal/PLT and dynamic external CUDA binding seen by glibc la_symbind64",
        "all glibc link-map namespaces whose objects trigger la_objopen",
        "RTLD_DEEPBIND-selected external bindings that cross a DSO boundary",
        "CUDA driver/runtime lookup APIs whose returned pointers are rewritten",
        "launch, graph replay, CUDA event, and selected CUPTI/profiler entries",
        "descendants inheriting both audit environment variables unchanged",
    ],
    "not_covered": [
        "raw NVIDIA ioctls bypassing exported CUDA APIs",
        "hidden/local or -Bsymbolic intra-DSO calls bypassing the dynamic binder",
        "secure-execution children for which glibc removes LD_AUDIT",
        "children deliberately replacing or removing the audit environment",
        "foreign processes or persistent daemons outside the phase process tree",
        "undocumented paths bypassing exports and audited function-pointer APIs",
    ],
    "fail_closed": (
        "Missing READY/PREINIT, malformed records, auditor failure, unsealed "
        "CUDA objects, nonzero counters, identity drift, or a non-PASS static "
        "call graph makes execution INVALID. Listed uncovered paths are forbidden."
    ),
}


def _call_name(node: ast.Call) -> str:
    try:
        return ast.unparse(node.func)
    except Exception:
        return ""


def _is_cute_compile_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and ast.unparse(node.func).startswith("cute.compile[")


def _compiled_aliases(
    node: ast.AST, initial: Sequence[str] = (),
) -> set[str]:
    aliases: set[str] = set(initial)
    assignments = [
        item for item in ast.walk(node)
        if isinstance(item, (ast.Assign, ast.AnnAssign))
    ]
    changed = True
    while changed:
        changed = False
        for statement in assignments:
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            value = statement.value
            seeded = _is_cute_compile_call(value)
            if isinstance(value, ast.Name) and value.id in aliases:
                seeded = True
            if (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id in aliases
                and value.attr == "__call__"
            ):
                seeded = True
            if seeded:
                for target in targets:
                    if isinstance(target, ast.Name) and target.id not in aliases:
                        aliases.add(target.id)
                        changed = True
    return aliases


def _classify_call(name: str, aliases: set[str]) -> str | None:
    if name in {"eval", "exec", "compile", "runpy.run_path", "runpy.run_module"}:
        return "DYNAMIC_PYTHON_EXECUTION_ENTRY"
    if (
        name in aliases
        or any(name == f"{alias}.__call__" or name.startswith(f"{alias}.__call__.") for alias in aliases)
        or "_compiled_call" in name
    ):
        return "COMPILED_CALLABLE_INVOKE"
    compact = name.replace("_", "").lower()
    if "graphlaunch" in compact or name.endswith(".replay") or name == "replay":
        return "CUDA_GRAPH_REPLAY_ENTRY"
    if compact.startswith(("culaunch", "cudalaunch")) or name.endswith(".launch") or name == "launch":
        return "CUDA_LAUNCH_ENTRY"
    if (
        compact.startswith(("cuevent", "cudaevent"))
        or name in {"torch.cuda.Event", "cuda.Event"}
        or compact.startswith((
            "cuptiactivity", "cuptiprofiler", "cuptisubscribe",
            "cuptievent", "cuptimetric", "cuprofiler", "cudaprofiler",
        ))
    ):
        return "CUDA_EVENT_ENTRY"
    if name in {
        "time.time", "time.time_ns", "time.perf_counter", "time.perf_counter_ns",
        "time.monotonic", "time.monotonic_ns", "time.process_time",
        "time.process_time_ns", "torch.profiler.profile",
        "torch.autograd.profiler.profile",
    }:
        return "PERFORMANCE_TIMER_ENTRY"
    return None


def _compiled_escape(node: ast.AST, aliases: set[str]) -> set[str]:
    if isinstance(node, ast.Call) and _call_name(node) == "artifact_value":
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
    result: set[str] = set()
    for child in ast.iter_child_nodes(node):
        result.update(_compiled_escape(child, aliases))
    return result


def source_call_graph(harness_root: Path = HARNESS_ROOT) -> dict:
    """Return deterministic no-execution admission rooted at six phase mains."""
    trees: dict[str, ast.Module] = {}
    functions: dict[str, dict[str, ast.AST]] = {}
    imports: dict[str, dict[str, str]] = {}
    source_identities: dict[str, dict] = {}
    for filename in CALL_GRAPH_SOURCES:
        path = harness_root / filename
        module = path.stem
        tree = ast.parse(path.read_text(), filename=str(path))
        trees[module] = tree
        source_identities[module] = identity(path)
        functions[module] = {
            item.name: item for item in tree.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        mapping: dict[str, str] = {}
        for item in tree.body:
            if isinstance(item, ast.ImportFrom) and item.module == "common":
                for alias in item.names:
                    mapping[alias.asname or alias.name] = f"common.{alias.name}"
        imports[module] = mapping

    edges: set[tuple[str, str]] = set()
    external_calls: set[tuple[str, str]] = set()
    findings: list[dict] = []
    reachable: set[str] = set()
    queue = deque(f"{Path(name).stem}.main" for name in PHASES.values())
    while queue:
        qualified = queue.popleft()
        if qualified in reachable:
            continue
        reachable.add(qualified)
        module, function_name = qualified.split(".", 1)
        function = functions.get(module, {}).get(function_name)
        if function is None:
            findings.append({"kind": "UNRESOLVED_CALL_GRAPH_EDGE", "function": qualified})
            continue
        aliases = _compiled_aliases(
            function,
            ("compiled",) if qualified == "clean_build.artifact_value" else (),
        )
        for call in [item for item in ast.walk(function) if isinstance(item, ast.Call)]:
            name = _call_name(call)
            banned = (
                "COMPILED_CALLABLE_INVOKE"
                if _is_cute_compile_call(call.func)
                else _classify_call(name, aliases)
            )
            if banned:
                findings.append({"kind": banned, "function": qualified, "call": name, "line": call.lineno})
            escaped = sorted(set().union(*(
                _compiled_escape(argument, aliases)
                for argument in [*call.args, *(item.value for item in call.keywords)]
            ), set()))
            metadata_escape = (
                name == "artifact_value"
                and len(call.args) == 2
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id in aliases
                and isinstance(call.args[1], ast.Constant)
                and call.args[1].value in {"__ptx__", "__cubin__"}
            )
            metadata_getattr = (
                qualified == "clean_build.artifact_value"
                and name == "getattr"
                and len(call.args) == 3
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id == "compiled"
                and isinstance(call.args[1], ast.Name)
                and call.args[1].id == "attribute"
                and isinstance(call.args[2], ast.Constant)
                and call.args[2].value is None
            )
            if escaped and not metadata_escape and not metadata_getattr:
                findings.append({
                    "kind": "COMPILED_CALLABLE_ESCAPE", "function": qualified,
                    "call": name, "aliases": escaped, "line": call.lineno,
                })
            target = None
            if isinstance(call.func, ast.Name):
                if call.func.id in functions[module]:
                    target = f"{module}.{call.func.id}"
                elif call.func.id in imports[module]:
                    target = imports[module][call.func.id]
            if target is None:
                external_calls.add((qualified, name))
            else:
                edges.add((qualified, target))
                if target not in reachable:
                    queue.append(target)
        for returned in [item for item in ast.walk(function) if isinstance(item, ast.Return)]:
            if isinstance(returned.value, ast.Name) and returned.value.id in aliases:
                findings.append({
                    "kind": "COMPILED_CALLABLE_ESCAPE", "function": qualified,
                    "call": "return", "aliases": [returned.value.id], "line": returned.lineno,
                })

    for module, tree in trees.items():
        top_level = ast.Module(
            body=[item for item in tree.body if not isinstance(
                item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            )],
            type_ignores=[],
        )
        aliases = _compiled_aliases(top_level)
        for call in [item for item in ast.walk(top_level) if isinstance(item, ast.Call)]:
            banned = _classify_call(_call_name(call), aliases)
            if banned:
                findings.append({
                    "kind": banned, "function": f"{module}.<module>",
                    "call": _call_name(call), "line": call.lineno,
                })

    metadata_calls = [
        item for item in ast.walk(trees["clean_build"])
        if isinstance(item, ast.Call) and _call_name(item) == "artifact_value"
    ]
    metadata_attributes: list[str] = []
    for call in metadata_calls:
        if len(call.args) != 2 or not isinstance(call.args[1], ast.Constant):
            findings.append({"kind": "UNPROVEN_COMPILED_METADATA_ACCESSOR", "line": call.lineno})
        else:
            metadata_attributes.append(str(call.args[1].value))
    if sorted(metadata_attributes) != ["__cubin__", "__ptx__"]:
        findings.append({"kind": "COMPILED_METADATA_SET_NOT_EXACT", "observed": metadata_attributes})

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


def expected_phase_commands(run: Path) -> dict[str, list[str]]:
    python = str(PYTHON.resolve())
    return {
        phase: [python, str((HARNESS_ROOT / filename).resolve()), "--run", str(run.resolve())]
        for phase, filename in PHASES.items()
    }


def _sealed_identity_map(run: Path, experiment_path: Path) -> dict[Path, dict]:
    experiment = load(experiment_path)
    if experiment.get("status") != "MATERIALIZED":
        raise RuntimeError("INVALID_INFRA: experiment is not MATERIALIZED")
    sealed: dict[Path, dict] = {}
    for item in experiment.get("source", {}).get("identities", []):
        path = Path(item["path"])
        path = path.resolve() if path.is_absolute() else (run / path).resolve()
        if not path.is_file() or sha256(path) != item.get("sha256"):
            raise RuntimeError(f"INVALID_INFRA: sealed identity drift: {path}")
        sealed[path] = item
    return sealed


def verify_executor_admission(
    run: Path,
    experiment_path: Path,
    interposer_build_receipt_path: Path,
) -> dict:
    """Verify immutable prerequisites without building or starting anything."""
    run, experiment_path = run.resolve(), experiment_path.resolve()
    sealed = _sealed_identity_map(run, experiment_path)
    experiment = load(experiment_path)
    required_harness = [(HARNESS_ROOT / name).resolve() for name in SEALED_HARNESS_SOURCES]
    missing = [str(path) for path in required_harness if path not in sealed]
    if missing:
        raise RuntimeError(f"INVALID_INFRA: experiment omits harness identities: {missing}")

    commands = experiment.get("commands", {})
    if sum(len(commands.get(phase, [])) for phase in PHASE_ORDER) != 6:
        raise RuntimeError("INVALID_INFRA: experiment must contain exactly six phase argv")
    expected = expected_phase_commands(run)
    for phase in PHASE_ORDER:
        if commands.get(phase) != [expected[phase]]:
            raise RuntimeError(f"INVALID_INFRA: direct argv mismatch for {phase}")

    measurement = experiment.get("measurement_contract", {})
    if (
        measurement.get("gpu_launches") != 0
        or measurement.get("performance_samples") != 0
        or measurement.get("timer") not in {"none", "none_compiler_typecheck"}
    ):
        raise RuntimeError("INVALID_INFRA: experiment is not offline compile-only")

    interposer_build_receipt_path = interposer_build_receipt_path.resolve()
    if interposer_build_receipt_path not in sealed:
        raise RuntimeError("INVALID_INFRA: interposer build receipt is not sealed")
    build = load(interposer_build_receipt_path)
    if build.get("schema_version") != INTERPOSER_BUILD_SCHEMA or build.get("status") != "PASS":
        raise RuntimeError("INVALID_INFRA: interposer build receipt is not PASS")
    binary = build.get("binary_identity", {})
    binary_path = Path(binary.get("path", "")).resolve()
    if binary_path not in sealed or identity(binary_path) != binary:
        raise RuntimeError("INVALID_INFRA: interposer binary is not sealed")
    if build.get("source_identity") != identity(HARNESS_ROOT / "zero_device_interposer.c"):
        raise RuntimeError("INVALID_INFRA: interposer source/build mismatch")
    if not REQUIRED_AUDIT_EXPORTS <= set(build.get("exported_symbols", [])):
        raise RuntimeError("INVALID_INFRA: required interposer exports missing")
    for field in (
        "compiler_identity", "linker_identity", "symbol_inspector_identity",
        "loader_identity",
    ):
        item = build.get(field, {})
        path = Path(item.get("path", "")).resolve()
        if path not in sealed or identity(path) != item:
            raise RuntimeError(f"INVALID_INFRA: unsealed build tool: {field}")
    if int(build.get("materialization_process_launches", -1)) < 1:
        raise RuntimeError("INVALID_INFRA: interposer build cost is undeclared")
    cuda_object_identities = build.get("cuda_object_identities", [])
    if not isinstance(cuda_object_identities, list) or not cuda_object_identities:
        raise RuntimeError("INVALID_INFRA: CUDA object allowlist is empty")
    allowed_cuda_objects = []
    for item in cuda_object_identities:
        path = Path(item.get("path", "")).resolve()
        if path not in sealed or identity(path) != item:
            raise RuntimeError(f"INVALID_INFRA: unsealed CUDA object allowlist item: {path}")
        allowed_cuda_objects.append(path)
    allowed_basenames = {path.name.split(".so", 1)[0] for path in allowed_cuda_objects}
    if not {"libcuda", "libcudart", "libcupti"} <= allowed_basenames:
        raise RuntimeError("INVALID_INFRA: CUDA object allowlist is incomplete")

    graph = source_call_graph()
    if graph["status"] != "PASS":
        raise RuntimeError(f"INVALID_INFRA: forbidden static path: {graph['findings']}")
    return {
        "experiment_identity": identity(experiment_path),
        "source_identities": [identity(path) for path in sorted(sealed) if path not in required_harness],
        "harness_identities": [identity(path) for path in required_harness],
        "auditor_identity": identity(interposer_build_receipt_path),
        "interposer_binary_identity": binary,
        "allowed_cuda_objects": allowed_cuda_objects,
        "static_call_graph": graph,
        "coverage_boundary": COVERAGE_BOUNDARY,
    }


def executor_phase_environment(
    base_environment: Mapping[str, str], *, interposer_binary: Path, phase_log: Path,
) -> dict[str, str]:
    """Return env for one direct phase launch; never starts a process."""
    forbidden = [name for name in (
        "LD_AUDIT", "LD_PRELOAD", "CUDA_INJECTION64_PATH", "CUDA_PROFILE", "CUDA_PROFILE_LOG",
    ) if base_environment.get(name)]
    if forbidden:
        raise RuntimeError(f"INVALID_INFRA: conflicting injection environment: {forbidden}")
    if phase_log.exists():
        raise RuntimeError(f"INVALID_INFRA: stale phase audit log: {phase_log}")
    result = dict(base_environment)
    result.update({
        "LD_AUDIT": str(interposer_binary.resolve()),
        "LD_BIND_NOW": "1",
        "KERNEL_OPT_ZERO_DEVICE_LOG": str(phase_log.resolve()),
    })
    return result


def parse_phase_log(path: Path, *, allowed_cuda_objects: Sequence[Path]) -> dict:
    """Parse one phase log and fail closed on ambiguity or sensitive activity."""
    if not path.is_file():
        raise RuntimeError(f"INVALID_INFRA: missing LD_AUDIT log: {path}")
    records: list[dict[str, str]] = []
    for raw in path.read_text(errors="replace").splitlines():
        kind, separator, value = raw.partition("|")
        if not separator or not kind:
            raise RuntimeError(f"INVALID_INFRA: malformed audit record: {raw!r}")
        records.append({"kind": kind, "value": value})
    if not any(item == {"kind": "AUDITOR", "value": "READY"} for item in records):
        raise RuntimeError("INVALID_INFRA: LD_AUDIT did not emit READY")
    if not any(item == {"kind": "AUDITOR", "value": "PREINIT"} for item in records):
        raise RuntimeError("INVALID_INFRA: LD_AUDIT did not emit PREINIT")
    failures = [item for item in records if item["kind"] == "AUDITOR_FAILURE"]
    if failures:
        raise RuntimeError(f"INVALID_INFRA: interposer failure: {failures}")

    counters = {name: 0 for name in COUNTER_FIELDS}
    invoke_map = {
        "cuda_driver_launch": "cuda_kernel_launches",
        "cuda_runtime_launch": "cuda_kernel_launches",
        "cuda_graph_replay": "graph_replays",
        "cuda_event_or_timer": "cuda_events",
    }
    for item in records:
        if item["kind"] == "INVOKE" and item["value"] in invoke_map:
            counters[invoke_map[item["value"]]] += 1

    allowed = {item.resolve() for item in allowed_cuda_objects}
    loaded_cuda: list[dict] = []
    for item in records:
        if item["kind"] != "OBJECT" or not Path(item["value"]).name.startswith(CUDA_OBJECT_PREFIXES):
            continue
        origin = Path(item["value"])
        if not origin.is_absolute() or origin.resolve() not in allowed:
            raise RuntimeError(f"INVALID_INFRA: unsealed CUDA object: {origin}")
        loaded_cuda.append(identity(origin.resolve()))
    if any(counters.values()):
        raise RuntimeError(f"INVALID_EXPERIMENT: sensitive CUDA activity: {counters}")
    return {
        "status": "PASS", "log_identity": identity(path), "counters": counters,
        "loaded_cuda_objects": loaded_cuda,
        "namespace_records": [item for item in records if item["kind"] == "NAMESPACE"],
    }


def build_framework_zero_device_receipt(
    *, admission: dict, phase_logs: Mapping[str, Path],
) -> dict:
    """Build exact framework-schema payload; the executor owns validation/write."""
    if set(phase_logs) != set(PHASE_ORDER):
        raise RuntimeError("INVALID_INFRA: exactly six named phase logs are required")
    totals = {name: 0 for name in COUNTER_FIELDS}
    for phase in PHASE_ORDER:
        parsed = parse_phase_log(
            phase_logs[phase],
            allowed_cuda_objects=admission["allowed_cuda_objects"],
        )
        for name in COUNTER_FIELDS:
            totals[name] += parsed["counters"][name]
    if any(totals.values()):
        raise RuntimeError(f"INVALID_EXPERIMENT: aggregate counters nonzero: {totals}")
    receipt = {
        "schema_version": FRAMEWORK_SCHEMA_VERSION,
        "status": "PASS",
        "request_id": REQUEST_ID,
        "experiment_identity": admission["experiment_identity"],
        "auditor_identity": admission["auditor_identity"],
        "source_identities": admission["source_identities"],
        "harness_identities": admission["harness_identities"],
        "offline_compile_only": True,
        "static_callgraph_audit": "PASS_NO_COMPILED_CALLABLE_EVENT_OR_GRAPH_PATH",
        "runtime_launch_audit": "PASS_DRIVER_INTERPOSER",
        "counters": totals,
    }
    if set(receipt) != FRAMEWORK_RECEIPT_FIELDS or set(totals) != COUNTER_FIELDS:
        raise AssertionError("framework zero-device schema field drift")
    if not receipt["source_identities"] or not receipt["harness_identities"]:
        raise RuntimeError("INVALID_INFRA: receipt identity arrays must be non-empty")
    return receipt


def assert_post_phase_toctou(
    admission: dict, *, experiment_path: Path, interposer_build_receipt_path: Path,
) -> None:
    """Recheck immutable executor inputs after each direct phase returns."""
    if identity(experiment_path.resolve()) != admission["experiment_identity"]:
        raise RuntimeError("INVALID_INFRA: experiment changed during phase")
    if identity(interposer_build_receipt_path.resolve()) != admission["auditor_identity"]:
        raise RuntimeError("INVALID_INFRA: auditor receipt changed during phase")
    for item in [*admission["source_identities"], *admission["harness_identities"]]:
        path = Path(item["path"]).resolve()
        if identity(path) != item:
            raise RuntimeError(f"INVALID_INFRA: input changed during phase: {path}")


__all__ = [
    "COVERAGE_BOUNDARY", "PHASE_ORDER", "assert_post_phase_toctou",
    "build_framework_zero_device_receipt", "executor_phase_environment",
    "expected_phase_commands", "parse_phase_log", "source_call_graph",
    "verify_executor_admission",
]
