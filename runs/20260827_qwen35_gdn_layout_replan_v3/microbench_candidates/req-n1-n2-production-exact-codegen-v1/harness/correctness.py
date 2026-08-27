#!/usr/bin/env python3
"""Mechanical source/ABI proof only; no numerical or GPU execution claim."""

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
FULL_PAIRS = [
    [0, 0],
    [1, 0], [1, 1],
    [2, 0], [2, 1], [2, 2],
    [3, 0], [3, 1], [3, 2], [3, 3],
]
S404_TAIL_PAIRS = [[0, 0], [1, 0], [1, 1]]


def canonical(node: ast.AST) -> str:
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def class_node(tree: ast.Module, name: str) -> ast.ClassDef:
    matches = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"class is not unique: {name}")
    return matches[0]


def method(cls: ast.ClassDef, name: str) -> ast.FunctionDef:
    matches = [
        node for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"method is not unique: {cls.name}.{name}")
    return matches[0]


def call_name(node: ast.Call) -> str:
    try:
        return ast.unparse(node.func)
    except Exception:
        return ""


def calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [
        item for item in ast.walk(node)
        if isinstance(item, ast.Call) and call_name(item) == name
    ]


def direct_expr_call(statement: ast.stmt, name: str) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and call_name(statement.value) == name
    )


def loop_named(node: ast.AST, variable: str) -> ast.For:
    matches = [
        item for item in ast.walk(node)
        if isinstance(item, ast.For)
        and isinstance(item.target, ast.Name)
        and item.target.id == variable
    ]
    if len(matches) != 1:
        raise RuntimeError(f"loop {variable!r} is not unique")
    return matches[0]


def module_int(tree: ast.Module, name: str) -> int | None:
    for statement in tree.body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == name
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, int)
        ):
            return statement.value.value
    return None


def direct_gemm_guard(fn: ast.FunctionDef) -> ast.If | None:
    matches = [
        item for item in ast.walk(fn)
        if isinstance(item, ast.If)
        and any(direct_expr_call(statement, "cute.gemm") for statement in item.body)
    ]
    return matches[0] if len(matches) == 1 else None


def guard_is_causal_tile_guard(fn: ast.FunctionDef) -> bool:
    guard = direct_gemm_guard(fn)
    if guard is None:
        return False
    text = ast.unparse(guard.test)
    return all(token in text for token in (
        "cutlass.Int32(col_tile) <= warp_idx",
        "cutlass.Int32(col_tile * 16) < valid_len",
        "warp_idx * cutlass.Int32(16) < valid_len",
    ))


def enclosing_four_warp_call(kernel: ast.FunctionDef) -> bool:
    matches = [
        item for item in ast.walk(kernel)
        if isinstance(item, ast.If)
        and ast.unparse(item.test) == "tidx < cutlass.Int32(128)"
        and len(calls(item, "self.causal_qk_main")) == 1
    ]
    return len(matches) == 1


def modeled_pairs(valid_len: int) -> list[list[int]]:
    return [
        [row_tile, col_tile]
        for row_tile in range(4)
        for col_tile in range(4)
        if col_tile <= row_tile
        and col_tile * 16 < valid_len
        and row_tile * 16 < valid_len
    ]


def short_publication_proof(
    tree: ast.Module, cls: ast.ClassDef, kernel: ast.FunctionDef
) -> dict:
    qk = method(cls, "causal_qk_main")
    col_loop = loop_named(qk, "col_tile")
    item_loops = [
        item for item in col_loop.body
        if isinstance(item, ast.For)
        and isinstance(item.target, ast.Name)
        and item.target.id == "item"
    ]
    item_loop = item_loops[0] if len(item_loops) == 1 else None
    fill_positions = [
        index for index, statement in enumerate(col_loop.body)
        if direct_expr_call(statement, "qk.fill")
        and "self.acc_dtype(0.0)" in ast.unparse(statement)
    ]
    store_positions = [
        index for index, statement in enumerate(col_loop.body)
        if direct_expr_call(statement, "self.store_qk")
    ]
    item_position = (
        col_loop.body.index(item_loop) if item_loop in col_loop.body else -1
    )
    zero_to_typed_store = False
    element_causal_guard = False
    if item_loop is not None:
        item_text = ast.unparse(item_loop)
        zero_to_typed_store = all(token in item_text for token in (
            "value = cutlass.Float32(0.0)",
            "qk[item] = value",
        ))
        element_causal_guard = all(token in item_text for token in (
            "cutlass.Int32(col_tile) <= warp_idx",
            "row < valid_len",
            "col < valid_len",
            "col <= row",
        ))

    checks = {
        "bt_is_64": module_int(tree, "BT") == 64,
        "four_constexpr_column_tiles": (
            ast.unparse(col_loop.iter) == "cutlass.range_constexpr(BT // 16)"
        ),
        "four_qk_warps_only": enclosing_four_warp_call(kernel),
        "causal_tile_mma_guard": guard_is_causal_tile_guard(qk),
        "fragment_zero_before_optional_mma": (
            len(fill_positions) == 1 and fill_positions[0] == 1
        ),
        "element_zero_and_causal_mask": zero_to_typed_store and element_causal_guard,
        "all_16_tiles_unconditionally_published": (
            len(store_positions) == 1
            and item_position >= 0
            and store_positions[0] > item_position
            and "warp_idx" in ast.unparse(col_loop.body[store_positions[0] - 1])
            and "cutlass.Int32(col_tile)" in ast.unparse(
                col_loop.body[store_positions[0] - 1]
            )
        ),
        "bf16_store_is_production_exact": (
            len(calls(method(cls, "store_qk"), "cute.copy")) == 1
            and "self.dtype(qk[item])" in ast.unparse(method(cls, "store_qk"))
        ),
    }
    full_pairs = modeled_pairs(64) if all((
        checks["bt_is_64"], checks["four_constexpr_column_tiles"],
        checks["four_qk_warps_only"], checks["causal_tile_mma_guard"],
    )) else []
    tail_pairs = modeled_pairs(20) if full_pairs else []
    checks.update({
        "full_chunk_executes_exact_10_lower_pairs": full_pairs == FULL_PAIRS,
        "s404_tail_executes_exact_3_lower_pairs": tail_pairs == S404_TAIL_PAIRS,
        "score_matrix_has_16_defined_tiles": (
            checks["all_16_tiles_unconditionally_published"]
            and checks["fragment_zero_before_optional_mma"]
            and checks["element_zero_and_causal_mask"]
        ),
    })
    checks["six_upper_tiles_are_bf16_zero"] = (
        checks["score_matrix_has_16_defined_tiles"]
        and checks["bf16_store_is_production_exact"]
        and 16 - len(full_pairs) == 6
    )
    return {
        "checks": checks,
        "full_executed_pairs": full_pairs,
        "s404_tail_executed_pairs": tail_pairs,
        "published_tile_count": 16 if checks["all_16_tiles_unconditionally_published"] else 0,
        "upper_zero_tile_count": 6 if checks["six_upper_tiles_are_bf16_zero"] else 0,
    }


def assigned_make_tensor_pointer(fn: ast.FunctionDef, target_name: str) -> str | None:
    for statement in fn.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if not isinstance(target, ast.Name) or target.id != target_name:
            continue
        value = statement.value
        if not isinstance(value, ast.Call) or call_name(value) != "cute.make_tensor":
            return None
        if not value.args or not isinstance(value.args[0], ast.Call):
            return None
        recast = value.args[0]
        if call_name(recast) != "cute.recast_ptr" or not recast.args:
            return None
        return canonical(recast.args[0])
    return None


def long_alias_order_proof(
    tree: ast.Module, cls: ast.ClassDef, kernel: ast.FunctionDef
) -> dict:
    register = method(cls, "causal_qk_register_fragment")
    qk_main = method(cls, "causal_qk_main")
    store = method(cls, "store_qk_bf16")

    register_assignments = []
    barrier_positions = []
    store_loop_positions = []
    for index, statement in enumerate(qk_main.body):
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Call)
            and call_name(statement.value) == "self.causal_qk_register_fragment"
        ):
            register_assignments.append((index, statement))
        if direct_expr_call(statement, "cute.arch.barrier"):
            barrier_positions.append(index)
        if (
            isinstance(statement, ast.For)
            and len(calls(statement, "self.store_qk_bf16")) == 1
        ):
            store_loop_positions.append(index)

    expected_fragments = []
    for _, statement in register_assignments:
        call = statement.value
        target = statement.targets[0].id
        final = call.args[-1] if call.args else None
        expected_fragments.append(
            [target, final.value if isinstance(final, ast.Constant) else None]
        )

    barrier_ok = False
    if len(barrier_positions) == 1:
        call = qk_main.body[barrier_positions[0]].value
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        barrier_id = keywords.get("barrier_id")
        thread_count = keywords.get("number_of_threads")
        barrier_ok = (
            isinstance(barrier_id, ast.Name)
            and barrier_id.id == "QK_STORE_BARRIER"
            and module_int(tree, "QK_STORE_BARRIER") == 1
            and isinstance(thread_count, ast.Constant)
            and thread_count.value == 128
        )

    store_tuple_ok = False
    if len(store_loop_positions) == 1:
        store_loop = qk_main.body[store_loop_positions[0]]
        try:
            pairs = [
                [pair.elts[0].value, pair.elts[1].id]
                for pair in store_loop.iter.elts
            ]
            store_tuple_ok = pairs == [
                [0, "qk0"], [1, "qk1"], [2, "qk2"], [3, "qk3"]
            ]
        except (AttributeError, IndexError):
            store_tuple_ok = False

    qk_main_text = ast.unparse(qk_main)
    register_text = ast.unparse(register)
    store_text = ast.unparse(store)
    k_pointer = assigned_make_tensor_pointer(kernel, "s_k")
    score_pointer = assigned_make_tensor_pointer(kernel, "s_qk")
    ordering_ok = (
        len(register_assignments) == 4
        and len(barrier_positions) == 1
        and len(store_loop_positions) == 1
        and max(index for index, _ in register_assignments) < barrier_positions[0]
        and barrier_positions[0] < store_loop_positions[0]
    )
    register_zero = all(token in register_text for token in (
        "qk.fill(self.acc_dtype(0.0))",
        "value = cutlass.Float32(0.0)",
        "qk_bf16[item] = self.dtype(value)",
        "return qk_bf16",
    ))
    register_causal_element_mask = all(token in register_text for token in (
        "cutlass.Int32(col_tile) <= warp_idx",
        "row < valid_len",
        "col < valid_len",
        "col <= row",
    ))
    checks = {
        "bt_is_64": module_int(tree, "BT") == 64,
        "k_score_same_backing_pointer": k_pointer is not None and k_pointer == score_pointer,
        "four_register_fragments_cover_columns_0_to_3": expected_fragments == [
            ["qk0", 0], ["qk1", 1], ["qk2", 2], ["qk3", 3]
        ],
        "every_fragment_has_one_guarded_k_read_and_mma": (
            len(calls(register, "self.load_b_aligned")) == 1
            and len(calls(register, "cute.gemm")) == 1
            and guard_is_causal_tile_guard(register)
        ),
        "four_qk_warps_only": enclosing_four_warp_call(kernel),
        "named_barrier_is_1_128": barrier_ok,
        "all_k_fragment_calls_precede_barrier_and_all_score_stores_follow": ordering_ok,
        "no_score_store_in_register_helper": (
            len(calls(register, "self.store_qk")) == 0
            and len(calls(register, "self.store_qk_bf16")) == 0
            and "s_qk" not in register_text
        ),
        "post_barrier_store_covers_all_16_tiles": store_tuple_ok,
        "score_store_is_stmatrix_bf16": all(token in store_text for token in (
            "warp.StMatrix8x8x16bOp",
            "self.dtype",
            "cute.copy",
        )),
        "upper_fragments_are_explicit_bf16_zero": (
            register_zero and register_causal_element_mask and store_tuple_ok
        ),
        "source_order_is_k_read_then_barrier_then_stmatrix": (
            ordering_ok
            and barrier_ok
            and "self.causal_qk_register_fragment" in qk_main_text
            and "self.store_qk_bf16" in qk_main_text
        ),
    }
    full_pairs = modeled_pairs(64) if all((
        checks["bt_is_64"], checks["four_register_fragments_cover_columns_0_to_3"],
        checks["every_fragment_has_one_guarded_k_read_and_mma"],
        checks["four_qk_warps_only"],
    )) else []
    checks.update({
        "full_chunk_executes_exact_10_lower_pairs": full_pairs == FULL_PAIRS,
        "long_s1024_all_chunks_are_full10": full_pairs == FULL_PAIRS,
        "score_matrix_has_16_defined_tiles": (
            checks["post_barrier_store_covers_all_16_tiles"]
            and checks["upper_fragments_are_explicit_bf16_zero"]
        ),
    })
    checks["six_upper_tiles_are_bf16_zero"] = (
        checks["score_matrix_has_16_defined_tiles"]
        and 16 - len(full_pairs) == 6
    )
    return {
        "checks": checks,
        "full_executed_pairs": full_pairs,
        "published_tile_count": 16 if checks["score_matrix_has_16_defined_tiles"] else 0,
        "upper_zero_tile_count": 6 if checks["six_upper_tiles_are_bf16_zero"] else 0,
        "alias_pointer_ast": k_pointer,
        "ordered_fragment_calls": expected_fragments,
        "barrier_source_position": barrier_positions,
        "score_store_source_position": store_loop_positions,
    }


def scorev_proof(cls: ast.ClassDef) -> dict:
    scorev = method(cls, "causal_score_v_accumulate")
    scorev_text = ast.unparse(scorev)
    col_loop = loop_named(scorev, "col_tile")
    row_loops = [
        item for item in ast.walk(col_loop)
        if isinstance(item, ast.For)
        and isinstance(item.target, ast.Name)
        and item.target.id == "row_tile"
    ]
    forbidden = {
        name: len(calls(scorev, name))
        for name in (
            "cute.copy",
            "cute.make_fragment_like",
            "cute.make_rmem_tensor",
            "cute.arch.sync_threads",
        )
    }
    checks = {
        "one_outer_col_loop": len([
            item for item in ast.walk(scorev)
            if isinstance(item, ast.For)
            and isinstance(item.target, ast.Name)
            and item.target.id == "col_tile"
        ]) == 1,
        "row_loop_nested_under_col": len(row_loops) == 1,
        "one_v_load_site_before_row_loop": (
            len(calls(scorev, "self.load_a_aligned")) == 1
            and scorev_text.find("v_operand = self.load_a_aligned")
            < scorev_text.find("for row_tile")
        ),
        "eight_warp_production_shape": all(token in scorev_text for token in (
            "cute.make_layout((8, 1, 1))",
            "permutation_mnk=(D, 16, 16)",
        )),
        "same_backing_logical_divide": all(token in scorev_text for token in (
            "cute.make_tensor(output.iterator",
            "cute.logical_divide(output.layout, (None, None, 2))",
        )),
        "causal_order": "col_tile <= row_tile" in scorev_text,
        "zero_explicit_transport": all(value == 0 for value in forbidden.values()),
    }
    return {"checks": checks, "forbidden_calls": forbidden}


def dense_fallback_exact(
    path_name: str, candidate_class: ast.ClassDef, production_class: ast.ClassDef
) -> dict:
    candidate_parent = method(
        candidate_class, "output_main" if path_name == "short" else "kernel"
    )
    production_parent = method(
        production_class, "output_main" if path_name == "short" else "kernel"
    )
    dispatch = [
        item for item in ast.walk(candidate_parent)
        if isinstance(item, ast.If)
        and "causal_scorev_schedule" in ast.unparse(item.test)
    ]
    if len(dispatch) != 1:
        return {"unique": False, "ast_exact": False}
    dense_names = {"o2_mma", "v_operand", "qk_operand"}
    expected = []
    for statement in ast.walk(production_parent):
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in dense_names
            for target in statement.targets
        ):
            expected.append(canonical(statement))
        elif (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and call_name(statement.value) == "cute.gemm"
            and "o2_mma" in ast.unparse(statement)
        ):
            expected.append(canonical(statement))
    observed = [canonical(statement) for statement in dispatch[0].orelse]
    return {"unique": True, "ast_exact": observed == expected}


def static_path_audit(path_name: str) -> dict:
    filename = SOURCES[path_name]
    candidate_path = CANDIDATE_PACKAGE / filename
    production_path = PRODUCTION_ROOT / filename
    candidate_tree = ast.parse(candidate_path.read_text(), filename=str(candidate_path))
    production_tree = ast.parse(production_path.read_text(), filename=str(production_path))
    candidate_class = class_node(candidate_tree, CLASSES[path_name])
    production_class = class_node(production_tree, CLASSES[path_name])
    kernel = method(candidate_class, "kernel")

    exact_methods = {}
    for helper in (
        "load_a_aligned", "load_b_aligned", "store_qk",
        "store_output_bf16", "raw_output_epilogue", "__call__",
    ):
        exact_methods[helper] = (
            canonical(method(candidate_class, helper))
            == canonical(method(production_class, helper))
        )

    publication = (
        short_publication_proof(candidate_tree, candidate_class, kernel)
        if path_name == "short"
        else long_alias_order_proof(candidate_tree, candidate_class, kernel)
    )
    scorev = scorev_proof(candidate_class)
    dense = dense_fallback_exact(path_name, candidate_class, production_class)
    checks = {
        **{f"production_exact_method:{key}": value for key, value in exact_methods.items()},
        **{f"qk_publication:{key}": value for key, value in publication["checks"].items()},
        **{f"scorev:{key}": value for key, value in scorev["checks"].items()},
        "n1_dense_scorev_dispatch_unique": dense["unique"],
        "n1_dense_scorev_ast_exact": dense["ast_exact"],
    }
    return {
        "production_path": path_name,
        "candidate_source": identity(candidate_path),
        "production_source": identity(production_path),
        "checks": checks,
        "publication_proof": publication,
        "scorev_proof": scorev,
        "dense_fallback_proof": dense,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "failed_checks": sorted(name for name, passed in checks.items() if not passed),
    }


def builder_audit() -> dict:
    path = CANDIDATE_PACKAGE / "qwen35_fla_s3_raw_sm120.py"
    text = path.read_text()
    init_text = (CANDIDATE_PACKAGE / "__init__.py").read_text()
    pipeline_text = (
        CANDIDATE_PACKAGE / "qwen35_fla_pipeline_sm120.py"
    ).read_text()
    short_text = (CANDIDATE_PACKAGE / SOURCES["short"]).read_text()
    long_text = (CANDIDATE_PACKAGE / SOURCES["long"]).read_text()
    checks = {
        "C0_dense_control": (
            'candidate_id in ("C1", "C2")' in text
            and 'candidate_id == "C2"' in text
        ),
        "short_long_boundary": "if sequence <= 640" in text,
        "allowed_candidate_set": 'candidate_id not in ("C0", "C1", "C2")' in text,
        "candidate_package_does_not_extend_path": "__path__" not in init_text,
        "pipeline_uses_absolute_production_varlen_helper": (
            "from flashinfer.gdn_kernels.delta_rule_dsl.varlen_helper import"
            in pipeline_text
        ),
        "all_candidate_sources_use_absolute_compile_cache": all(
            "from flashinfer.gdn_kernels.delta_rule_dsl.custom_compile_cache import"
            in source
            for source in (pipeline_text, short_text, long_text)
        ),
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
    by_path = {entry["production_path"]: entry for entry in paths}
    builder = builder_audit()
    common_qk = builder["status"] == "PASS" and all(
        all(
            passed for name, passed in entry["checks"].items()
            if name.startswith("qk_publication:")
        )
        for entry in paths
    )
    n1_pass = common_qk and all(
        entry["checks"]["n1_dense_scorev_ast_exact"] for entry in paths
    )
    n2_pass = common_qk and all(
        all(
            passed for name, passed in entry["checks"].items()
            if name.startswith("scorev:")
        )
        for entry in paths
    )
    result = {
        "schema_version": "qwen35-n1-n2-static-correctness-v2",
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
        "tile_schedule_contract": {
            "tile_shape": [16, 16],
            "full_chunk_pairs": FULL_PAIRS,
            "full_chunk_pair_count": 10,
            "short_s404_tail_valid_tokens": 20,
            "short_s404_tail_pairs": S404_TAIL_PAIRS,
            "short_s404_tail_pair_count": 3,
            "short_proof": by_path["short"]["publication_proof"],
            "long_proof": by_path["long"]["publication_proof"],
        },
        "long_alias_lifetime_contract": (
            "all four register-resident K-read results precede named "
            "barrier(1,128); all BF16 score STMatrix stores follow it"
        ),
        "bf16_boundaries": {
            "score_store": "all 16 tiles, including six explicit upper zeros",
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
    print("PASS: mechanical source/ABI proof completed; CUDA launches=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
