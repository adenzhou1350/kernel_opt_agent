# TIRx integration pilot — 2026-09-30

Status: an optional CPU backend is implemented and tested, with a same-source GPU
handoff and a bounded multi-workload performance study. It is available to a
capable agent via `python scripts/kernel_opt.py tirx`. Existing Scout, SemIf,
resource allocation and delivery services were not changed. It is not yet an
automatic production route or a completed agent-system A/B.

## What is combined

- Existing task discovery, workload selection, knowledge/worklog and delivery.
- TIRx NumSim, Synccheck and Racecheck, with explicit numerical references,
  source identity, package versions, diagnostic details and bounded execution.
- Complete reusable affine examples, including CPU-only numerical, race and
  barrier-error controls, plus a source-bound GPU check.
- A multi-shape GEMM study using the official event timer, identical operand
  storage per comparison, randomized implementation order and raw pairs.
  Candidate selection remains specific to shape/dtype/hardware; cuBLAS is retained.

## Verified

Local tests: 30 passed, 1 platform-specific skipped, 46 subtests passed for the
adapter and existing worklog/knowledge tools. Public CLI section check passed.
The skip is an existing knowledge-notes symlink test (symlink creation is
unavailable on this Windows host), not a TIRx check.

On the private B300 SM10.3 environment (Harness/Kernel Zoo 0.1.2, TVM 0.27.0):

- Affine CPU numerical, sync and race checks passed.
- All three deliberate bad cases failed with the expected numerical,
  `data_race`, or `mbarrier_use_before_init` finding. Bad cases were kept off GPU.
- The same affine source SHA256 passed a real GPU test with exact FP32 output.
- CPU case elapsed time was 197.61 seconds on the initial private-cache build,
  then 0.247 seconds with the same cache. This is case execution time, excluding
  Python/TVM import overhead; do not infer total agent latency or general savings.
- FP16 1024/2048/4096 square and BF16 1024 square GEMMs passed three data seeds
  and post-benchmark output checks under rtol=0.001, atol=0.01.

Seven randomized pairs per case, 10ms warmup, 30ms repeat and 0.1s cooldown per
implementation, official event timer, warm repeated operands:

| Workload | TIRx default median μs | cuBLAS median μs | cuBLAS/TIRx |
| --- | ---: | ---: | ---: |
| FP16 1024³ | 11.543 | 10.597 | 0.918 |
| FP16 2048³ | 19.845 | 19.583 | 0.987 |
| FP16 4096³ | 94.127 | 90.180 | 0.958 |
| BF16 1024³ | 11.608 | 10.630 | 0.916 |

All paired median-delta bootstrap intervals were above zero in this study
(negative delta would favor TIRx). These are conditional warm-kernel measurements
on a shared node, not cold-cache, whole-model or cross-system rankings. This
protocol differs from the earlier installation probe, so their values should not
be pooled. A single exploratory FP16 1024 variant (`cta_n=128`, `pipe_depth=4`)
passed correctness but measured 12.209μs; reject it for this measured workload.
No installed library file or global configuration was changed.

## Evidence and reproduction

Raw local evidence: `D:\codes\community-validation\tirx-harness-gzb-20260930\integration-evidence\`
and `integration-gpu-study.json`; the original installation probe is in the same
parent directory. Private remote environment and source copies:
`/tmp/tirx-feasibility-20260930-01a0f10d/integration-20260930`.
The local experiment notebook is `runs/tirx-integration-20260930`.
Remote address and UUID stay in private experiment records, not portable lessons.

Use [backend instructions](tirx_backend.md) for CPU checks. GPU examples require
an already coordinated allocation, EXPECTED_GPU_UUID, matching
CUDA_VISIBLE_DEVICES, and TIRX_PREPARE_CUDA_ARCH=sm_103a. `affine_device.py`
consumes a current passing CPU result bound to the exact example source;
`gemm_study.py` records its source/library hashes and raw measurements. Invoke
them with an outer timeout and private environment/cache. They do not allocate
or decide whether a shared GPU is idle. The private `integration.sh` handles the
live check and shared lock for this experiment. Do not use historical availability.

## Continuing work

A heartbeat attached to the research chat continues every six hours. It should
advance a new useful experiment or affected regression, avoid duplicate work and
remain quiet when there is no meaningful result. Shared GPUs must be checked and
coordinated each time. Each GPU experiment is bounded to ten minutes; each CPU
batch to five minutes. The tested GPU was released and returned to 0MiB/0%.

Next useful steps:

1. Validate held-out numerical and synchronization patterns; identify modeled
   operation limits with small reproducible counterexamples.
2. Choose one actual project operator, preserve its production contract and
   compare the existing route with the combined route at the same model/budget.
   Record real tokens, time to correct result, GPU usage and final performance.
3. Use successful complete kernels as applicability-qualified implementation
   assets. Retain better existing backends rather than promoting TIRx by default.
4. Before shared KCoral deployment, separately qualify its dependency stack,
   allocation interface, profiler access and filesystem isolation. The existing
   loopback trusted-script smoke test does not establish these properties.

No full attention suite, production route, autonomous tuning campaign, NCU/IKET,
or system-level productivity improvement has been established. Proton/CUPTI
remains unavailable in this environment; the event timer is the verified path.

## Follow-up advantage ablation

A bounded FP32 affine+ReLU study compared the same five safe synthetic candidates
(four numerical defects and one valid implementation) on CPU and GPU. Three
repeats per route found that a separate CPU worker plus GPU worker took median
9.18s versus 7.06s for direct GPU validation: the current split-process interface
is not automatically a speedup. Both rejected all defects and retained the valid
candidate. The deliberately high defect ratio is not a production estimate.

A follow-up prototype reused imports in one process and used CPU compilation
before allocation in **both** routes. With existing candidate caches, medians
were 5.74s with prechecks versus 6.75s direct, and allocated GPU-stage time was
0.361s versus 0.458s. GPU candidate launches fell from five to one. First-time
CPU candidate materialization cost 31.79s despite a previously built native
engine, so these warm-case results do not justify checking every new kernel.
The single-process route is an experiment, not an implemented production worker.

Kernel measurements at four sizes with three seeds and seven randomized pairs
showed tiled TIRx roughly matching fused Triton. At 1,048,576 elements, Torch's
three-op chain took 13.08us, Triton 9.13us, TIRx naive 23.56us and TIRx tiled
9.20us. Fusion helped both backends; TIRx did not establish broad superiority.

Private report and raw evidence:
`D:\codes\community-validation\tirx-harness-gzb-20260930\advantage-study\README.md`.
Use prechecks selectively, prepare before allocating GPU, and reuse worker
imports/caches when useful. A real model-generated candidate search with matched
budget and measured tokens remains necessary for a system-level conclusion.

## Current-source audit

The `c3f3c98` snapshot includes `3e7a33a`: exact integer/bool comparisons and
explicit NumSim coverage verdicts. The current adapter's 21 regression tests and
the public CLI section check passed. Actual native NumSim execution reproduced
an old false PASS for int64 outputs near `2**60` with a +1 error; the current
adapter returned FAIL with exact error 1. Correct int64 and affine cases passed;
numerical, race and barrier negative controls failed as expected. The public
`kernel_opt.py tirx check` route also returned the expected codes and retained
source hashes. Native coverage-review cases were not exercised in this audit;
that change has unit-test coverage.

Using the current adapter in the same CPU-prepared single-process prototype,
three interleaved repeats per arm found 6.933s direct versus 6.592s with prechecks
for four safe numerical defects plus one valid candidate. Launches fell 5 to 1.
For one valid candidate, times were 4.375s direct versus 4.754s with prechecks.
These are warm-cache synthetic queues, not measured production error rates or
model-generated search. The roughly 5% mixed-queue time reduction is not a stable
speedup estimate: total-time ranges overlap and CUDA initialization varies.
Mixed-queue allocated GPU-stage medians increased from 0.704s to 1.178s despite
fewer launches. The earlier time/reservation savings did not reliably reproduce.
No final-kernel changes or new kernel-performance claim accompany this audit.

Current source inspection still finds no automatic TIRx invocation in Scout or
SemIf. Selective CPU checks are useful capabilities; default full checking and
overall agent superiority remain unsupported. Private current-source report:
`D:\codes\community-validation\tirx-harness-gzb-20260930\current-audit\README.md`.
