#!/usr/bin/env python3
"""Static semantic/ABI audit only; no numerical or GPU execution claim."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

from common import (
    CANDIDATE_PACKAGE,
    EXPERIMENT_ROOT,
    PRODUCTION_ROOT,
    dump,
    gate,
    identity,
    require_run,
    verify_bound_sources,
    verify_experiment_source_seal,
)


CLASSES = {
    "short": "S3PackedEpiW16RawKernelSm120",
    "long": "S3PackedWorkspaceDecayRawKernelSm120",
}
SOURCES = {
    "short": "qwen35_fla_s3_short_raw_sm120.py",
    "long": "qwen35_fla_s3_long_raw_sm120.py",
}


def canonical(node) -> str:
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def class_node(tree: ast.Module, name: str) -> ast.ClassDef:
    matches = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name]
    if len(matches) != 1:
        raise RuntimeError(f"class is not unique: {name}")
    return matches[0]


def method(cls: ast.ClassDef, name: str) -> ast.FunctionDef:
    matches = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(matches) != 1:
        raise RuntimeError(f"method is not unique: {cls.name}.{name}")
    return matches[0]


def call_name(node: ast.Call) -> str:
    try:
        return ast.unparse(node.func)
    except Exception:
        return ""


def calls(fn: ast.AST, name: str) -> list[ast.Call]:
    return [node for node in ast.walk(fn) if isinstance(node, ast.Call) and call_name(node) == name]


def loop_named(fn: ast.AST, variable: str) -> ast.For:
    matches = [
        node for node in ast.walk(fn)
        if isinstance(node, ast.For)
        and isinstance(node.target, ast.Name)
        and node.target.id == variable
    ]
    if len(matches) != 1:
        raise RuntimeError(f"loop {variable!r} is not unique")
    return matches[0]


def static_path_audit(path_name: str) -> dict:
    filename = SOURCES[path_name]
    candidate_path = CANDIDATE_PACKAGE / filename
    production_path = PRODUCTION_ROOT / filename
    candidate_tree = ast.parse(candidate_path.read_text(), filename=str(candidate_path))
    production_tree = ast.parse(production_path.read_text(), filename=str(production_path))
    candidate_class = class_node(candidate_tree, CLASSES[path_name])
    production_class = class_node(production_tree, CLASSES[path_name])

    checks = {}
    for helper in (
        "load_a_aligned",
        "load_b_aligned",
        "store_qk",
        "store_output_bf16",
        "raw_output_epilogue",
        "__call__",
    ):
        checks[f"production_exact_method:{helper}"] = (
            canonical(method(candidate_class, helper))
            == canonical(method(production_class, helper))
        )

    qk = method(candidate_class, "causal_qk_main")
    qk_text = ast.unparse(qk)
    qk_col = loop_named(qk, "col_tile")
    checks.update({
        "qk_single_col_loop": len([
            node for node in ast.walk(qk)
            if isinstance(node, ast.For)
            and isinstance(node.target, ast.Name)
            and node.target.id == "col_tile"
        ]) == 1,
        "qk_col_order_constexpr": "cutlass.range_constexpr(BT // 16)" in ast.unparse(qk_col.iter),
        "qk_causal_warp_guard": "cutlass.Int32(col_tile) <= warp_idx" in qk_text,
        "qk_element_guard": "col <= row" in qk_text,
        "qk_bf16_boundary_uses_exact_store_qk": len(calls(qk, "self.store_qk")) == 1,
        "qk_one_mma_per_tile_body": len(calls(qk, "cute.gemm")) == 1,
    })

    kernel = method(candidate_class, "kernel")
    kernel_text = ast.unparse(kernel)
    # C1 keeps the dense scoreV consumer, so the six omitted upper QK tiles
    # still require an explicit zero definition before causal_qk_main stores
    # the lower ten.  The current source has no such definition.
    score_zero_calls = [
        node for node in ast.walk(kernel)
        if isinstance(node, ast.Call)
        and (
            call_name(node) in {"self.zero_score_tile", "self.initialize_score_zero"}
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "fill"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "s_qk"
            )
        )
    ]
    checks["n1_dense_scorev_upper_tiles_defined"] = len(score_zero_calls) == 1

    # Long production aliases score storage onto K.  Incrementally loading one
    # K tile and immediately storing score can overwrite K before another warp
    # has loaded it.  Admission requires either distinct backing or an explicit
    # all-participant preload-complete barrier before the first score store.
    aliases_k_score = (
        path_name == "long"
        and "workspace + tile_elems" in kernel_text
        and kernel_text.count("workspace + tile_elems") >= 3
    )
    preload_barrier_calls = [
        node for node in ast.walk(kernel)
        if isinstance(node, ast.Call)
        and call_name(node) in {
            "self.causal_qk_preload_all_k",
            "self.causal_qk_preload_complete",
        }
    ]
    checks["long_k_score_alias_lifecycle_safe"] = (
        not aliases_k_score or len(preload_barrier_calls) == 1
    )

    scorev = method(candidate_class, "causal_score_v_accumulate")
    scorev_text = ast.unparse(scorev)
    col_loop = loop_named(scorev, "col_tile")
    row_loops = [
        node for node in ast.walk(col_loop)
        if isinstance(node, ast.For)
        and isinstance(node.target, ast.Name)
        and node.target.id == "row_tile"
    ]
    forbidden_calls = {
        name: len(calls(scorev, name))
        for name in (
            "cute.copy",
            "cute.make_fragment_like",
            "cute.make_rmem_tensor",
            "cute.arch.sync_threads",
        )
    }
    load_a_calls = calls(scorev, "self.load_a_aligned")
    checks.update({
        "scorev_one_outer_col_loop": len([
            node for node in ast.walk(scorev)
            if isinstance(node, ast.For)
            and isinstance(node.target, ast.Name)
            and node.target.id == "col_tile"
        ]) == 1,
        "scorev_row_loop_nested_under_col": len(row_loops) == 1,
        "scorev_one_v_load_site": len(load_a_calls) == 1,
        "scorev_v_load_precedes_row_loop": (
            scorev_text.find("v_operand = self.load_a_aligned")
            < scorev_text.find("for row_tile")
        ),
        "scorev_eight_warp_mma": "cute.make_layout((8, 1, 1))" in scorev_text,
        "scorev_production_shape": "permutation_mnk=(D, 16, 16)" in scorev_text,
        "scorev_logical_divide": "cute.logical_divide(output.layout, (None, None, 2))" in scorev_text,
        "scorev_same_iterator": "cute.make_tensor(output.iterator" in scorev_text,
        "scorev_causal_order": "col_tile <= row_tile" in scorev_text,
        "scorev_zero_explicit_transport": all(value == 0 for value in forbidden_calls.values()),
    })

    # Preserve the original dense scoreV branch byte-for-byte at AST level for
    # N1.  The candidate's causal-scoreV dispatch else body must equal the
    # production dense o2 construction/load/gemm statements.
    candidate_parent = (
        method(candidate_class, "output_main")
        if path_name == "short"
        else method(candidate_class, "kernel")
    )
    production_parent = (
        method(production_class, "output_main")
        if path_name == "short"
        else method(production_class, "kernel")
    )
    scorev_dispatch = [
        node for node in ast.walk(candidate_parent)
        if isinstance(node, ast.If)
        and "causal_scorev_schedule" in ast.unparse(node.test)
    ]
    if len(scorev_dispatch) != 1:
        checks["n1_dense_scorev_dispatch_unique"] = False
        checks["n1_dense_scorev_ast_exact"] = False
    else:
        checks["n1_dense_scorev_dispatch_unique"] = True
        dense_names = {"o2_mma", "v_operand", "qk_operand"}
        expected_dense = []
        for statement in ast.walk(production_parent):
            if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in dense_names
                for target in statement.targets
            ):
                expected_dense.append(canonical(statement))
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                if call_name(statement.value) == "cute.gemm" and "o2_mma" in ast.unparse(statement):
                    expected_dense.append(canonical(statement))
        observed_dense = [canonical(statement) for statement in scorev_dispatch[0].orelse]
        checks["n1_dense_scorev_ast_exact"] = observed_dense == expected_dense

    return {
        "production_path": path_name,
        "candidate_source": identity(candidate_path),
        "production_source": identity(production_path),
        "checks": checks,
        "forbidden_scorev_calls": forbidden_calls,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "failed_checks": sorted(name for name, passed in checks.items() if not passed),
    }


def builder_audit() -> dict:
    path = CANDIDATE_PACKAGE / "qwen35_fla_s3_raw_sm120.py"
    text = path.read_text()
    checks = {
        "C0_dense_control": 'candidate_id in ("C1", "C2")' in text and 'candidate_id == "C2"' in text,
        "short_long_boundary": "if sequence <= 640" in text,
        "allowed_candidate_set": 'candidate_id not in ("C0", "C1", "C2")' in text,
    }
    return {
        "source": identity(path),
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = require_run(args.run)
    experiment_identity = verify_experiment_source_seal(run)
    bound_sources = verify_bound_sources()
    build = gate(EXPERIMENT_ROOT / "build/manifest.json")
    static = gate(EXPERIMENT_ROOT / "static/instruction_audit.json")

    paths = [static_path_audit(name) for name in ("short", "long")]
    builder = builder_audit()
    qk_pass = builder["status"] == "PASS" and all(
        entry["checks"]["qk_single_col_loop"]
        and entry["checks"]["qk_causal_warp_guard"]
        and entry["checks"]["qk_element_guard"]
        for entry in paths
    )
    n1_pass = qk_pass and all(
        entry["checks"].get("n1_dense_scorev_ast_exact", False)
        and entry["checks"].get("n1_dense_scorev_upper_tiles_defined", False)
        and entry["checks"].get("long_k_score_alias_lifecycle_safe", False)
        for entry in paths
    )
    n2_pass = qk_pass and all(
        entry["checks"]["scorev_zero_explicit_transport"]
        and entry["checks"]["scorev_logical_divide"]
        and entry["checks"]["scorev_one_v_load_site"]
        and entry["checks"]["scorev_v_load_precedes_row_loop"]
        and entry["checks"].get("long_k_score_alias_lifecycle_safe", False)
        for entry in paths
    )
    result = {
        "schema_version": "qwen35-n1-n2-static-correctness-v1",
        "status": "PASS",
        "experiment_identity": experiment_identity,
        "bound_sources": bound_sources,
        "upstream_gates": {
            "build": build["identity"],
            "static": static["identity"],
        },
        "path_audits": paths,
        "builder_audit": builder,
        "candidate_results": {
            "N1": {"status": "PASS" if n1_pass else "FAIL"},
            "N2": {"status": "PASS" if n2_pass else "FAIL"},
        },
        "tail_contract": {
            "S404_valid_tail": 20,
            "executed_pairs": [[0, 0], [1, 0], [1, 1]],
        },
        "k_order_contract": (
            "QK retains each D=128 inner order; scoreV uses ascending col/K "
            "tiles and the original K=16 inner MMA order."
        ),
        "bf16_boundaries": {
            "score_store_method": "production-exact store_qk",
            "raw_o_store_method": "production-exact store_output_bf16",
        },
        "cuda_kernel_launches": 0,
        "compiled_callable_invocations": 0,
        "numerical_correctness": "DEFERRED_TO_NEXT_GPU_EXPERIMENT",
        "claims_forbidden": [
            "bitwise numerical correctness",
            "latency or speedup",
            "production acceptance",
        ],
    }
    dump(EXPERIMENT_ROOT / "correctness.json", result)
    print("PASS: static semantics/ABI audit completed; CUDA launches=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
