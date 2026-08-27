# Zero-device executor integration contract

This contract is part of the sealed harness. It does not authorize execution.

## Preapproval infrastructure artifact

Build `zero_device_interposer.c` before experiment materialization as a separate
infrastructure action. The build and any symbol-inspection process launches are
charged only to the materialization receipt, never hidden in an experiment
phase. The immutable build receipt uses
`zero-device-interposer-build-receipt-v1` and records at least:

- `status=PASS`;
- `source_identity`, `compiler_identity`, `linker_identity`,
  `symbol_inspector_identity`, `loader_identity`, and `binary_identity`;
- an identity allowlist for the exact `libcuda`, `libcudart`, and `libcupti`
  objects admitted during execution;
- the exact build argv and `materialization_process_launches`;
- exported symbols including `la_version`, `la_objopen`, `la_symbind64`, and
  `la_preinit`.

The experiment source seal must bind the build receipt, binary, C source,
compiler, linker, and loader identities before supervisor approval.

## Exactly six experiment processes

The experiment commands remain direct argv. There is no wrapper process:

```text
/workspace/dance/qwen35/.venv-cu13/bin/python <harness>/clean_build.py --run <run>
/workspace/dance/qwen35/.venv-cu13/bin/python <harness>/static_audit.py --run <run>
/workspace/dance/qwen35/.venv-cu13/bin/python <harness>/correctness.py --run <run>
/workspace/dance/qwen35/.venv-cu13/bin/python <harness>/warmup.py --run <run>
/workspace/dance/qwen35/.venv-cu13/bin/python <harness>/measure.py --run <run>
/workspace/dance/qwen35/.venv-cu13/bin/python <harness>/analyze.py --run <run>
```

The trusted executor imports `zero_device_audit.py` in its existing process.
Before phase 0 it calls `verify_executor_admission`. For every direct
`subprocess.run(argv)` it injects:

```text
LD_AUDIT=<sealed interposer binary>
LD_BIND_NOW=1
KERNEL_OPT_ZERO_DEVICE_LOG=<sealed experiment dir>/zero_device_logs/<phase>.log
```

It rejects preexisting injection/profiling variables, stale logs, argv drift,
or identity drift. Immediately after every phase it parses that phase log and
runs `assert_post_phase_toctou`. Any nonzero phase exit, missing `READY` or
`PREINIT`, malformed record, auditor failure, unsealed CUDA object, or sensitive
invocation makes the execution receipt FAIL/INVALID and stops the lifecycle.

After phase 6, the same executor process calls
`build_framework_zero_device_receipt` over these exact six logs:

```text
zero_device_logs/clean_build.log
zero_device_logs/static_audit.log
zero_device_logs/correctness.log
zero_device_logs/warmup.log
zero_device_logs/measure.log
zero_device_logs/analyze.log
```

The executor validates and writes the payload using the framework
`zero_device_execution_receipt.schema.json`; it then includes the resulting
receipt identity in the trusted execution evidence. The harness library never
writes a private receipt.

## Receipt semantics

The framework receipt is exactly
`zero-device-execution-receipt-v1`, with top-level fields:

```text
schema_version, status, request_id, experiment_identity, auditor_identity,
source_identities, harness_identities, offline_compile_only,
static_callgraph_audit, runtime_launch_audit, counters
```

`offline_compile_only=true`, static audit is
`PASS_NO_COMPILED_CALLABLE_EVENT_OR_GRAPH_PATH`, runtime audit is
`PASS_DRIVER_INTERPOSER`, and the only counter fields are all zero:

```text
cuda_kernel_launches, gpu_performance_samples,
compiled_callable_invocations, cuda_events, graph_replays
```

## Coverage boundary

GNU `LD_AUDIT` sees cross-DSO bindings in the base link-map and objects opened
through `dlmopen`; `la_objopen` marks every observed namespace for bind-to and
bind-from auditing. `RTLD_DEEPBIND` changes lookup precedence, not the fact that
an external selected definition crosses the dynamic binder.

It does not prove hidden/local or `-Bsymbolic` intra-DSO calls, raw NVIDIA
ioctls, secure-execution children that lose `LD_AUDIT`, children that scrub the
environment, foreign daemons, or undocumented launch paths. Such paths are
forbidden by the sealed experiment; their presence is not converted into a
false PASS.
