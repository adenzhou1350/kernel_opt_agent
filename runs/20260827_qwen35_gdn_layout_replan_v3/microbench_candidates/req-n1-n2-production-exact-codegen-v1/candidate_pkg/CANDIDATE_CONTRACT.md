# N1/N2 production-exact codegen candidates

This source package changes only the S3 causal 16x16 tile schedule.  It does
not authorize a numerical or performance conclusion.

- `C0`: frozen dense production S3 reference.
- `C1` / `N1_QK_ONLY`: four QK row warps issue the ten lower-triangular N16
  tiles per full chunk.  The dense production score-times-V path is unchanged.
  All six upper N16 score tiles are nevertheless published as explicit BF16
  zeros, so the dense consumer reads a completely defined 64x64 matrix.
- `C2` / `N2_DIRECT_VIEW`: C1 plus causal score-times-V.  The production
  eight-warp O1 accumulator remains live and is exposed as four N16 C/D views
using `cute.logical_divide` over the same backing iterator.

The long-S kernel preserves its registered 49,408-byte shared-memory layout:
K and score still alias.  Its four QK warps therefore keep four rounded BF16
score fragments in registers, execute one convergent 128-thread named barrier
after the final K read, and only then publish score with STMatrix.  The barrier
is a necessary alias-lifetime edge and must be present in final SASS.  E0 must
reject either candidate if this live range exceeds the registered resource or
CTA-residency cap.

For C2 the K-tile loop is outermost.  Each V K-tile is loaded from shared
memory once and reused for every legal output N-tile, while each output sees K
tiles in the original ascending order.  A one-warp `cute.append`, fragment
copy, permutation, shared/global roundtrip, repeated per-output V load, state
GEMM retile, changed BF16 boundary, extra kernel, or fusion is forbidden.

The run-local files use hash-bound absolute imports for the production
`custom_compile_cache` and `varlen_helper` dependencies.  No implicit package
path extension is permitted; E0 must seal the resolved module origins and
hashes before compilation and verify them again afterward.

This package is admissible for execution only after its exact hashes are bound
to `req-n1-n2-production-exact-codegen-v1` and the supervisor approves the
zero-launch compile/SASS/resource experiment.
