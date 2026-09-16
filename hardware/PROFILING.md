# Hardware-aware optimization, without a new workflow bureaucracy

The useful target is a **conditional performance envelope**, not a universal
score for a card. A workload fixes precision, numerical requirements, shapes,
layout, algorithm freedom and execution mode. An architecture names resources;
it does not by itself supply their attainable rates for that workload.

## Start with discovery

```sh
python scripts/kernel_opt.py hardware-profile inspect --output runs/device-profile.json
```

This new command only queries NVIDIA management metadata and locates installed
tools. It does not import Torch, initialize a CUDA workload, compile a device
query, install dependencies, change clocks or connect to remote machines. It
works without a GPU framework; unavailable driver fields stay unknown. It uses
reported device indices and UUIDs, not row order. Inventory is neither a
calibration nor permission to run on an apparently idle GPU. An unsupported
vendor reports unavailable; AMD/Intel adapters are not implemented yet.

The older `hardware-discover` tool can compile its CUDA device-property helper.
Use it deliberately when richer register/shared-memory/cache properties are
needed and compilation is appropriate, not as a default passive inventory.

## Calibrate only what can change the next decision

1. Inspect devices and existing runtimes before installing anything. Reuse a
   compatible runtime; otherwise use a task-private environment and build cache.
   Group compatible driver/runtime/architecture combinations, not one global
   environment for every framework or a new environment for every operator.
2. On an authorized, freshly idle device with coordinated allocation, measure a
   small relevant portfolio: bandwidth vs working-set size, precision/shape-
   matched GEMM, reductions, or launch/dependency latency. Do not run an exhaustive
   instruction suite merely because a device is new.
3. Retain warmup and repeated raw samples, output checks, working-set/cache state,
   launch geometry, eager/graph mode, software versions and power/clock/load
   observations. A cache-resident copy rate is not DRAM bandwidth; GEMM FLOP/s is
   not a universal compute ceiling. Do not label logical read+write bytes as
   measured DRAM transactions without evidence at that boundary.
4. Fit shape/size-conditioned service curves using `service-curve-fit` when useful.
   They are empirical references, not physical limits. Recheck a small canary
   after runtime, power, clock or device changes before reusing cached results.
5. Map the real model's reached operator shapes onto these references. Prioritize
   the largest plausible whole-workload improvement, implement one hypothesis,
   and compare paired correct production runs. An optimization can change the
   bottleneck: update the model rather than blindly accumulating speedups.

This is the measurement procedure, not an implemented multi-vendor automatic
calibration/install service. `hardware-profile` never launches these probes.
Use existing relevant probes and the selected framework's normal benchmark;
introduce a new probe only for a specific unresolved decision.

## Calculate a small resource-gap report

```sh
python scripts/kernel_opt.py hardware-profile estimate \
  --model hardware/examples/resource-gap.json
```

The example is synthetic, not a card profile. It yields a conditional 10 us
lower bound, a separate 12.5 us empirical resource reference, and an 11 us
illustrative observation. The remaining speedup ceiling is 1.10x **only under
the supplied bound assumptions**. Observing 9 us instead invalidates the model
comparison, rather than proving a result above physics. Output files, if
requested with `--output`, must be fresh so prior evidence is never replaced.

For each resource, `minimum_work` and `upper_rate_per_second` form a conditional
time lower bound. State their basis explicitly: mandatory work for the permitted
algorithm family, capacity from applicable official evidence, dtype, dense vs
sparse, and clocks. Missing work or capacity produces an unknown, not zero.
Only supply a capacity as an upper rate when that claim is justified: advertised
nominal-clock throughput is not an unconditional bound under boost clocks.

`reference_work` and `measured_rate_per_second` separately estimate resource
service time for a matched implementation. `measurement_basis` should identify
raw samples, environment/device snapshot and reproduction command. The tool
does not fetch or verify those references. Keep traffic units per boundary and
count FLOP consistently (a scalar FMA contributes two FLOP).

Independent resource constraints combine by maximum. Supply any stronger
mandatory serial-path constraint as `dependency_lower_us` with `dependency_basis`;
do not sum mutually overlapping compute/memory time, or assume a maximum proves
an executable schedule. Latency, cache, occupancy, issue, contention and missing
resource constraints can leave substantial unexplained time. The report is
conditional arithmetic, never an automatic certificate, PR decision or proof
that the given implementation is optimal. For deeper conditional-bound research,
see the existing optional performance-limit tools.

## Keep reusable knowledge, not a machine-status archive

Keep raw profiles, UUIDs, host access details and environment logs local. Publish
sanitized reproducible calibration examples and scoped lessons that change a
future decision. Search `knowledge` before contributing. A response curve needs
its shape/precision/cache/runtime conditions and failures, not just a peak score.

References: [NVIDIA management queries](https://docs.nvidia.com/deploy/nvidia-smi/),
[Nsight Compute resource and Roofline analysis](https://docs.nvidia.com/nsight-compute/ProfilingGuide/).
