# CPU cache-format selection needs an affected layer

A small native witness supporting the existing author's
[vLLM PR #62665](https://github.com/vllm-project/vllm/pull/62665), not a competing
fix. It checks one unsupported CPU cache format and a default-generation control.
No unsupported-cache tokens are generated. Synthetic weights do not qualify
trained-model accuracy, quantization numerics, performance or upstream CI.

## Keep the target path in the fixture

TurboQuant automatically excludes boundary attention layers. A two-layer Llama
therefore uses `auto` in **every** layer, even when the run-wide setting requests
`turboquant_k8v4`. Its successful startup does not exercise the format rejection.
Logging-only observation of the actual spawned selector confirmed this fallback.
Use three layers for a middle-layer rejection witness; keep the two-layer case
as a negative coverage control, not evidence that the patch is ineffective.

Reuse the random two-layer model prepared in
[the seeded CPU fixture](../native-cpu-seeded-prefill/README.md#prepare-once).
The observed three-layer model was derived without downloads: change its config's
`num_hidden_layers` to 3 and clone layer0 into layer2, preserving all existing
weights. In the isolated CPU venv, with `SOURCE_MODEL` set to that preserved
directory and `PRIVATE_MODEL` to a fresh directory:

```python
import json, os
from pathlib import Path
from safetensors.torch import load_file, save_file

src, dest = Path(os.environ['SOURCE_MODEL']), Path(os.environ['PRIVATE_MODEL'])
dest.mkdir()
config = json.loads((src / 'config.json').read_text())
assert config['num_hidden_layers'] == 2
config['num_hidden_layers'] = 3
(dest / 'config.json').write_text(json.dumps(config, indent=2))
weights = load_file(str(src / 'model.safetensors'))
weights.update({k.replace('model.layers.0.', 'model.layers.2.', 1): v.clone()
                for k, v in list(weights.items()) if k.startswith('model.layers.0.')})
save_file(weights, str(dest / 'model.safetensors'), metadata={'format': 'pt'})
```

## Inputs and execution

Use the existing native pytest capture, a fresh process, private HOME/caches and
a short private socket `TMPDIR`. Reuse the CPU environment settings documented in
the seeded fixture: no GPU, installation, build, network or shared-service changes.
The test requires:

- `PRIVATE_MODEL`: the same three-layer config and checkpoint for both arms.
- `EXPECTED_PACKAGE_ROOT`: canonical imported `vllm` directory.
- `EXPECTED_MODULES`: JSON mapping `platforms/cpu.py` and
  `v1/attention/backends/cpu_attn.py` to their reviewed raw-byte SHA256 values.
- `ROUTE_RESULT`: a fresh JSON output path recording actual constructor outcomes
  and the default control's two generated token IDs.

```sh
uv --no-config run --no-project --offline --python /private/venv/bin/python \
  python -B -m pytest -c /dev/null --rootdir=examples/native-cpu-cache-dtype \
  examples/native-cpu-cache-dtype/test_cpu_cache_dtype.py -q -s --tb=short
```

Inspect the child traceback too: the unsupported run must reach the reviewed
`CpuPlatform.get_attn_backend_cls` and its dtype-specific `ValueError` before the
first safetensors weight-loading progress. Spawned-engine initialization can wrap
that error as `RuntimeError`; an unrelated exception is not a passing rejection
witness. A parent import-path assertion alone does not prove every child path.
Compare default token IDs across arms, along with test/source identities and
managed-process cleanup. Do not reinterpret resource-tracker warnings as a
proof of a persistent leak, or silently discard them.

## Observed scope, 2026-10-21

Linux x86, AVX-512 available, AMX unavailable; Python3.12, Torch2.14.0+cpu,
Transformers5.19.0. Only the two named modules were overlaid from parent
`e2d2680417432b80986a36d456e3d79173ee1a45` or author head
`4de643cbcfa395d95bb2dafb5bda7f951f2d464f` on the same official
`0.32.1rc1.dev36+ge68efc685` CPU distribution. This is not a full PR build,
ARM/macOS replication or qualification of other engine/source combinations.

The author's unchanged 11 selected tests: parent5 pass/6 fail; author11 pass.
An extra real-host, non-mocked selector control: parent fails, author passes.

| Same three-layer checkpoint and test | Parent modules | Author modules |
| --- | --- | --- |
| `turboquant_k8v4` construction, no generation | Accepted; rejection assertion fails | Child selector raises the named error before loading weights |
| `auto` generation control | Generates `[107, 92]` | Generates the same `[107, 92]` |

The unchanged engine test therefore fails on the parent and passes on the author
overlay. Both captures finish without runner-enforced post-exit group cleanup;
raw application teardown/resource-tracker warnings remain evidence, not a claim
that all lifecycle problems are absent. The earlier two-layer rejection test was
an invalid target-coverage assumption, not silently converted into a passing test.

Separate E4M3/E5M2 native-pack controls against exact Torch cast bytes failed
identically under **both** module overlays, with identical observed bytes and
shared native-library hashes. Those failures remain unresolved for this older
native distribution; no tolerance was loosened and no FP8 numerical qualification
or patch-caused kernel regression is claimed.
