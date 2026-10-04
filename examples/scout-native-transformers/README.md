# Callback batching must preserve the registered event loop

This optional CPU reproduction imports a **reviewed local Transformers checkout**
and initializes a real, tiny random-weight Llama through
`model.init_continuous_batching`. Two actual asyncio loops in separate threads
register callbacks through the public manager API. No AST extraction, replacement
router, model download, generation thread or GPU is used.

At upstream commit `469230357aab0f2b303b0d638c1f8d06edb14184`,
`OutputRouter.deliver_batch` collects callbacks but schedules them all on the last
handler's loop. Both reversed two-loop orders route a callback to the wrong loop
and trigger the real debug-mode Future thread check. Individual delivery,
single-loop streaming, queue fallback and empty batches are controls.

Use an existing compatible Python/Torch/Transformers dependency environment with
pytest. The example does not provision it or start local WSL. In PowerShell,
from the kernel_opt_agent root:

```powershell
$env:TRANSFORMERS_ROUTER_SOURCE_ROOT = 'D:/reviewed/transformers-checkout'
$env:CUDA_VISIBLE_DEVICES = ''
$env:HF_HUB_OFFLINE = '1'
python -m pytest -q examples/scout-native-transformers/test_output_router.py
```

Run once on the unchanged exact commit, then apply the included minimal patch to
a separate clean, task-owned checkout and repeat in a fresh Python process.
`git apply --check` should precede `git apply`. The patch batches once **per owner
loop** and binds each scheduled closure's own batch. The test also verifies
within-loop streaming order, terminal-handler cleanup and unknown-request queue
fallback; it does not require cross-loop delivery order.

Observed on Windows native Python 3.14.3, Torch 2.11.0+cu128 and pytest 9.1.1: unchanged source
has 3 failures / 4 passing controls; patched source has 7 passing cases. The two
existing upstream `test_output_router` cases also pass after the patch, with
137 deselected and one missing pytest-env configuration warning. This is routing
component correctness through the public registration path, **not** generated
tokens, model numerical correctness, production multi-loop deployment evidence,
latency/throughput improvement or complete upstream CI.

The callback signals arrival before its wrapper cleans up; the test drains each
loop before inspecting terminal handler state to avoid a fixture-induced race.
Loop threads are stopped/joined on assertion failure as well as success.

This finding does not authorize publication. Transformers' pinned
[`CONTRIBUTING.md`](https://github.com/huggingface/transformers/blob/469230357aab0f2b303b0d638c1f8d06edb14184/CONTRIBUTING.md)
asks autonomous agents not to open PRs/issues and requires coordination and human
review. Keep the patch as independent evidence unless those requirements are
actually satisfied; a confirmed component bug is not a Ready-PR decision.
