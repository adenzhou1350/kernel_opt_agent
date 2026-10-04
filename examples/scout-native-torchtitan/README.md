# Test the checkpoint consumer, not a guessed alias verdict

This optional example imports a **reviewed local TorchTitan checkout** at
`290d499942d6cd4adb9420c56f111ec6a2e09e26`. It checks actual module paths and
raw source hashes; it neither extracts functions nor replaces project modules.
Default repository test collection skips it until a source root is explicitly
set. It does not install dependencies, fetch source, initialize CUDA, or start WSL.

Use an existing compatible Python/Torch dependency environment with pytest and
the pinned `spmd_types==0.2.5`. In native PowerShell, from kernel_opt_agent:

```powershell
$env:TORCHTITAN_AUDIT_SOURCE_ROOT = 'D:/reviewed/torchtitan-checkout'
$env:CUDA_VISIBLE_DEVICES = ''
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B -m pytest -q -p no:cacheprovider examples/scout-native-torchtitan/test_checkpoint_consumers.py
```

Provide an LF checkout matching raw Git blobs. On Windows, configure
`core.autocrlf=false` **before** creating a fresh checkout, or reuse the existing
raw-blob bundle tool. Do not overwrite another task's working tree.

Observed on native Windows Python 3.14.3 / Torch 2.11.0+cu128 / pytest 9.1.1:

- The actual purge worker survives a real missing-directory deletion error,
  deletes the next directory, and stops before a later queued directory.
- `_shares_storage` reports false for detached FSDP wrappers even when their
  inner tensors alias. The **actual ModelWrapper consumer** falls back to copy;
  cached storage and updated/loaded values stay correct in this CPU control.
  A false helper predicate alone does not demonstrate checkpoint corruption.
- Actual replicated CPU DTensors report the expected local-storage aliases.
  A one-rank Gloo/FileStore process group is created and destroyed by the test.
  Windows Torch lacks `HashStore` in this environment; no fake distributed
  module or local WSL is needed.

These three component checks pass on unmodified source. This is not a proposed
upstream fix, official dependency-complete CI, multi-rank checkpoint save/load,
async staging, training correctness, or performance qualification. The original
upstream checkpoint test module cannot collect in this environment because an
unrelated optimizer import requires `torch.cuda._graph_annotations`. That remains
untested, not passing; a smaller native check does not erase the incompatibility.

The checks were developed during a **post-outcome** audit of one source-window
NO_LEAD. No new defect was reproduced, but neither tests nor source inspection
prove absence of defects or zero false negatives. Keep the failed initial probe,
the successful consumer controls, and their scopes distinct. They do not rescore
the earlier cohort, establish routing utility, or justify a paper claim.

Public source: [base helper and consumer](https://github.com/pytorch/torchtitan/blob/290d499942d6cd4adb9420c56f111ec6a2e09e26/torchtitan/components/checkpointer/base.py),
[wrapper lifecycle](https://github.com/pytorch/torchtitan/blob/290d499942d6cd4adb9420c56f111ec6a2e09e26/torchtitan/quantization/_fsdp_tensor.py).
