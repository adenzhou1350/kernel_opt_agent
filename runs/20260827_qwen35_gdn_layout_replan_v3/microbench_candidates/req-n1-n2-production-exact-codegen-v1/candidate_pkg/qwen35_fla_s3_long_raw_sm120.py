"""Production long-S raw S3 consuming packed K with decay broadcast."""

from __future__ import annotations

import cutlass
import cutlass.cute as cute
from cutlass.cute.nvgpu import warp, warpgroup

from flashinfer.gdn_kernels.delta_rule_dsl.custom_compile_cache import (
    KeyedCompileMixin,
)


BT = 64
D = 128
THREADS = 256
QK_STORE_BARRIER = 1


class S3PackedWorkspaceDecayRawKernelSm120(KeyedCompileMixin):
    def __init__(
        self,
        dtype,
        cu_seqlens_dtype,
        *,
        causal_qk_schedule: bool,
        causal_scorev_schedule: bool,
    ):
        self.dtype = dtype
        self.acc_dtype = cutlass.Float32
        self.cu_seqlens_dtype = cu_seqlens_dtype
        self.causal_qk_schedule = causal_qk_schedule
        self.causal_scorev_schedule = causal_scorev_schedule
        self.manual_cache_key(
            "dtype",
            "cu_seqlens_dtype",
            "causal_qk_schedule",
            "causal_scorev_schedule",
        )

    @cute.jit
    def load_a_aligned(
        self,
        s_tensor: cute.Tensor,
        tiled_mma,
        tidx: cutlass.Int32,
        a_shape,
        transpose: cutlass.Constexpr,
    ) -> cute.Tensor:
        if cutlass.const_expr(transpose):
            atom = cute.make_copy_atom(
                warp.LdMatrix8x8x16bOp(transpose=True, num_matrices=4),
                self.dtype,
            )
        else:
            atom = cute.make_copy_atom(
                warp.LdMatrix8x8x16bOp(transpose=False, num_matrices=4),
                self.dtype,
            )
        tiled_copy = cute.make_tiled_copy_A(atom, tiled_mma)
        thr_copy = tiled_copy.get_slice(tidx)
        operand = cute.make_rmem_tensor(
            tiled_mma.partition_shape_A(a_shape), self.dtype
        )
        operand_copy = thr_copy.retile(operand)
        source = thr_copy.partition_S(s_tensor)
        source = cute.make_tensor(source.iterator.align(16), source.layout)
        cute.copy(tiled_copy, source, operand_copy)
        return operand

    @cute.jit
    def load_b_aligned(
        self,
        s_tensor: cute.Tensor,
        tiled_mma,
        tidx: cutlass.Int32,
        b_shape,
        transpose: cutlass.Constexpr,
    ) -> cute.Tensor:
        if cutlass.const_expr(transpose):
            atom = cute.make_copy_atom(
                warp.LdMatrix8x8x16bOp(transpose=True, num_matrices=4),
                self.dtype,
            )
        else:
            atom = cute.make_copy_atom(
                warp.LdMatrix8x8x16bOp(transpose=False, num_matrices=4),
                self.dtype,
            )
        tiled_copy = cute.make_tiled_copy_B(atom, tiled_mma)
        thr_copy = tiled_copy.get_slice(tidx)
        operand = cute.make_rmem_tensor(
            tiled_mma.partition_shape_B(b_shape), self.dtype
        )
        operand_copy = thr_copy.retile(operand)
        source = thr_copy.partition_S(s_tensor)
        source = cute.make_tensor(source.iterator.align(16), source.layout)
        cute.copy(tiled_copy, source, operand_copy)
        return operand

    @cute.jit
    def store_qk(
        self,
        qk: cute.Tensor,
        s_qk: cute.Tensor,
        tiled_mma,
        tidx: cutlass.Int32,
    ):
        atom = cute.make_copy_atom(
            warp.StMatrix8x8x16bOp(transpose=False, num_matrices=4), self.dtype
        )
        tiled_copy = cute.make_tiled_copy_C(atom, tiled_mma)
        thr_copy = tiled_copy.get_slice(tidx)
        destination = thr_copy.partition_D(s_qk)
        destination = cute.make_tensor(
            destination.iterator.align(16), destination.layout
        )
        qk_bf16 = cute.make_fragment_like(qk, self.dtype)
        for item in cutlass.range(cute.size(qk), unroll_full=True):
            qk_bf16[item] = self.dtype(qk[item])
        source = thr_copy.retile(qk_bf16)
        cute.copy(tiled_copy, source, destination)

    @cute.jit
    def store_qk_bf16(
        self,
        qk_bf16: cute.Tensor,
        s_qk: cute.Tensor,
        tiled_mma,
        tidx: cutlass.Int32,
    ):
        """Publish an already-rounded BF16 score fragment with STMatrix."""

        atom = cute.make_copy_atom(
            warp.StMatrix8x8x16bOp(transpose=False, num_matrices=4), self.dtype
        )
        tiled_copy = cute.make_tiled_copy_C(atom, tiled_mma)
        thr_copy = tiled_copy.get_slice(tidx)
        destination = thr_copy.partition_D(s_qk)
        destination = cute.make_tensor(
            destination.iterator.align(16), destination.layout
        )
        source = thr_copy.retile(qk_bf16)
        cute.copy(tiled_copy, source, destination)

    @cute.jit
    def causal_qk_register_fragment(
        self,
        q_operand: cute.Tensor,
        k_tiles: cute.Tensor,
        s_g: cute.Tensor,
        qk_mma,
        qk_thr,
        scale: cutlass.Float32,
        valid_len: cutlass.Int32,
        warp_idx: cutlass.Int32,
        lane: cutlass.Int32,
        col_tile: cutlass.Constexpr,
    ) -> cute.Tensor:
        """Return one rounded score tile without publishing shared memory."""

        qk = qk_thr.make_fragment_C(qk_thr.partition_shape_C((16, 16)))
        qk.fill(self.acc_dtype(0.0))
        if (
            cutlass.Int32(col_tile) <= warp_idx
            and cutlass.Int32(col_tile * 16) < valid_len
            and warp_idx * cutlass.Int32(16) < valid_len
        ):
            k_operand = self.load_b_aligned(
                k_tiles[None, None, cutlass.Int32(col_tile), 0],
                qk_mma,
                lane,
                (16, D),
                False,
            )
            cute.gemm(qk_mma, qk, q_operand, k_operand, qk)

        coordinates = qk_thr.partition_C(
            cute.make_identity_tensor((16, 16))
        )
        qk_bf16 = cute.make_fragment_like(qk, self.dtype)
        for item in cutlass.range(cute.size(qk), unroll_full=True):
            row_local, col_local = coordinates[item]
            row = row_local + warp_idx * cutlass.Int32(16)
            col = col_local + cutlass.Int32(col_tile * 16)
            value = cutlass.Float32(0.0)
            if (
                cutlass.Int32(col_tile) <= warp_idx
                and row < valid_len
                and col < valid_len
                and col <= row
            ):
                value = (
                    cutlass.Float32(qk[item])
                    * cute.math.exp(
                        cutlass.Float32(s_g[row])
                        - cutlass.Float32(s_g[col]),
                        fastmath=True,
                    )
                    * scale
                )
            qk_bf16[item] = self.dtype(value)
        return qk_bf16

    @cute.jit
    def causal_qk_main(
        self,
        s_q: cute.Tensor,
        s_k: cute.Tensor,
        s_qk: cute.Tensor,
        s_g: cute.Tensor,
        scale: cutlass.Float32,
        valid_len: cutlass.Int32,
        tidx: cutlass.Int32,
    ):
        """Compute causal QK before publishing aliased score storage.

        All four possible N16 score fragments are initialized to zero, while
        MMA is issued only for col_tile <= row_tile.  Fragments remain in
        registers until a 128-thread named barrier proves that every QK warp has
        completed every K read.  Only then may score stores overwrite the K
        backing interval.  Storing all fragments also defines the six upper
        tiles as BF16 zero for the C1 dense score-V fallback.
        """

        warp_idx = tidx // cutlass.Int32(32)
        lane = tidx % cutlass.Int32(32)
        q_tiles = cute.flat_divide(s_q, (16, D))
        k_tiles = cute.flat_divide(s_k, (16, D))
        score_tiles = cute.flat_divide(s_qk, (16, 16))
        qk_mma = cute.make_tiled_mma(
            warp.MmaF16BF16Op(self.dtype, self.acc_dtype, (16, 8, 16)),
            cute.make_layout((1, 1, 1)),
            permutation_mnk=(16, 16, D),
        )
        qk_thr = qk_mma.get_slice(lane)
        q_tile = q_tiles[None, None, warp_idx, 0]
        q_operand = self.load_a_aligned(
            q_tile, qk_mma, lane, (16, D), False
        )
        qk0 = self.causal_qk_register_fragment(
            q_operand, k_tiles, s_g, qk_mma, qk_thr, scale,
            valid_len, warp_idx, lane, 0,
        )
        qk1 = self.causal_qk_register_fragment(
            q_operand, k_tiles, s_g, qk_mma, qk_thr, scale,
            valid_len, warp_idx, lane, 1,
        )
        qk2 = self.causal_qk_register_fragment(
            q_operand, k_tiles, s_g, qk_mma, qk_thr, scale,
            valid_len, warp_idx, lane, 2,
        )
        qk3 = self.causal_qk_register_fragment(
            q_operand, k_tiles, s_g, qk_mma, qk_thr, scale,
            valid_len, warp_idx, lane, 3,
        )

        # Exactly four complete QK warps enter this helper.  No score store may
        # execute before all reads from the aliased K interval are complete.
        cute.arch.barrier(
            barrier_id=QK_STORE_BARRIER, number_of_threads=128
        )

        for col_tile, qk in ((0, qk0), (1, qk1), (2, qk2), (3, qk3)):
            score_tile = score_tiles[
                None,
                None,
                warp_idx,
                cutlass.Int32(col_tile),
            ]
            self.store_qk_bf16(qk, score_tile, qk_mma, lane)

    @cute.jit
    def causal_score_v_accumulate(
        self,
        output: cute.Tensor,
        s_v: cute.Tensor,
        s_qk: cute.Tensor,
        valid_len: cutlass.Int32,
        tidx: cutlass.Int32,
    ):
        """Use four same-backing N16 views and reuse each V K-tile once.

        The K tile is the outer loop, so each output tile observes the original
        ascending K order while the shared-memory V request is not multiplied
        by the number of causal output tiles.  ``logical_divide`` is the exact
        eight-warp view admitted by the static layout proof; it performs no
        fragment copy or shared/global materialization.
        """

        scorev_mma = cute.make_tiled_mma(
            warp.MmaF16BF16Op(self.dtype, self.acc_dtype, (16, 8, 16)),
            cute.make_layout((8, 1, 1)),
            permutation_mnk=(D, 16, 16),
        )
        output_divided = cute.make_tensor(
            output.iterator,
            cute.logical_divide(output.layout, (None, None, 2)),
        )
        for col_tile in cutlass.range_constexpr(BT // 16):
            if cutlass.Int32(col_tile * 16) < valid_len:
                v_tile = cute.local_tile(
                    s_v, (D, 16), (0, cutlass.Int32(col_tile))
                )
                v_operand = self.load_a_aligned(
                    v_tile, scorev_mma, tidx, (D, 16), True
                )
                for row_tile in cutlass.range_constexpr(BT // 16):
                    if cutlass.const_expr(col_tile <= row_tile):
                        if cutlass.Int32(row_tile * 16) < valid_len:
                            score_tile = cute.local_tile(
                                s_qk,
                                (16, 16),
                                (
                                    cutlass.Int32(row_tile),
                                    cutlass.Int32(col_tile),
                                ),
                            )
                            score_operand = self.load_b_aligned(
                                score_tile,
                                scorev_mma,
                                tidx,
                                (16, 16),
                                False,
                            )
                            tile_output = output_divided[
                                None, None, (None, row_tile)
                            ]
                            cute.gemm(
                                scorev_mma,
                                tile_output,
                                v_operand,
                                score_operand,
                                tile_output,
                            )

    @cute.jit
    def store_output_bf16(
        self,
        output: cute.Tensor,
        s_o: cute.Tensor,
        tiled_mma,
        tidx: cutlass.Int32,
    ):
        atom = cute.make_copy_atom(
            warp.StMatrix8x8x16bOp(transpose=True, num_matrices=4), self.dtype
        )
        tiled_copy = cute.make_tiled_copy_C(atom, tiled_mma)
        thr_copy = tiled_copy.get_slice(tidx)
        destination = thr_copy.partition_D(s_o)
        destination = cute.make_tensor(
            destination.iterator.align(16), destination.layout
        )
        output_bf16 = cute.make_fragment_like(output, self.dtype)
        for item in cutlass.range(cute.size(output), unroll_full=True):
            output_bf16[item] = self.dtype(output[item])
        source = thr_copy.retile(output_bf16)
        cute.copy(tiled_copy, source, destination)

    @cute.jit
    def raw_output_epilogue(
        self,
        s_o: cute.Tensor,
        g_raw_o: cute.Tensor,
        tok_offset: cutlass.Int32,
        valid_len: cutlass.Int32,
        head_idx: cutlass.Int32,
        tidx: cutlass.Int32,
    ):
        lane = tidx % cutlass.Int32(32)
        warp_idx = tidx // cutlass.Int32(32)
        for row_iter in cutlass.range_constexpr(BT // 8):
            row = warp_idx + cutlass.Int32(row_iter * 8)
            if row < valid_len:
                token_idx = tok_offset + row
                for item in cutlass.range_constexpr(D // 32):
                    d_idx = lane + cutlass.Int32(item * 32)
                    value = cutlass.Float32(s_o[d_idx, row])
                    g_raw_o[d_idx, token_idx, head_idx] = self.dtype(value)

    @cute.jit
    def __call__(
        self,
        g_q: cute.Tensor,
        g_k: cute.Tensor,
        g_v_new: cute.Tensor,
        g_h: cute.Tensor,
        g_cumulative: cute.Tensor,
        g_raw_o: cute.Tensor,
        g_cu_seqlens: cute.Tensor,
        scale: cutlass.Float32,
        num_heads: cutlass.Int32,
        total_chunks: cutlass.Int32,
        stream,
    ):
        qkv_atom = warpgroup.make_smem_layout_atom(
            warpgroup.SmemLayoutAtomKind.K_INTER, self.dtype
        )
        qk_sd = cute.tile_to_shape(qkv_atom, (BT, D), order=(0, 1))
        qk_ds = cute.select(qk_sd, [1, 0])
        score_atom = cute.make_layout((8, 8), stride=(8, 1))
        score_layout = cute.tile_to_shape(score_atom, (BT, BT), order=(0, 1))
        o_atom = warpgroup.make_smem_layout_atom(
            warpgroup.SmemLayoutAtomKind.MN_SW128, self.dtype
        )
        o_layout = cute.tile_to_shape(o_atom, (D, BT), order=(1, 0))
        g_layout = cute.make_layout(BT)

        @cute.struct
        class SharedStorage:
            # Phase 1: Q | K | V (3 * 16 KiB).  Once Q@K^T has consumed K,
            # the first 8 KiB of K becomes score.  Once both output GEMMs have
            # consumed Q/K/V/score, the Q region becomes the BF16 output tile.
            # The peak is therefore 48 KiB instead of 72 KiB.
            smem_workspace: cute.struct.Align[
                cute.struct.MemRange[
                    self.dtype, 3 * cute.cosize(qk_sd)
                ],
                128,
            ]
            smem_g: cute.struct.Align[
                cute.struct.MemRange[cutlass.Float32, cute.cosize(g_layout)], 16
            ]

        self.shared_storage = SharedStorage
        self.kernel(
            g_q,
            g_k,
            g_v_new,
            g_h,
            g_cumulative,
            g_raw_o,
            g_cu_seqlens,
            scale,
            num_heads,
            total_chunks,
        ).launch(
            grid=(total_chunks * num_heads, 1, 1),
            block=(THREADS, 1, 1),
            max_number_threads=(THREADS, 1, 1),
            stream=stream,
            min_blocks_per_mp=1,
        )

    @cute.kernel
    def kernel(
        self,
        g_q: cute.Tensor,
        g_k: cute.Tensor,
        g_v_new: cute.Tensor,
        g_h: cute.Tensor,
        g_cumulative: cute.Tensor,
        g_raw_o: cute.Tensor,
        g_cu_seqlens: cute.Tensor,
        scale: cutlass.Float32,
        num_heads: cutlass.Int32,
        total_chunks: cutlass.Int32,
    ):
        tidx, _, _ = cute.arch.thread_idx()
        block_idx, _, _ = cute.arch.block_idx()
        head_idx = block_idx % num_heads
        chunk_idx = block_idx // num_heads
        seq_start = cutlass.Int32(g_cu_seqlens[0])
        seq_len = cutlass.Int32(g_cu_seqlens[1] - seq_start)
        tok_offset = seq_start + chunk_idx * cutlass.Int32(BT)
        valid_len = seq_len - chunk_idx * cutlass.Int32(BT)
        if valid_len > cutlass.Int32(BT):
            valid_len = cutlass.Int32(BT)

        qkv_atom = warpgroup.make_smem_layout_atom(
            warpgroup.SmemLayoutAtomKind.K_INTER, self.dtype
        )
        qk_sd = cute.tile_to_shape(qkv_atom, (BT, D), order=(0, 1))
        qk_ds = cute.select(qk_sd, [1, 0])
        score_atom = cute.make_layout((8, 8), stride=(8, 1))
        score_layout = cute.tile_to_shape(score_atom, (BT, BT), order=(0, 1))
        o_atom = warpgroup.make_smem_layout_atom(
            warpgroup.SmemLayoutAtomKind.MN_SW128, self.dtype
        )
        o_layout = cute.tile_to_shape(o_atom, (D, BT), order=(1, 0))
        allocator = cutlass.utils.SmemAllocator()
        storage = allocator.allocate(self.shared_storage)
        workspace = storage.smem_workspace.data_ptr()
        tile_elems = cute.cosize(qk_sd)
        s_q = cute.make_tensor(
            cute.recast_ptr(workspace, qk_sd.inner, dtype=self.dtype),
            qk_sd.outer,
        )
        s_k = cute.make_tensor(
            cute.recast_ptr(
                workspace + tile_elems, qk_sd.inner, dtype=self.dtype
            ),
            qk_sd.outer,
        )
        s_k_physical = cute.make_tensor(
            cute.recast_ptr(workspace + tile_elems, dtype=self.dtype),
            cute.make_layout(BT * D),
        )
        s_v = cute.make_tensor(
            cute.recast_ptr(
                workspace + 2 * tile_elems, qk_ds.inner, dtype=self.dtype
            ),
            qk_ds.outer,
        )
        # K has already been loaded into the QK MMA registers when this view is
        # written, so the score matrix may safely alias the beginning of K.
        s_qk = cute.make_tensor(
            cute.recast_ptr(workspace + tile_elems, dtype=self.dtype),
            score_layout,
        )
        # All Q/K/V/score operands are in registers before this view is written.
        s_o = cute.make_tensor(
            cute.recast_ptr(workspace, o_layout.inner, dtype=self.dtype),
            o_layout.outer,
        )
        s_g = storage.smem_g.get_tensor(cute.make_layout(BT))

        # Direct coalesced physical copy: S01 packed K and this shared K tile
        # have identical K_INTER byte order.  No logical K materialization.
        k_tile_base = (
            (chunk_idx * num_heads + head_idx)
            * cutlass.Int32(BT * D)
        )

        # Full constexpr unrolling lets ptxas hoist 32 packed-K loads and
        # retain them until a late shared store, raising the allocation to 160
        # registers/thread and forcing one CTA/SM.  Eight-way unrolling bounds
        # that live range while preserving addresses, ownership and BF16 ABI.
        for item in cutlass.range(
            (BT * D) // THREADS,
            unroll=8,
            at_least_once=True,
        ):
            linear = tidx + cutlass.Int32(item * THREADS)
            row = linear // cutlass.Int32(D)
            d_idx = linear % cutlass.Int32(D)
            q_value = self.dtype(0.0)
            v_value = self.dtype(0.0)
            if row < valid_len:
                q_value = g_q[d_idx, tok_offset + row, head_idx]
                v_value = g_v_new[d_idx, tok_offset + row, head_idx]
            s_q[row, d_idx] = q_value
            s_k_physical[linear] = g_k[k_tile_base + linear]
            s_v[d_idx, row] = v_value
        if tidx < cutlass.Int32(BT):
            g_value = cutlass.Float32(0.0)
            if tidx < valid_len:
                g_value = cutlass.Float32(
                    g_cumulative[head_idx, tok_offset + tidx]
                )
            s_g[tidx] = g_value
        cute.arch.sync_threads()

        if cutlass.const_expr(self.causal_qk_schedule):
            if tidx < cutlass.Int32(128):
                self.causal_qk_main(
                    s_q,
                    s_k,
                    s_qk,
                    s_g,
                    scale,
                    valid_len,
                    tidx,
                )
        elif tidx < cutlass.Int32(128):
            qk_mma = cute.make_tiled_mma(
                warp.MmaF16BF16Op(self.dtype, self.acc_dtype, (16, 8, 16)),
                cute.make_layout((4, 1, 1)),
                permutation_mnk=(BT, BT, D),
            )
            qk_thr = qk_mma.get_slice(tidx)
            q_operand = self.load_a_aligned(
                s_q, qk_mma, tidx, (BT, D), False
            )
            k_operand = self.load_b_aligned(
                s_k, qk_mma, tidx, (BT, D), False
            )
            qk = qk_thr.make_fragment_C(qk_thr.partition_shape_C((BT, BT)))
            qk.fill(self.acc_dtype(0.0))
            cute.gemm(qk_mma, qk, q_operand, k_operand, qk)
            qk_coordinates = qk_thr.partition_C(
                cute.make_identity_tensor((BT, BT))
            )
            for item in cutlass.range(cute.size(qk), unroll_full=True):
                row, col = qk_coordinates[item]
                value = cutlass.Float32(0.0)
                if row < valid_len and col < valid_len and col <= row:
                    value = (
                        cutlass.Float32(qk[item])
                        * cute.math.exp(
                            cutlass.Float32(s_g[row])
                            - cutlass.Float32(s_g[col]),
                            fastmath=True,
                        )
                        * scale
                    )
                qk[item] = value
            self.store_qk(qk, s_qk, qk_mma, tidx)
        cute.arch.sync_threads()

        if chunk_idx > 0:
            if tidx < cutlass.Int32(BT):
                s_g[tidx] = (
                    cute.math.exp(cutlass.Float32(s_g[tidx]), fastmath=True)
                    * scale
                )
            cute.arch.sync_threads()

        o1_mma = cute.make_tiled_mma(
            warp.MmaF16BF16Op(self.dtype, self.acc_dtype, (16, 8, 16)),
            cute.make_layout((8, 1, 1)),
            permutation_mnk=(D, BT, D),
        )
        o1_thr = o1_mma.get_slice(tidx)
        output = o1_thr.make_fragment_C(o1_thr.partition_shape_C((D, BT)))
        output.fill(self.acc_dtype(0.0))
        if chunk_idx > 0:
            h_operand = cute.make_rmem_tensor(
                o1_thr.partition_shape_A((D, D)), self.dtype
            )
            h_coordinates = o1_thr.partition_A(
                cute.make_identity_tensor((D, D))
            )
            for item in cutlass.range(cute.size(h_operand), unroll_full=True):
                value_idx, key_idx = h_coordinates[item]
                # Native S2 H-CTA-major physical ABI.  This changes only the
                # address map; it does not introduce a transpose/copy kernel.
                value_group = value_idx // cutlass.Int32(16)
                value_lane = value_idx % cutlass.Int32(16)
                key_half = key_idx // cutlass.Int32(64)
                key_lane = key_idx % cutlass.Int32(64)
                h_operand[item] = g_h[
                    key_half,
                    key_lane,
                    value_lane,
                    chunk_idx,
                    value_group,
                    head_idx,
                ]
            q_operand_o = self.load_b_aligned(
                s_q, o1_mma, tidx, (BT, D), False
            )
            cute.gemm(o1_mma, output, h_operand, q_operand_o, output)
            output_coordinates = o1_thr.partition_C(
                cute.make_identity_tensor((D, BT))
            )
            for item in cutlass.range(cute.size(output), unroll_full=True):
                _, row = output_coordinates[item]
                output[item] = (
                    cutlass.Float32(output[item])
                    * cutlass.Float32(s_g[row])
                )

        if cutlass.const_expr(self.causal_scorev_schedule):
            self.causal_score_v_accumulate(
                output,
                s_v,
                s_qk,
                valid_len,
                tidx,
            )
        else:
            o2_mma = cute.make_tiled_mma(
                warp.MmaF16BF16Op(
                    self.dtype, self.acc_dtype, (16, 8, 16)
                ),
                cute.make_layout((8, 1, 1)),
                permutation_mnk=(D, BT, BT),
            )
            v_operand = self.load_a_aligned(
                s_v, o2_mma, tidx, (D, BT), True
            )
            qk_operand = self.load_b_aligned(
                s_qk, o2_mma, tidx, (BT, BT), False
            )
            cute.gemm(o2_mma, output, v_operand, qk_operand, output)
        # s_o aliases s_q.  Do not let an early warp overwrite Q while a late
        # warp still has an outstanding LDSM for the q@h operand.
        cute.arch.sync_threads()
        self.store_output_bf16(output, s_o, o1_mma, tidx)
        cute.arch.sync_threads()
        self.raw_output_epilogue(
            s_o,
            g_raw_o,
            tok_offset,
            valid_len,
            head_idx,
            tidx,
        )
