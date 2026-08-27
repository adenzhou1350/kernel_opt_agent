"""Production short-S S3 raw main consuming S01 packed K_INTER directly."""

from __future__ import annotations

import cutlass
import cutlass.cute as cute
from cutlass.cute.nvgpu import warp, warpgroup

from .custom_compile_cache import (
    KeyedCompileMixin,
)


BT = 64
D = 128
THREADS = 512
MAIN_THREADS = 256
EPILOGUE_WARPS = 16


class S3PackedEpiW16RawKernelSm120(KeyedCompileMixin):
    def __init__(self, dtype, cu_seqlens_dtype):
        self.dtype = dtype
        self.acc_dtype = cutlass.Float32
        self.cu_seqlens_dtype = cu_seqlens_dtype
        self.manual_cache_key("dtype", "cu_seqlens_dtype")

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
        for row_iter in cutlass.range_constexpr(BT // EPILOGUE_WARPS):
            row = warp_idx + cutlass.Int32(row_iter * EPILOGUE_WARPS)
            if row < valid_len:
                token_idx = tok_offset + row
                for item in cutlass.range_constexpr(D // 32):
                    d_idx = lane + cutlass.Int32(item * 32)
                    value = cutlass.Float32(s_o[d_idx, row])
                    g_raw_o[d_idx, token_idx, head_idx] = self.dtype(value)

    @cute.jit
    def output_main(
        self,
        s_q: cute.Tensor,
        s_v: cute.Tensor,
        s_qk: cute.Tensor,
        s_o: cute.Tensor,
        s_g: cute.Tensor,
        g_h: cute.Tensor,
        scale: cutlass.Float32,
        head_idx: cutlass.Int32,
        chunk_idx: cutlass.Int32,
        tidx: cutlass.Int32,
    ):
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
                    * cute.math.exp(cutlass.Float32(s_g[row]), fastmath=True)
                    * scale
                )

        o2_mma = cute.make_tiled_mma(
            warp.MmaF16BF16Op(self.dtype, self.acc_dtype, (16, 8, 16)),
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
        self.store_output_bf16(output, s_o, o1_mma, tidx)

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
            smem_q: cute.struct.Align[
                cute.struct.MemRange[self.dtype, cute.cosize(qk_sd)], 128
            ]
            smem_k: cute.struct.Align[
                cute.struct.MemRange[self.dtype, cute.cosize(qk_sd)], 128
            ]
            smem_v: cute.struct.Align[
                cute.struct.MemRange[self.dtype, cute.cosize(qk_sd)], 128
            ]
            smem_qk: cute.struct.Align[
                cute.struct.MemRange[self.dtype, cute.cosize(score_layout)], 128
            ]
            smem_o: cute.struct.Align[
                cute.struct.MemRange[self.dtype, cute.cosize(o_layout)], 128
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
        s_q = storage.smem_q.get_tensor(qk_sd.outer, swizzle=qk_sd.inner)
        s_k = storage.smem_k.get_tensor(qk_sd.outer, swizzle=qk_sd.inner)
        s_k_physical = storage.smem_k.get_tensor(cute.make_layout(BT * D))
        s_v = storage.smem_v.get_tensor(qk_ds.outer, swizzle=qk_ds.inner)
        s_qk = storage.smem_qk.get_tensor(score_layout)
        s_o = storage.smem_o.get_tensor(o_layout.outer, swizzle=o_layout.inner)
        s_g = storage.smem_g.get_tensor(cute.make_layout(BT))

        # S01 and this shared tile use the identical K_INTER physical mapping.
        # Copy the 8192 BF16 values linearly/coalesced instead of unpacking
        # logical (row,d) coordinates and immediately swizzling them again.
        k_tile_base = (
            (chunk_idx * num_heads + head_idx)
            * cutlass.Int32(BT * D)
        )

        # A bounded unroll keeps the Q/K/V copy live range below the fully
        # unrolled form while retaining enough independent memory operations.
        for item in cutlass.range(
            (BT * D) // THREADS,
            unroll=4,
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

        if tidx < cutlass.Int32(128):
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

        if tidx < cutlass.Int32(MAIN_THREADS):
            self.output_main(
                s_q,
                s_v,
                s_qk,
                s_o,
                s_g,
                g_h,
                scale,
                head_idx,
                chunk_idx,
                tidx,
            )
        cute.arch.sync_threads()
        self.raw_output_epilogue(
            s_o,
            g_raw_o,
            tok_offset,
            valid_len,
            head_idx,
            tidx,
        )
