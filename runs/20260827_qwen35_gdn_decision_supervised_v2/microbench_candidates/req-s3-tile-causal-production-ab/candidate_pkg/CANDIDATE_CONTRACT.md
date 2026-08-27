# C1 source admission contract

- `C0` specializes `causal_tile_schedule=False`; its S3 body retains the
  frozen full `64x64` QK and score-times-V paths.
- `C1` specializes `causal_tile_schedule=True`; four QK row warps issue only
  causal `16x16` pairs and eight output warps accumulate the same score-times-V
  K tiles in ascending order.
- The state GEMM, shared BF16 score boundary, BF16 raw-output boundary, grid,
  block, S01, S2, post and four-kernel ABI are not changed.
- The `assert output.layout == output_tiles_layout` statement is a compile-time
  admission gate for a layout-only accumulator view. If it fails, no scan/copy,
  shared roundtrip, QK-only fallback or state-GEMM retile is allowed. The
  experiment must enter `AWAITING_SUPERVISOR_REVIEW`.
- For a full chunk, the only scheduled token-tile pairs are `(0,0)`, `(1,0)`,
  `(1,1)`, `(2,0)`, `(2,1)`, `(2,2)`, `(3,0)`, `(3,1)`, `(3,2)`, `(3,3)`.
  The S404 tail has `valid_len=20`, so it issues exactly `(0,0)`, `(1,0)`,
  `(1,1)`; element masking remains active inside diagonal and tail tiles.
