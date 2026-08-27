"""AST binding, exhaustive mapping witness, and no-launch CuTe codegen proof."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import cutlass
import cutlass.cute as cute
from cutlass.cute.nvgpu import warp


D = 128
BT = 64
N_TILE = 16
ACTIVE_THREADS = 256


def canonical(node: ast.AST) -> str:
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def canonical_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def exact_constant(tree: ast.Module, name: str) -> int:
    matches = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == name
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, int)
    ]
    if len(matches) != 1:
        raise RuntimeError(f"INFRA_FAILURE: expected one integer assignment for {name}, observed={matches}")
    return int(matches[0])


def class_method(tree: ast.Module, class_name: str, method_name: str) -> ast.FunctionDef:
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name]
    if len(classes) != 1:
        raise RuntimeError(f"INFRA_FAILURE: class binding is not unique: {class_name}")
    methods = [node for node in classes[0].body if isinstance(node, ast.FunctionDef) and node.name == method_name]
    if len(methods) != 1:
        raise RuntimeError(f"INFRA_FAILURE: method binding is not unique: {class_name}.{method_name}")
    return methods[0]


def calls_named(node: ast.AST, suffix: str) -> list[ast.Call]:
    matches = []
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        function = item.func
        parts = []
        while isinstance(function, ast.Attribute):
            parts.append(function.attr)
            function = function.value
        if isinstance(function, ast.Name):
            parts.append(function.id)
        if ".".join(reversed(parts)).endswith(suffix):
            matches.append(item)
    return matches


def o1_mma_call(method: ast.FunctionDef) -> ast.Call:
    matches = []
    for node in ast.walk(method):
        if not isinstance(node, ast.Assign) or not any(isinstance(target, ast.Name) and target.id == "o1_mma" for target in node.targets):
            continue
        if isinstance(node.value, ast.Call):
            matches.append(node.value)
    if len(matches) != 1:
        raise RuntimeError(f"INFRA_FAILURE: expected one o1_mma constructor, observed={len(matches)}")
    return matches[0]


def ast_binding(name: str, path: Path) -> dict:
    tree = ast.parse(path.read_text(), filename=str(path))
    if name == "short":
        class_name, method_name = "S3PackedEpiW16RawKernelSm120", "output_main"
        threads = exact_constant(tree, "THREADS")
        active = exact_constant(tree, "MAIN_THREADS")
        call_method = class_method(tree, class_name, "__call__")
        guards = [
            node for node in ast.walk(call_method)
            if isinstance(node, ast.If) and "MAIN_THREADS" in canonical(node.test) and "tidx" in canonical(node.test)
        ]
        if len(guards) != 1:
            raise RuntimeError("INFRA_FAILURE: short active-thread guard is not uniquely bound")
        guard_ast = canonical(guards[0].test)
    else:
        class_name, method_name = "S3PackedWorkspaceDecayRawKernelSm120", "__call__"
        threads = exact_constant(tree, "THREADS")
        active = threads
        guard_ast = "ALL_BLOCK_THREADS_ACTIVE"
    method = class_method(tree, class_name, method_name)
    init = class_method(tree, class_name, "__init__")
    acc_assignments = [
        node for node in ast.walk(init)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Attribute) and target.attr == "acc_dtype" for target in node.targets)
    ]
    if len(acc_assignments) != 1 or "cutlass.Float32" not in ast.unparse(acc_assignments[0].value):
        raise RuntimeError(f"INFRA_FAILURE: {name} FP32 accumulator binding failed")
    mma = o1_mma_call(method)
    mma_text = ast.unparse(mma)
    required_mma_tokens = (
        "warp.MmaF16BF16Op", "self.dtype", "self.acc_dtype", "(16, 8, 16)",
        "cute.make_layout((8, 1, 1))", "permutation_mnk=(D, BT, D)",
    )
    if not all(token in mma_text for token in required_mma_tokens):
        raise RuntimeError(f"INFRA_FAILURE: {name} O1 constructor tokens changed: {mma_text}")
    get_slices = [call for call in calls_named(method, "get_slice") if len(call.args) == 1 and ast.unparse(call.args[0]) == "tidx"]
    fragments = [call for call in calls_named(method, "make_fragment_C") if "partition_shape_C((D, BT))" in ast.unparse(call)]
    if not get_slices or len(fragments) != 1:
        raise RuntimeError(f"INFRA_FAILURE: {name} O1 slice/fragment construction is not uniquely bound")
    normalized = {
        "D": exact_constant(tree, "D"), "BT": exact_constant(tree, "BT"),
        "threads": threads, "active_threads": active,
        "acc_dtype_ast": canonical(acc_assignments[0].value),
        "o1_mma_ast": canonical(mma),
        "o1_fragment_ast": canonical(fragments[0]),
        "active_guard_ast": guard_ast,
    }
    return {
        "production_path": name, "source_path": str(path),
        "normalized": normalized,
        "normalized_sha256": canonical_digest(json.dumps(normalized, sort_keys=True)),
    }


def validate_ast_pair(short: dict, long: dict) -> dict:
    for binding in (short, long):
        normalized = binding["normalized"]
        if (normalized["D"], normalized["BT"], normalized["active_threads"]) != (D, BT, ACTIVE_THREADS):
            raise RuntimeError(f"INFRA_FAILURE: production domain mismatch: {binding['production_path']}")
    shared_keys = ("D", "BT", "active_threads", "acc_dtype_ast", "o1_mma_ast", "o1_fragment_ast")
    mismatches = [key for key in shared_keys if short["normalized"][key] != long["normalized"][key]]
    if mismatches:
        raise RuntimeError(f"INFRA_FAILURE: short/long canonical O1 AST differs: {mismatches}")
    return {"status": "PASS", "shared_keys": list(shared_keys), "short_block_threads": 512, "long_block_threads": 256}


def fragment_coordinate(tid: int, item: int) -> tuple[int, int]:
    warp_id, lane = divmod(tid, 32)
    lane_group, lane_in_group = divmod(lane, 4)
    atom_item = item % 4
    n8 = item // 4
    d = 16 * warp_id + lane_group + 8 * (atom_item // 2)
    n = 8 * n8 + 2 * lane_in_group + atom_item % 2
    return d, n


def exhaustive_mapping_rows() -> tuple[list[dict], dict]:
    rows: list[dict] = []
    global_seen: set[tuple[int, int]] = set()
    storage_seen: set[tuple[int, int]] = set()
    negative_mismatches = 0
    for tid in range(ACTIVE_THREADS):
        per_thread_offsets: set[int] = set()
        tile_sets: list[set[int]] = []
        for tile in range(BT // N_TILE):
            current_offsets: set[int] = set()
            for slot in range(8):
                full_item = tile * 8 + slot
                o1_d, o1_n = fragment_coordinate(tid, full_item)
                sv_d, sv_n_local = fragment_coordinate(tid, slot)
                expected = (sv_d, tile * N_TILE + sv_n_local)
                if (o1_d, o1_n) != expected:
                    raise AssertionError(f"PREDICATE_REJECT: coordinate mismatch tid={tid} tile={tile} slot={slot}")
                logical_offset = full_item
                coord = (o1_d, o1_n)
                storage = (tid, logical_offset)
                if coord in global_seen or storage in storage_seen or logical_offset in per_thread_offsets:
                    raise AssertionError(f"PREDICATE_REJECT: alias tid={tid} tile={tile} slot={slot}")
                global_seen.add(coord)
                storage_seen.add(storage)
                per_thread_offsets.add(logical_offset)
                current_offsets.add(logical_offset)
                lane_group, lane_in_group = divmod(tid % 32, 4)
                atom_item = slot % 4
                legacy_coord = (
                    lane_group + 8 * (atom_item // 2),
                    tile * N_TILE + 8 * (slot // 4) + 2 * lane_in_group + atom_item % 2,
                )
                if tid >= 32 or legacy_coord != coord:
                    negative_mismatches += 1
                rows.append({
                    "tid": tid, "owner_lane": tid % 32, "owner_warp": tid // 32,
                    "tile": tile, "slot": slot,
                    "o1_d": o1_d, "o1_n": o1_n,
                    "scorev_d": sv_d, "scorev_n_local": sv_n_local,
                    "absolute_fragment_offset": logical_offset,
                })
            if len(current_offsets) != 8:
                raise AssertionError("PREDICATE_REJECT: tile cardinality")
            if any(current_offsets & previous for previous in tile_sets):
                raise AssertionError("PREDICATE_REJECT: tiles overlap")
            tile_sets.append(current_offsets)
        if per_thread_offsets != set(range(32)):
            raise AssertionError(f"PREDICATE_REJECT: incomplete per-thread union tid={tid}")
    expected_coords = {(d, n) for d in range(D) for n in range(BT)}
    if global_seen != expected_coords or len(storage_seen) != D * BT or len(rows) != D * BT:
        raise AssertionError("PREDICATE_REJECT: global coverage is incomplete")
    if negative_mismatches == 0:
        raise AssertionError("PREDICATE_REJECT: negative control failed to discriminate")
    return rows, {
        "status": "PREDICATE_PASS", "row_count": len(rows),
        "unique_global_coordinates": len(global_seen),
        "unique_owner_offset_pairs": len(storage_seen),
        "per_thread_offset_set": [0, 31], "tile_cardinality": 8,
        "tile_count": 4, "negative_control_mismatches": negative_mismatches,
    }


class N2LiveCodegenProof:
    def __init__(self, block_threads: int):
        self.dtype = cutlass.BFloat16
        self.acc_dtype = cutlass.Float32
        self.block_threads = block_threads

    @cute.jit
    def live_body(self, g_sink: cute.Tensor, tidx: cutlass.Int32):
        o1_mma = cute.make_tiled_mma(
            warp.MmaF16BF16Op(self.dtype, self.acc_dtype, (16, 8, 16)),
            cute.make_layout((8, 1, 1)), permutation_mnk=(D, BT, D),
        )
        o1_thr = o1_mma.get_slice(tidx)
        output = o1_thr.make_fragment_C(o1_thr.partition_shape_C((D, BT)))
        output.fill(self.acc_dtype(0.0))
        h_operand = cute.make_rmem_tensor(o1_thr.partition_shape_A((D, D)), self.dtype)
        q_operand = cute.make_rmem_tensor(o1_thr.partition_shape_B((BT, D)), self.dtype)
        h_operand.fill(self.dtype(1.0))
        q_operand.fill(self.dtype(1.0))
        cute.gemm(o1_mma, output, h_operand, q_operand, output)

        scorev_mma = cute.make_tiled_mma(
            warp.MmaF16BF16Op(self.dtype, self.acc_dtype, (16, 8, 16)),
            cute.make_layout((8, 1, 1)), permutation_mnk=(D, N_TILE, N_TILE),
        )
        scorev_thr = scorev_mma.get_slice(tidx)
        prototype = scorev_thr.make_fragment_C(scorev_thr.partition_shape_C((D, N_TILE)))
        divided_layout = cute.logical_divide(output.layout, (None, None, 2))
        output_divided = cute.make_tensor(output.iterator, divided_layout)
        assert cute.size(output) == 32
        assert cute.size(prototype) == 8
        assert cute.size(output_divided) == cute.size(output)
        for tile_id in cutlass.range_constexpr(BT // N_TILE):
            tile = output_divided[None, None, (None, tile_id)]
            assert tile.layout == prototype.layout
            a_operand = cute.make_rmem_tensor(scorev_thr.partition_shape_A((D, N_TILE)), self.dtype)
            b_operand = cute.make_rmem_tensor(scorev_thr.partition_shape_B((N_TILE, N_TILE)), self.dtype)
            a_operand.fill(self.dtype(1.0))
            b_operand.fill(self.dtype(1.0))
            cute.gemm(scorev_mma, tile, a_operand, b_operand, tile)

        coordinates = o1_thr.partition_C(cute.make_identity_tensor((D, BT)))
        for item in cutlass.range(cute.size(output), unroll_full=True):
            d, n = coordinates[item]
            g_sink[d, n] = output[item]

    @cute.kernel
    def kernel(self, g_sink: cute.Tensor):
        tidx, _, _ = cute.arch.thread_idx()
        if tidx < cutlass.Int32(ACTIVE_THREADS):
            self.live_body(g_sink, tidx)

    @cute.jit
    def __call__(self, g_sink: cute.Tensor):
        self.kernel(g_sink).launch(
            grid=(1, 1, 1), block=(self.block_threads, 1, 1),
            max_number_threads=(self.block_threads, 1, 1), min_blocks_per_mp=1,
        )


class StaticRejectMarker:
    """Compilable marker used only for a recognized host-side predicate rejection."""

    @cute.kernel
    def kernel(self, g_sink: cute.Tensor):
        if cute.arch.thread_idx()[0] == 0:
            g_sink[0, 0] = cutlass.Float32(0.0)

    @cute.jit
    def __call__(self, g_sink: cute.Tensor):
        self.kernel(g_sink).launch(grid=(1, 1, 1), block=(1, 1, 1), max_number_threads=(1, 1, 1))


__all__ = [
    "ACTIVE_THREADS", "BT", "D", "N_TILE", "N2LiveCodegenProof", "StaticRejectMarker",
    "ast_binding", "exhaustive_mapping_rows", "validate_ast_pair",
]
