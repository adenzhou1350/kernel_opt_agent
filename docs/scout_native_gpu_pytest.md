# Owner-reviewed native GPU pytest

Use the repository's actual package and registered pytest tests, rather than
copying one function into a synthetic module. This optional Linux tool is for
already reviewed, trusted code on an authorized worker. It does not execute
unreviewed Scout queue entries, provision dependencies, connect over SSH, publish
PRs or replace a disposable sandbox. The ordinary native runner CLI remains
CPU-only; no local WSL is needed.

Export complete source trees with Linux LF Git-blob bytes, verify the source/test
exports, and use the same environment and regression test bytes in both arms.
Run each arm in a fresh process/output directory. List the affected implementation,
regression tests and requested import files with their reviewed SHA256 hashes.
The import check happens in the same process before pytest: every requested module
must resolve inside that checkout and match a listed source digest.

```sh
python scripts/scout_native_gpu_run.py \
  --cwd /task/candidate --output /task/candidate-native-result \
  --python /task/venv/bin/python \
  --gpu-uuid GPU-00000000-0000-0000-0000-000000000000 \
  --lock-dir /site/existing-gpu-allocator \
  --source package/layer.py=REVIEWED_SHA256 \
  --source tests/test_layer.py=REVIEWED_SHA256 \
  --import-from-checkout package.layer \
  --expect-test tests.test_layer::test_regression \
  --timeout 600 --memory-mib 4096 \
  -- -q tests/test_layer.py -p no:cacheprovider
```

Use the site's **same existing allocator directory and full-UUID lock filename**,
not a new per-task lock domain. Cooperating owners retain the lock inode. The
existing GPU helper checks three live samples, at least 6 GiB free and at most
80% utilization; sharing is allowed, no inventory process is signalled. The child
must observe exactly the selected CUDA UUID. Native command cleanup only signals
its own process group. An uncertain postflight or a new surviving GPU process
makes the result inconclusive, never permission to stop another task.

The tool sets a maximum 4 GiB **Torch allocator** budget, not a hard limit for
Triton/direct CUDA/external allocations. Review tensor sizes, external allocators,
side effects and parallel/distributed launches before use. Larger model workloads
need a separately appropriate resource policy, not a bypass of this small test
route. Task-local compilation caches are fresh; cold compilation is included in
the command's wall timeout and wall accounting. Wall time is not GPU active time
or a valid shared-card performance measurement.

Outputs reuse `terminal.log`, owned `junit.xml` and `result.json`. Exact expected
JUnit case identities must execute; skips, setup errors, signals, truncated logs,
changed selected source/tool bytes and abnormal exits cannot qualify a pass.
The added GPU record captures device mapping, imported module paths/digests and
pre/post inventory. It does not prove the whole dependency closure, every
transitive import, a semantically adequate oracle, actual kernels in every test,
performance improvement or upstream readiness. Inspect before/after results and
the target repository's contribution rules before publication.

## Observed integration control

A native RTX 5090 replay used FLA baseline
`b8ff848705a8f7685770273452f2c8d8dcf40621` and the same six registered regressions
as [FLA #1333](https://github.com/fla-org/flash-linear-attention/pull/1333), candidate
`cf1b0c5829166464c3ae6c3ac26a19081f7a2fd7`. With Python 3.12, Torch 2.11.0+cu130
and Triton 3.6.0, the tool retained **2 failures / 4 passes** before the repair
and **6 passes** after it. Both in-process source/device checks and postflight
observations passed. Separate cold compilation caches were used; the combined
controller invocation took about 263 seconds, including both runs and checks.
This is an exposed positive integration control for the runner, not another PR,
cross-framework validation, a performance comparison or a prospective cost/yield
experiment. Broader FLA qualification is recorded on that PR separately.
