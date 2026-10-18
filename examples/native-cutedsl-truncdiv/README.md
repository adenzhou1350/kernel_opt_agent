# Native integer semantics before a full compiler build

This is an exposed development witness, not a discovery or selector benchmark.
It executes a **reviewed** full Python mathematics module and real Cutlass MLIR
operations. It does not build/import the TileLang parent package, run registered
pytest, execute a GPU, or reproduce the author's complete compiler qualification.
Do not run an arbitrary model-generated source file with this loader.

Use the raw Git blob of `tilelang/contrib/cutedsl/math.py` from author-owned
[TileLang PR #3551, head 064d8582](https://github.com/tile-ai/tilelang/blob/064d8582d723b0e680dff73d332880ba1199661c/tilelang/contrib/cutedsl/math.py).
Export it with the existing commit-exact source bundler and record its SHA256.
Use a reviewed compatible Linux environment with Cutlass DSL **4.7.1**, Torch
and the actual selected dependencies. Keep installs, HOME, temporary files and
caches task-private; a successful `--no-deps` install is not dependency validation.
No download/install, credentials, remote host or queue is managed by this example.

With an official pip `--target` Cutlass installation, check its `.pth` file's
literal path entry: the observed package also needs
`native/nvidia_cutlass_dsl/dsl_packages` on the import path. Verify the actual
`cutlass.__file__` stays inside the intended target rather than falling back to
an older system package. Do not copy this path convention to an uninspected wheel.

Run in a fresh reviewed CPU process, with the site's normal time/resource bounds:

```sh
CUDA_VISIBLE_DEVICES='' PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 \
  python -B check.py --reviewed-source RAW_MATH_MODULE --sha256 RAW_SHA256
```

The check uses `int(Fraction(a, b))` as an exact scalar reference, including
signed extrema and divisors of both signs. It compares the literal helper and
MLIR constant-folded helper with that reference for 32 cases across int8/16/32/64;
four dynamic IR functions must emit `arith.divsi`. Direct Cutlass `//` is a
contrasting floor-division operator, **not** an execution of old TileLang codegen.
The author's pinned helper passed all 32 cases; `//` disagreed on 16. This is one
known repair, not 16 discoveries. Native IR verification/folding does not prove
target-device lowering or runtime numerical behavior.

Exclude division by zero and signed-minimum divided by -1, whose behavior is
outside [MLIR `arith.divsi`'s defined contract](https://mlir.llvm.org/docs/Dialects/ArithOps/#arithdivsi-arithdivsiop).
The TensorSSA/vector branch, broadcasting/shape compatibility, full compiler,
GPU, sanitizer, supported-platform matrix and performance remain untested here.
Do not use this scalar witness to dismiss the existing vector-shape review.

One explicit development mutation changed only the typed scalar helper's
`arith.divsi` to `arith.floordivsi`, leaving its plain-Python literal branch
correct. The witness rejected it at `-7 / 3` (`-3` instead of `-2`) with a nonzero
exit and no success report. This demonstrates why literal-only tests are
insufficient; the mutation is not an upstream revision or another discovery.

The source hash is checked before and after loading. Output records actual
runtime paths/versions, rows and wall time; it is not a new native-run report
format, readiness decision or execution authorization. Retain errors as errors,
not empty successes. Setup/download, owner review and model costs are separate.
The original scoped validation was acknowledged by the author in #3551; support
that author's repair rather than opening a competing PR. Such collaboration is
not an additional own PR, a new prospective case or evidence of routing efficacy.
