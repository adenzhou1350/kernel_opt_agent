# Native TileLang reshape layout counterexample

An owner-reviewed reproduction of an existing author's
[TileLang #3339](https://github.com/tile-ai/tilelang/pull/3339), not a new defect
claim or competing PR. Equal logical bit counts do not prove a buffer view can
be rebuilt with the same data pointer: offsets and physical strides also matter.
The tests call the selected complete `tilelang/language/customize.py` module with
real native TVM/TIRx Buffer objects. They do not rewrite reshape or mock TVM.

Use an already compatible task-private TileLang/TVM, Torch and pytest runtime on
an authorized worker. Dependency setup is separate; this example installs
nothing. Export **raw Git-blob bytes**, not Windows CRLF working-tree bytes:

| Arm | Source revision | customize.py SHA256 |
| --- | --- | --- |
| Baseline | `7a8ded9f1d91b0693fa82467656311947cfd8922` | `b3b716ac33b028a6b76677c6dbe855af5db0444eb475ba5e033a3d8af60da013` |
| Existing author's repair | `cdc407ae84fa5b9bb4a1cfd2e2ded4f96831b58c` | `965583cd4dfe835d5495cb434b9044894ddf7a3ad18d3ce510f22bbf95bef4d0` |

Keep one arm's export as `reviewed_customize.py` in each private test directory.
Copy the same reviewed test bytes into both as `test_reshape_layout.py`. Start a
fresh process for each arm; never mutate the dependency installation. For one
arm, this POSIX command uses the existing native capture tool:

```sh
# Set ARM_ROOT, ARM_SHA, TEST_SHA, CAPTURE_ROOT, RESULT_ROOT, PYTHON and
# NATIVE_RUNTIME to reviewed absolute paths/hashes for this invocation.
python3 -B "$CAPTURE_ROOT/scripts/scout_native_run.py" \
  --cwd "$ARM_ROOT" --output "$RESULT_ROOT" --timeout 60 \
  --format pytest-junit \
  --source "reviewed_customize.py=$ARM_SHA" \
  --source "test_reshape_layout.py=$TEST_SHA" \
  --env "PYTHONPATH=$NATIVE_RUNTIME" --env PYTHONDONTWRITEBYTECODE=1 \
  --env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  --env "TILELANG_CUSTOMIZE_SOURCE=$ARM_ROOT/reviewed_customize.py" \
  --env "TILELANG_CUSTOMIZE_SHA256=$ARM_SHA" \
  --expect-test test_reshape_layout::test_implicit_compact \
  --expect-test test_reshape_layout::test_explicit_compact \
  --expect-test test_reshape_layout::test_singleton_stride \
  --expect-test test_reshape_layout::test_nonzero_offset \
  --expect-test test_reshape_layout::test_symbolic_offset \
  --expect-test test_reshape_layout::test_noncompact_stride \
  --expect-test test_reshape_layout::test_bits_mismatch \
  -- "$PYTHON" -B -m pytest test_reshape_layout.py -q -s -p no:cacheprovider
```

CUDA is hidden by the capture tool; the fixture also checks that Torch never
initializes CUDA. The baseline should have three assertion failures (offset,
symbolic offset, noncompact stride) and four passing controls. The peer should
pass all seven. Preserve the baseline's nonzero exit/report; it is intentional
discrimination, not successful CI. Missing dependencies or a wrong source hash
produce setup errors, not bug reproduction. Use `compare_regression` from
`scout_native_results.py` on the two saved JUnit reports with these three named
regressions and four controls; require the entire selected pattern.

The module keeps TileLang's real package context for relative imports. Its other
Python modules and native libraries come from the observed runtime (the initial
replay used TileLang 0.1.15/TVM on Python 3.12), **not an exact full build of either
source revision**. Provenance paths/versions are captured in the private log.
This supports adapted native frontend layout discrimination only, not full-stack
compatibility, GPU numerics, performance, PR readiness or evidence-selector
utility. The capture tool is not a sandbox: do not feed it unreviewed Scout code.
