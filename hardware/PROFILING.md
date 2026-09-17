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

For a new NVIDIA device, opt into richer metadata and a portable handoff:

```sh
python scripts/kernel_opt.py hardware-profile inspect --cuda --topology \
  --output runs/new-card/profile.json
python scripts/kernel_opt.py hardware-profile handoff \
  --profile runs/new-card/profile.json --output runs/new-card/HARDWARE.md
```

On a multi-device host, add `--device GPU-<exact-UUID>` to `handoff`; never guess
from row order or a CUDA ordinal. Give a fresh agent **both `HARDWARE.md` and
`profile.json`**, plus the operator/model task. No previous chat is required.
Use `handoff --format json` for a programmatic consumer.

- `--cuda` uses the installed CUDA Driver API in a child process with a 10-second
  timeout. It initializes the driver but creates no context, allocation or
  kernel and does not compile or import Torch. It queries SM count, warp width,
  L2, shared-memory/register limits, thread/block limits, memory bus width,
  reported clocks and selected capability flags. Missing attributes remain null.
- `--topology` queries `nvidia-smi topo -m`, checking GPU index/UUID identities
  before and after. It reports GPU/NIC relationship labels and available CPU/NUMA
  affinities, not link throughput. NIC labels are not independently verified
  NIC identities. Unsupported Windows/container output remains unknown.
- Driver attributes join by UUID-v2 only. This is a reported device/instance,
  not proof of a full physical GPU; a legacy UUID or mismatched MIG identity
  cannot silently contribute physical-parent capacities. Virtualization and
  visibility restrictions may limit what can be observed.
- On Linux, `--cuda` also reads available proc/sysfs metadata: kernel UUID at
  the same PCI address, PCIe link speed/width and NUMA node, and RDMA port state
  and advertised rate. It records the loaded CUDA driver library path. A
  kernel/user-space UUID difference is a mapping question (for example a proxy
  or partition), not proof of a broken device. Keep the runtime observations,
  but resolve the mapping before calling them physical-card capacities.

The topology parser accepts color-only ANSI decoration and common mlx5/irdma
NIC names, preserves the raw output, and gives the matrix query up to 10 seconds
(identity queries stay bounded at 2 seconds). Unsupported terminal controls,
incomplete/asymmetric matrices, or NVLink labels on NIC edges fail closed to
unknown topology. No retry/install loop is needed to discover this limitation.
PCIe negotiated GT/s, NVLink labels and RDMA port Gb/s are not application
bandwidth and do not prove that a transport path is usable.

The older `hardware-discover` tool can compile its CUDA device-property helper;
it is not required for this first-layer handoff.

## What the first layer hands to the next layer

The brief separates three things: **queried capacities**, **supplied performance
evidence**, and **decision-dependent unknowns**. It includes a generic logical
resource hierarchy, but does not pretend to discover the physical SM-to-L2
wiring, slice arbitration, cache mapping/replacement policy, or every execution
unit's service rate. These are not all exposed by a vendor API.

The first layer is useful when a new agent can identify its target, cite where a
parameter came from, tell which quantities are still unknown, and select the
cheapest informative next experiment. Filling the capacity checklist does not
mean the chip is fully understood or an optimum has been established. No new
phase gate, approval document or mandatory exhaustive calibration is required.

For a numerical bound, the next layer must still establish the workload's
unavoidable work and applicable upper capacities. Obtain architecture-specific
instruction/precision information from official sources, and measure only the
relevant service curves and coupled-resource behavior. A theoretical bound is
conditional on the algorithm/numerical/clock assumptions; it is not necessarily
attainable. Measured best-known rates give useful targets, not physical proofs.

If these sources or calibrations already exist, `handoff --rates FILE` can carry
them forward. The JSON object binds `device_uuid` and `profile_sha256` and has a
`rates` list. Each entry contains:

- `resource`, positive `value`, and `unit` (`bytes/s`, `FLOP/s`, `instructions/s`,
  or `us` for an empirical latency).
- `kind`: `documented_upper` or `empirical_reference`.
- Nonempty `conditions`, `evidence`, and `uncertainty` strings. Record exact
  precision, dense/sparse mode, clock regime, cache/working set, concurrency,
  runtime and reproduction/raw-sample reference as applicable.

The tool validates the binding and basic fields, **not the truth or applicability
of those sources**. It does not fetch references, derive bandwidth from nominal
clock/bus width, turn a measurement into a physical upper bound, or automatically
feed unverified rates into an optimum calculation. Profiles and briefs are
snapshots; recheck identity/runtime/load before execution.

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

For a cheap first reference, an optional existing-Torch example is included:

```sh
CUDA_VISIBLE_DEVICES=GPU-<full-uuid> timeout 120 /existing/env/bin/python \
  hardware/probes/torch_quick_reference.py --device GPU-<full-uuid> \
  --output /fresh/task-private/reference.json
```

The caller must check current load/processes, coordinate exclusive use, and
record pre/post identity, clocks and power conditions. The output parent must
already exist. The probe checks Torch's actual UUID before allocations and uses
less than 1 GiB of allocated tensors: 8/256 MiB FP32 copy buffers and BF16 square
GEMMs of size 2048/4096, each with 3 warmups and 7 synchronized event samples.
It records raw samples, constant-input sanity and runtime/precision policy.
It does not install, compile source, profile, change clocks, or reserve resources.
A failed attempt can leave an empty output file; use a new path for another run.
An empty process list alone does not prove idleness: visibility can be restricted
inside a container. Check utilization and memory as well, and skip a busy or
ambiguous device rather than altering its services or isolation.

This is a narrow empirical reference, not a stress test, physical bandwidth
measurement, numerical qualification, full service curve or upper bound. A
small working set may be cache-resident, but that does not establish which cache
served it; large logical copy traffic is not automatically DRAM transactions.
Use a matched operator probe next only if its answer changes a decision.
`hardware-profile` never launches calibration or installs an environment.

## Reuse at the right scope

Cache three different things rather than rediscovering everything each time:

1. **Architecture knowledge:** official instruction, precision, memory hierarchy
   and scheduling semantics, keyed by vendor/architecture/document revision.
   Reuse as a starting point, not a substitute for the SKU's queried capacities.
2. **Device/host snapshot:** UUID and partition identity, actual SM/cache/memory
   limits, driver, visibility and PCIe/NUMA/NIC topology. Query on first contact
   and recheck cheap identities after host/runtime/allocation changes.
3. **Measured reference:** exact probe, shape/dtype/layout, software/backend,
   cache regime, clocks/power/load, raw samples and numerical contract. Another
   card of the same architecture may reuse the method, not the numeric rate.
   Rerun a small canary before trusting a cached rate in a new environment.

Store unknowns and the cheapest way to resolve them. Do not repeatedly try a
known unsupported Windows topology command, privileged profiler counter, or
opaque virtualized topology without a relevant environment/permission change.
This is guidance for saving work, not a mandatory inventory schema or phase gate.

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
