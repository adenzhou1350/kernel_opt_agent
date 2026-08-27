"""CuTe compiler/type proof for the N2 accumulator N16 same-iterator view.

The compiled callable contains a launch site because CuTe must lower register
fragments inside device scope.  The experiment never invokes that callable;
`cute.compile` alone evaluates the layout assertions and emits proof artifacts.
"""

from __future__ import annotations

import cutlass
import cutlass.cute as cute
from cutlass.cute.nvgpu import warp


D = 128
BT = 64
N_TILE = 16
THREADS = 256


class N2AccumulatorLayoutProof:
    def __init__(self):
        self.dtype = cutlass.BFloat16
        self.acc_dtype = cutlass.Float32

    @cute.jit
    def _prove_exact_path(self, tidx: cutlass.Int32):
        # Exact production O1 construction used by both short and long S3.
        o1_mma = cute.make_tiled_mma(
            warp.MmaF16BF16Op(self.dtype, self.acc_dtype, (16, 8, 16)),
            cute.make_layout((8, 1, 1)),
            permutation_mnk=(D, BT, D),
        )
        o1_thr = o1_mma.get_slice(tidx)
        output = o1_thr.make_fragment_C(o1_thr.partition_shape_C((D, BT)))

        # N2 scoreV keeps the same eight-warp M ownership and changes only the
        # logical N extent from 64 to 16.  K=16 does not affect C ownership.
        scorev_mma = cute.make_tiled_mma(
            warp.MmaF16BF16Op(self.dtype, self.acc_dtype, (16, 8, 16)),
            cute.make_layout((8, 1, 1)),
            permutation_mnk=(D, N_TILE, N_TILE),
        )
        scorev_thr = scorev_mma.get_slice(tidx)
        prototype = scorev_thr.make_fragment_C(
            scorev_thr.partition_shape_C((D, N_TILE))
        )

        # Split the real per-thread MMA_N mode into two N8 atoms per N16 tile
        # and four tiles.  The tensor is built from output.iterator: no new
        # fragment, register storage, copy or memory handoff is introduced.
        divided_layout = cute.logical_divide(output.layout, (None, None, 2))
        output_divided = cute.make_tensor(output.iterator, divided_layout)

        assert cute.size(output) == 32
        assert cute.cosize(output.layout) == 32
        assert cute.size(prototype) == 8
        assert cute.cosize(prototype.layout) == 8
        assert cute.size(output_divided) == cute.size(output)
        assert cute.cosize(output_divided.layout) == cute.cosize(output.layout)

        for row_tile in cutlass.range_constexpr(BT // N_TILE):
            tile = output_divided[None, None, (None, row_tile)]
            assert tile.layout == prototype.layout
            assert cute.size(tile) == cute.size(prototype)
            assert cute.cosize(tile.layout) == cute.cosize(prototype.layout)

        # Negative control: the rejected design appended four independent
        # single-warp fragments.  Its layout must remain unequal to the real
        # eight-warp O1 fragment; otherwise this probe is not discriminating.
        legacy_mma = cute.make_tiled_mma(
            warp.MmaF16BF16Op(self.dtype, self.acc_dtype, (16, 8, 16)),
            cute.make_layout((1, 1, 1)),
            permutation_mnk=(N_TILE, N_TILE, N_TILE),
        )
        legacy_thr = legacy_mma.get_slice(tidx % cutlass.Int32(32))
        legacy_fragment = legacy_thr.make_fragment_C(
            legacy_thr.partition_shape_C((N_TILE, N_TILE))
        )
        legacy_appended = cute.append(
            legacy_fragment.layout,
            cute.make_layout(
                (BT // N_TILE,),
                stride=(cute.cosize(legacy_fragment.layout),),
            ),
        )
        assert output.layout != legacy_appended

    @cute.kernel
    def kernel(self):
        tidx, _, _ = cute.arch.thread_idx()
        # Independent instantiations bind both production dispatch paths.  The
        # static audit separately hash-binds and checks their source constructors.
        self._prove_exact_path(tidx)  # short path
        self._prove_exact_path(tidx)  # long path

    @cute.jit
    def __call__(self):
        self.kernel().launch(
            grid=(1, 1, 1),
            block=(THREADS, 1, 1),
            max_number_threads=(THREADS, 1, 1),
            min_blocks_per_mp=1,
        )


__all__ = ["N2AccumulatorLayoutProof", "D", "BT", "N_TILE", "THREADS"]
