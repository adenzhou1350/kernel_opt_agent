# CPU seeded sampling across chunked prefill

One public `LLM.generate` fixture for [vLLM #62687](https://github.com/vllm-project/vllm/issues/62687)
and the author's [PR #62688](https://github.com/vllm-project/vllm/pull/62688).
It is not a new competing implementation. The fixture records generated token
IDs; the caller must compare them across fresh processes. A passing individual
run establishes generation and a healthy follow-up request, **not** equality
with another run, model accuracy, performance or complete serving correctness.

## Prepare once

Use an existing isolated Linux CPU vLLM environment and its uv-selected Python.
No GPU, remote code, model download or runtime package installation is needed.
The following creates the same 361,088-parameter random Llama used in the check;
run it once with `PRIVATE_MODEL` set to a fresh task-private directory. These
are synthetic weights for a sampling/state regression, not a trained checkpoint.

```python
import os
import torch
from transformers import LlamaConfig, LlamaForCausalLM

torch.manual_seed(20261021)
config = LlamaConfig(
    vocab_size=128, hidden_size=128, intermediate_size=256,
    num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=4,
    max_position_embeddings=512, bos_token_id=1, eos_token_id=2,
    pad_token_id=0, tie_word_embeddings=False,
)
model = LlamaForCausalLM(config).to(dtype=torch.float32, device="cpu")
model.save_pretrained(os.environ["PRIVATE_MODEL"], safe_serialization=True)
```

Keep model files, artifacts and caches on the task volume. Use a **short unique
private** `TMPDIR` for Unix sockets: vLLM appends a UUID to its RPC base path.
A deep evidence path caused ZeroMQ to fail before sampling; that is not #62687.
See the [existing path-budget lesson](../../knowledge/lessons/unix-socket-temporary-path-budget.json).
CPU inference was bounded to two available CPUs, 12 GiB process address space,
one GiB CPU KV cache and a 100-second capture limit per condition. These are
observed task settings, not universal hardware or isolation requirements.

## Run and compare

The fixture uses these explicit inputs:

- `EXPECTED_PACKAGE_ROOT`: canonical directory containing the imported `vllm/__init__.py`.
- `EXPECTED_RUNNER_SHA256`: reviewed raw-byte SHA256 of that package's
  `v1/worker/gpu_model_runner.py`. Module path, inherited CPU method and digest
  are checked in the actual test interpreter.
- `PRIVATE_MODEL`: the preserved model above; verify its files before each run.
- `CHUNKED_PREFILL`: `0` for the unchunked reference, `1` for chunking.
- `PREFILL_BUDGET`: `128` for reference, `16` or `32` for chunking.
- `TOKEN_RESULT`: a fresh output JSON path for that condition.

Run the existing native pytest capture with:

```sh
uv --no-config run --no-project --offline --python /private/venv/bin/python \
  python -B -m pytest -c /dev/null --rootdir=examples/native-cpu-seeded-prefill \
  examples/native-cpu-seeded-prefill/test_cpu_seeded_prefill.py -q -s --tb=short
```

Set task-private HOME/caches, `CUDA_VISIBLE_DEVICES=''`, `OMP_NUM_THREADS=2`,
`MKL_NUM_THREADS=2`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`,
`VLLM_PLUGINS=''`, `VLLM_USE_V2_MODEL_RUNNER=0`, `VLLM_CPU_KVCACHE_SPACE=1`,
`VLLM_CPU_OMP_THREADS_BIND=nobind`, `VLLM_WORKER_MULTIPROC_METHOD=spawn` and
`PYTHONDONTWRITEBYTECODE=1`. Use the prepared CPU environment's OpenMP preload
when required by that distribution. Do not modify shared libraries or processes.

Each condition starts a fresh engine. Compare **all three** `seeded_tokens`
arrays, not just generation exit codes or their first tokens. Check the saved
pytest report, output cardinality, actual module identity and process cleanup.
The follow-up is a separate unseeded greedy request; success proves the engine
remains usable in that process, not an HTTP health endpoint. Unexpected setup
errors, warnings and cleanup failures remain part of the result.

## Observed independent check, 2026-10-21

Same Linux/Python 3.12, Torch `2.14.0+cpu`, Transformers `5.19.0`, official vLLM
`0.32.1rc1.dev36+ge68efc685` distribution/native libraries. Only
`gpu_model_runner.py` was overlaid from the exact parent
`8407bc0bb6b0061dacb731ae3cc54b6035f112b3` or author head
`bdd9361152502528398f80d07703b08a00255514`, with fresh processes and matched
other files/model/test. This is **not a full PR checkout/build**, another model,
GPU/speculative-decoding verification, macOS replication or official CI.

| Runner condition | Observation |
| --- | --- |
| Parent, unchunked | Generates 3×8 tokens; follow-up passes |
| Author head, unchunked | Same token IDs as parent; follow-up passes |
| Parent, chunk budget16 | Fails with `CPU Generator does not use offset` |
| Author head, budget16 | Same token IDs as unchunked; follow-up passes |
| Author head, budget32 | Same token IDs as unchunked; follow-up passes |
| Parent plus **only** skipping CPU offset rewind, budget16 | Generation/follow-up pass, but seeded token IDs differ from the preserved unchunked reference |

That last controlled variant is not the author's fix. It demonstrates why only
removing the exception is insufficient for this fixture's seeded-sequence
contract. It does not establish convergence or cross-backend numerical identity.
Five original captures took about194.50 wall seconds including process/engine
setup; the extra variant is separately metered. These timings are not a speed
comparison or total contribution cost. All managed test process groups exited
without forced post-exit cleanup. The expected crashing baseline also emitted
a shared-memory resource-tracker warning, retained rather than called a clean
engine shutdown or proof of a persistent leak.

Harness setup failures preceded those captures: an absolute source identity
was rejected before any test, then a long Unix-socket path prevented engine
startup. Both were retained. No provider calls, new package install, trained
checkpoint download or GPU use were required. Owner-selected known bug/repair
validation is not a prospective selector experiment or a novel discovery.
