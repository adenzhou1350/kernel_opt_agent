"""PASS-only static proof for the production O1 -> four N16 layout view.

The JSONL records are an independent PTX accumulator oracle.  Admission also
requires real CuTe TV layouts, partition_C coordinate tensors, and fragment
slice offsets to agree with that oracle.  A compile/assert/tool failure is
always INVALID; it is never interpreted as candidate rejection.
"""

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


def digest_json(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
        raise RuntimeError(f"INFRA_FAILURE: integer assignment is not unique: {name}={matches}")
    return int(matches[0])


def class_method(tree: ast.Module, class_name: str, method_name: str) -> ast.FunctionDef:
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name]
    if len(classes) != 1:
        raise RuntimeError(f"INFRA_FAILURE: class is not unique: {class_name}")
    methods = [node for node in classes[0].body if isinstance(node, ast.FunctionDef) and node.name == method_name]
    if len(methods) != 1:
        raise RuntimeError(f"INFRA_FAILURE: method is not unique: {class_name}.{method_name}")
    return methods[0]


def unique_assignment(method: ast.FunctionDef, name: str) -> ast.Assign:
    matches = [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"INFRA_FAILURE: assignment is not unique: {name}, count={len(matches)}")
    return matches[0]


def exact_o1_chain(method: ast.FunctionDef) -> dict:
    mma_assignment = unique_assignment(method, "o1_mma")
    thr_assignment = unique_assignment(method, "o1_thr")
    output_assignment = unique_assignment(method, "output")
    mma = mma_assignment.value
    if not isinstance(mma, ast.Call) or ast.unparse(mma.func) != "cute.make_tiled_mma":
        raise RuntimeError("INFRA_FAILURE: o1_mma is not cute.make_tiled_mma")
    required = (
        "warp.MmaF16BF16Op(self.dtype, self.acc_dtype, (16, 8, 16))",
        "cute.make_layout((8, 1, 1))",
        "permutation_mnk=(D, BT, D)",
    )
    mma_text = ast.unparse(mma)
    if not all(token in mma_text for token in required):
        raise RuntimeError(f"INFRA_FAILURE: O1 MMA constructor changed: {mma_text}")
    if ast.unparse(thr_assignment.value) != "o1_mma.get_slice(tidx)":
        raise RuntimeError("INFRA_FAILURE: o1_mma -> o1_thr def-use chain changed")
    expected_fragment = "o1_thr.make_fragment_C(o1_thr.partition_shape_C((D, BT)))"
    if ast.unparse(output_assignment.value) != expected_fragment:
        raise RuntimeError("INFRA_FAILURE: o1_thr -> output def-use chain changed")
    return {
        "mma_constructor_ast": canonical(mma),
        "slice_ast": canonical(thr_assignment.value),
        "fragment_ast": canonical(output_assignment.value),
    }


def is_cutlass_int32_name(node: ast.AST, name: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "cutlass"
        and node.func.attr == "Int32"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == name
        and not node.keywords
    )


def is_short_active_guard(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and node.left.id == "tidx"
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.Lt)
        and len(node.comparators) == 1
        and is_cutlass_int32_name(node.comparators[0], "MAIN_THREADS")
    )


def statement_list_calls_method(statements: list[ast.stmt], method_name: str) -> bool:
    body = ast.Module(body=statements, type_ignores=[])
    return any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == method_name
        for call in ast.walk(body)
    )


def legacy_layout_value_asts(method: ast.FunctionDef) -> dict:
    names = (
        "o2_mma", "o2_thr", "tile_prototype", "tile_storage",
        "output_tiles_layout",
    )
    return {name: canonical(unique_assignment(method, name).value) for name in names}


def legacy_negative_ast_binding(path: Path, *, proof: bool) -> dict:
    tree = ast.parse(path.read_text(), filename=str(path))
    if proof:
        method = class_method(tree, "N2StaticLayoutProof", "proof_body")
        binding_kind = "proof_negative_control"
    else:
        method = class_method(
            tree, "S3PackedEpiW16RawKernelSm120", "causal_score_v_accumulate"
        )
        binding_kind = "immutable_legacy_attempt2"
    values = legacy_layout_value_asts(method)
    return {
        "binding_kind": binding_kind,
        "source_path": str(path),
        "normalized_value_asts": values,
        "normalized_value_asts_sha256": digest_json(values),
    }


def production_ast_binding(name: str, path: Path) -> dict:
    tree = ast.parse(path.read_text(), filename=str(path))
    if name == "short":
        class_name, producer_method = "S3PackedEpiW16RawKernelSm120", "output_main"
        threads = exact_constant(tree, "THREADS")
        active_threads = exact_constant(tree, "MAIN_THREADS")
        call_method = class_method(tree, class_name, "kernel")
        guards = [
            node
            for node in ast.walk(call_method)
            if isinstance(node, ast.If)
            and is_short_active_guard(node.test)
            and statement_list_calls_method(node.body, "output_main")
            and not statement_list_calls_method(node.orelse, "output_main")
        ]
        if len(guards) != 1:
            raise RuntimeError(
                "INFRA_FAILURE: exact tidx<cutlass.Int32(MAIN_THREADS) body "
                "does not uniquely contain output_main"
            )
        active_guard = canonical(guards[0].test)
    else:
        class_name, producer_method = "S3PackedWorkspaceDecayRawKernelSm120", "kernel"
        threads = exact_constant(tree, "THREADS")
        active_threads = threads
        active_guard = "ALL_BLOCK_THREADS_ACTIVE"
    method = class_method(tree, class_name, producer_method)
    init = class_method(tree, class_name, "__init__")
    acc = [
        node
        for node in ast.walk(init)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Attribute) and target.attr == "acc_dtype" for target in node.targets)
    ]
    if len(acc) != 1 or ast.unparse(acc[0].value) != "cutlass.Float32":
        raise RuntimeError(f"INFRA_FAILURE: {name} accumulator dtype is not uniquely Float32")
    signature = {
        "D": exact_constant(tree, "D"),
        "BT": exact_constant(tree, "BT"),
        "active_threads": active_threads,
        "acc_dtype_ast": canonical(acc[0].value),
        **exact_o1_chain(method),
    }
    return {
        "binding_kind": "production",
        "production_path": name,
        "source_path": str(path),
        "block_threads": threads,
        "active_guard_ast": active_guard,
        "layout_signature": signature,
        "layout_signature_sha256": digest_json(signature),
    }


def proof_ast_binding(path: Path) -> dict:
    tree = ast.parse(path.read_text(), filename=str(path))
    method = class_method(tree, "N2StaticLayoutProof", "proof_body")
    init = class_method(tree, "N2StaticLayoutProof", "__init__")
    acc = [
        node
        for node in ast.walk(init)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Attribute) and target.attr == "acc_dtype" for target in node.targets)
    ]
    if len(acc) != 1 or ast.unparse(acc[0].value) != "cutlass.Float32":
        raise RuntimeError("INFRA_FAILURE: proof accumulator dtype is not uniquely Float32")
    signature = {
        "D": D,
        "BT": BT,
        "active_threads": ACTIVE_THREADS,
        "acc_dtype_ast": canonical(acc[0].value),
        **exact_o1_chain(method),
    }
    return {
        "binding_kind": "proof",
        "source_path": str(path),
        "layout_signature": signature,
        "layout_signature_sha256": digest_json(signature),
    }


def validate_ast_triplet(
    short: dict,
    long: dict,
    proof: dict,
    legacy: dict,
    proof_negative: dict,
) -> dict:
    bindings = {"short": short, "long": long, "proof": proof}
    expected_domain = (D, BT, ACTIVE_THREADS)
    for name, binding in bindings.items():
        signature = binding["layout_signature"]
        observed = (signature["D"], signature["BT"], signature["active_threads"])
        if observed != expected_domain:
            raise RuntimeError(f"INFRA_FAILURE: {name} layout domain differs: {observed}")
    hashes = {name: item["layout_signature_sha256"] for name, item in bindings.items()}
    if len(set(hashes.values())) != 1:
        raise RuntimeError(f"INFRA_FAILURE: production/proof layout AST differs: {hashes}")
    if (short["block_threads"], long["block_threads"]) != (512, 256):
        raise RuntimeError("INFRA_FAILURE: short/long block domains changed")
    if legacy["normalized_value_asts"] != proof_negative["normalized_value_asts"]:
        raise RuntimeError(
            "INFRA_FAILURE: proof negative control differs from immutable "
            "attempt-2 normalized constructor AST"
        )
    return {
        "status": "PASS",
        "layout_signature_sha256": hashes["short"],
        "triplet_hashes": hashes,
        "short_block_threads": 512,
        "long_block_threads": 256,
        "active_threads": ACTIVE_THREADS,
        "legacy_negative_ast_sha256": legacy["normalized_value_asts_sha256"],
        "proof_negative_ast_sha256": proof_negative["normalized_value_asts_sha256"],
        "legacy_negative_exact_ast_equal": True,
    }


def expected_fragment_coordinate(tid: int, item: int) -> tuple[int, int]:
    """Independent PTX mma.sync accumulator mapping oracle."""
    warp_id, lane = divmod(tid, 32)
    lane_group, lane_in_group = divmod(lane, 4)
    atom_item = item % 4
    n8 = item // 4
    d = 16 * warp_id + lane_group + 8 * (atom_item // 2)
    n = 8 * n8 + 2 * lane_in_group + atom_item % 2
    return d, n


def expected_legacy_coordinate(lane: int, item: int) -> tuple[int, int]:
    lane_group, lane_in_group = divmod(lane, 4)
    atom_item = item % 4
    n8 = item // 4
    d = lane_group + 8 * (atom_item // 2)
    n = 8 * n8 + 2 * lane_in_group + atom_item % 2
    return d, n


def oracle_witness_rows() -> tuple[list[dict], dict]:
    rows: list[dict] = []
    coordinates: set[tuple[int, int]] = set()
    owner_offsets: set[tuple[int, int]] = set()
    for tid in range(ACTIVE_THREADS):
        offsets: set[int] = set()
        tile_sets: list[set[int]] = []
        for tile in range(BT // N_TILE):
            current: set[int] = set()
            for slot in range(8):
                expected_item = tile * 8 + slot
                d, n = expected_fragment_coordinate(tid, expected_item)
                sv_d, sv_n = expected_fragment_coordinate(tid, slot)
                if (d, n) != (sv_d, tile * N_TILE + sv_n):
                    raise RuntimeError("INFRA_FAILURE: independent PTX oracle disagrees across MMA shapes")
                coordinate = (d, n)
                owner_offset = (tid, expected_item)
                if coordinate in coordinates or owner_offset in owner_offsets:
                    raise RuntimeError("INFRA_FAILURE: independent PTX oracle aliases")
                coordinates.add(coordinate)
                owner_offsets.add(owner_offset)
                offsets.add(expected_item)
                current.add(expected_item)
                legacy_d, legacy_n = expected_legacy_coordinate(tid % 32, slot)
                rows.append({
                    "tid": tid,
                    "owner_warp": tid // 32,
                    "owner_lane": tid % 32,
                    "tile": tile,
                    "slot": slot,
                    "oracle_o1_item": expected_item,
                    "oracle_o1_d": d,
                    "oracle_o1_n": n,
                    "oracle_o1_linear": d + D * n,
                    "oracle_scorev_d": sv_d,
                    "oracle_scorev_n_local": sv_n,
                    "oracle_scorev_linear": sv_d + D * sv_n,
                    "oracle_legacy_d": legacy_d,
                    "oracle_legacy_n_local": legacy_n,
                    "oracle_legacy_linear": legacy_d + N_TILE * legacy_n,
                })
            if len(current) != 8 or any(current & prior for prior in tile_sets):
                raise RuntimeError("INFRA_FAILURE: independent PTX oracle tile partition failed")
            tile_sets.append(current)
        if offsets != set(range(32)):
            raise RuntimeError("INFRA_FAILURE: independent PTX oracle backing union failed")
    expected_coordinates = {(d, n) for d in range(D) for n in range(BT)}
    if coordinates != expected_coordinates or len(owner_offsets) != D * BT:
        raise RuntimeError("INFRA_FAILURE: independent PTX oracle coverage failed")
    return rows, {
        "status": "EXPECTED_PTX_ORACLE_COMPLETE",
        "row_count": len(rows),
        "unique_global_coordinates": len(coordinates),
        "unique_owner_offset_pairs": len(owner_offsets),
        "tile_count": BT // N_TILE,
        "tile_cardinality": 8,
        "per_thread_oracle_item_union": [0, 31],
        "legacy_replication_aliases_across_warps": True,
    }


class N2StaticLayoutProof:
    def __init__(self, block_threads: int):
        self.dtype = cutlass.BFloat16
        self.acc_dtype = cutlass.Float32
        self.block_threads = block_threads

    @cute.jit
    def proof_body(self, g_sink: cute.Tensor, tidx: cutlass.Int32):
        o1_mma = cute.make_tiled_mma(
            warp.MmaF16BF16Op(self.dtype, self.acc_dtype, (16, 8, 16)),
            cute.make_layout((8, 1, 1)),
            permutation_mnk=(D, BT, D),
        )
        o1_thr = o1_mma.get_slice(tidx)
        output = o1_thr.make_fragment_C(o1_thr.partition_shape_C((D, BT)))
        output.fill(self.acc_dtype(0.0))

        scorev_mma = cute.make_tiled_mma(
            warp.MmaF16BF16Op(self.dtype, self.acc_dtype, (16, 8, 16)),
            cute.make_layout((8, 1, 1)),
            permutation_mnk=(D, N_TILE, N_TILE),
        )
        scorev_thr = scorev_mma.get_slice(tidx)
        scorev_fragment = scorev_thr.make_fragment_C(scorev_thr.partition_shape_C((D, N_TILE)))
        divided_layout = cute.logical_divide(output.layout, (None, None, 2))
        output_divided = cute.make_tensor(output.iterator, divided_layout)
        o1_tv = o1_mma.tv_layout_C_tiled
        scorev_tv = scorev_mma.tv_layout_C_tiled

        assert cute.size(o1_tv, mode=[0]) == ACTIVE_THREADS
        assert cute.size(o1_tv, mode=[1]) == 32
        assert cute.size(scorev_tv, mode=[0]) == ACTIVE_THREADS
        assert cute.size(scorev_tv, mode=[1]) == 8
        assert cute.size(output) == 32
        assert cute.size(scorev_fragment) == 8
        assert cute.size(output_divided) == cute.size(output)

        identity = cute.make_identity_tensor((D, BT))
        for owner in cutlass.range_constexpr(ACTIVE_THREADS):
            owner_o1_thr = o1_mma.get_slice(owner)
            o1_coordinates = owner_o1_thr.partition_C(identity)
            o1_thread_coord = cute.idx2crd(owner, cute.shape(o1_tv, mode=0))
            for item in cutlass.range_constexpr(32):
                o1_value_coord = cute.idx2crd(item, cute.shape(o1_tv, mode=1))
                o1_linear = cute.crd2idx((o1_thread_coord, o1_value_coord), o1_tv)
                oracle_d, oracle_n = expected_fragment_coordinate(owner, item)
                assert o1_linear == oracle_d + D * oracle_n
                actual_d, actual_n = o1_coordinates[item]
                assert actual_d == oracle_d
                assert actual_n == oracle_n

            for tile_id in cutlass.range_constexpr(BT // N_TILE):
                identity_tile = cute.local_tile(identity, (D, N_TILE), (0, tile_id))
                owner_scorev_thr = scorev_mma.get_slice(owner)
                scorev_coordinates = owner_scorev_thr.partition_C(identity_tile)
                scorev_thread_coord = cute.idx2crd(owner, cute.shape(scorev_tv, mode=0))
                slicer = (None, None, (None, tile_id))
                tile_layout, tile_base = cute.slice_and_offset(slicer, divided_layout)
                tile = output_divided[slicer]
                assert tile.layout == tile_layout
                assert tile_layout == scorev_fragment.layout
                for slot in cutlass.range_constexpr(8):
                    scorev_value_coord = cute.idx2crd(slot, cute.shape(scorev_tv, mode=1))
                    scorev_linear = cute.crd2idx((scorev_thread_coord, scorev_value_coord), scorev_tv)
                    scorev_d, scorev_n = scorev_coordinates[slot]
                    local_coord = cute.idx2crd(slot, tile_layout.shape)
                    view_offset = tile_base + cute.crd2idx(local_coord, tile_layout)
                    oracle_sv_d, oracle_sv_n = expected_fragment_coordinate(owner, slot)
                    assert scorev_linear == oracle_sv_d + D * oracle_sv_n
                    assert scorev_d == oracle_sv_d
                    assert scorev_n == tile_id * N_TILE + oracle_sv_n

                    matches = 0
                    for original_item in cutlass.range_constexpr(32):
                        original_coord = cute.idx2crd(original_item, output.layout.shape)
                        original_offset = cute.crd2idx(original_coord, output.layout)
                        if cutlass.const_expr(original_offset == view_offset):
                            matches += 1
                            o1_d, o1_n = o1_coordinates[original_item]
                            assert o1_d == scorev_d
                            assert o1_n == scorev_n
                    assert matches == 1

        # Exact rejected attempt-2 negative layout: one-warp fragment appended
        # four times.  It must differ from the real production O1 layout.
        lane = tidx % cutlass.Int32(32)
        o2_mma = cute.make_tiled_mma(
            warp.MmaF16BF16Op(self.dtype, self.acc_dtype, (16, 8, 16)),
            cute.make_layout((1, 1, 1)),
            permutation_mnk=(16, 16, 16),
        )
        o2_thr = o2_mma.get_slice(lane)
        tile_prototype = o2_thr.make_fragment_C(
            o2_thr.partition_shape_C((16, 16))
        )
        tile_storage = cute.cosize(tile_prototype.layout)
        output_tiles_layout = cute.append(
            tile_prototype.layout,
            cute.make_layout(
                (BT // 16,),
                stride=(tile_storage,),
            ),
        )
        assert output.layout != output_tiles_layout
        legacy_tv = o2_mma.tv_layout_C_tiled
        assert cute.size(legacy_tv, mode=[0]) == 32
        assert cute.size(legacy_tv, mode=[1]) == 8
        legacy_t0 = cute.idx2crd(0, cute.shape(legacy_tv, mode=0))
        legacy_v0 = cute.idx2crd(0, cute.shape(legacy_tv, mode=1))
        scorev_t0 = cute.idx2crd(0, cute.shape(scorev_tv, mode=0))
        scorev_t32 = cute.idx2crd(32, cute.shape(scorev_tv, mode=0))
        scorev_v0 = cute.idx2crd(0, cute.shape(scorev_tv, mode=1))
        assert cute.crd2idx((legacy_t0, legacy_v0), legacy_tv) == 0
        assert cute.crd2idx((scorev_t0, scorev_v0), scorev_tv) != cute.crd2idx((scorev_t32, scorev_v0), scorev_tv)

        # Typed C/D use only; no production-SASS or resource claim is made.
        a_operand = cute.make_rmem_tensor(scorev_thr.partition_shape_A((D, N_TILE)), self.dtype)
        b_operand = cute.make_rmem_tensor(scorev_thr.partition_shape_B((N_TILE, N_TILE)), self.dtype)
        a_operand.fill(self.dtype(1.0))
        b_operand.fill(self.dtype(1.0))
        for tile_id in cutlass.range_constexpr(BT // N_TILE):
            tile = output_divided[None, None, (None, tile_id)]
            cute.gemm(scorev_mma, tile, a_operand, b_operand, tile)

        coordinates = o1_thr.partition_C(identity)
        for item in cutlass.range(cute.size(output), unroll_full=True):
            d, n = coordinates[item]
            g_sink[d, n] = output[item]

    @cute.kernel
    def kernel(self, g_sink: cute.Tensor):
        tidx, _, _ = cute.arch.thread_idx()
        if tidx < cutlass.Int32(ACTIVE_THREADS):
            self.proof_body(g_sink, tidx)

    @cute.jit
    def __call__(self, g_sink: cute.Tensor):
        self.kernel(g_sink).launch(
            grid=(1, 1, 1),
            block=(self.block_threads, 1, 1),
            max_number_threads=(self.block_threads, 1, 1),
            min_blocks_per_mp=1,
        )


class N2ShortStaticLayoutProof(N2StaticLayoutProof):
    def __init__(self):
        super().__init__(block_threads=512)


class N2LongStaticLayoutProof(N2StaticLayoutProof):
    def __init__(self):
        super().__init__(block_threads=256)


__all__ = [
    "ACTIVE_THREADS", "BT", "D", "N_TILE", "N2StaticLayoutProof",
    "N2ShortStaticLayoutProof", "N2LongStaticLayoutProof",
    "oracle_witness_rows", "production_ast_binding", "proof_ast_binding",
    "legacy_negative_ast_binding",
    "validate_ast_triplet",
]
