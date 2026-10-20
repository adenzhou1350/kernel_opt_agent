# Shared config-class alias serialization witness

This standalone native Transformers check illustrates a mechanism in vLLM
[`_register_config_class`](https://github.com/vllm-project/vllm/blob/3897f95cf17619137536d2a7d325d9c2f39dc38f/vllm/transformers_utils/config.py):
it changes `config_class.model_type` before registering that same class. At this
revision the registry maps both `kimi_k2` and `deepseek_v32` to Transformers'
`DeepseekV3Config`. By default the script reproduces those two registration
statements without importing vLLM. With `--vllm`, it instead calls the installed
package's real `get_config()`; the copied registration helper is not used.

Use a task-private environment, for example:

```sh
uv venv /path/to/private-env
uv pip install --python /path/to/private-env/bin/python transformers==5.16.1
uv run --no-project --offline --python /path/to/private-env/bin/python \
  python -B examples/config-alias-serialization/reproduce.py
```

On Windows use the private environment's `Scripts/python.exe`; no WSL is needed.
The script disables Hub access and CUDA visibility before importing Transformers.
It creates only local configuration JSON files, loads them through real
`AutoConfig.from_pretrained`, and saves the first configuration again. No weights,
tensor computation, GPU, external data or pytest plugin is required.

The initial copied-helper check used native Windows CPython 3.14.3, Transformers 5.16.1 and
Hugging Face Hub 1.31.0. The private environment inherited system packages,
including Torch 2.11.0+cu128; it was not a supported full vLLM/Torch 2.14 closure.
Both cross-alias orders changed the first object's serialized/saved `model_type`
to the second alias, despite its instance field retaining the first alias. The
same-alias control stayed stable. **Exit 1 is the expected defect witness**, not
a passing regression suite. Import or other unexpected exceptions must not be
counted as that witness; inspect the three output records.

## Full-package CPU check

With an existing reviewed CPU vLLM environment, run the same source as:

```sh
uv run --no-project --offline --python /path/to/vllm-env/bin/python \
  python -B examples/config-alias-serialization/reproduce.py --vllm
```

A separate native Linux check used the official CPU distribution
`vllm 0.32.1rc1.dev36+ge68efc685.cpu`, Torch 2.14.0+cpu, Transformers 5.19.0
and Hugging Face Hub 2.2.0. There was no source export or helper replacement in
that check: both aliases were loaded through the installed `vllm.get_config`.
The two serialization witnesses failed, while same-alias, CPU/native-extension
import and the existing `hf_overrides` class-identity checks passed: **3 passed,
2 failed, zero errors/skips**. The complete package's configuration-module bytes
were unchanged; the owned process group exited without forced cleanup. The
captured invocation took 8.75 seconds, excluding earlier SDK setup and owner
work. This is one exposed case, not five discoveries or a cost-saving result.
The final public CLI was then checked in both modes in that CPU environment;
both retained the same two cross-alias failures and stable same-alias control.
Those CLI checks are reproducibility checks, not additional independent cases.

That fixed CPU distribution is **not latest-main execution**. The separately
inspected pinned-main source above still contains the shared-class registration
mechanism; source evidence is not a rerun of the entire newer package. No
project repair, serving/accuracy effect, full CI or performance is established.
The existing vLLM
[`hf_overrides` test](https://github.com/vllm-project/vllm/blob/3897f95cf17619137536d2a7d325d9c2f39dc38f/tests/transformers_utils/test_hf_overrides_model_type.py)
requires both override and on-disk aliases to resolve to the selected class.
A future fix must preserve that contract and check class identity, caching and
pickling; blindly removing registration or creating unpicklable dynamic classes
is not qualified. A repaired candidate still needs its own target-package
validation and current duplicate-work checks before a vLLM contribution.

## Rejected repair: stable metadata is not alias-preserving persistence

One private, one-module prototype replaced the helper with
`CONFIG_MAPPING.register(model_type, config_class, exist_ok=True)` and removed
both writes to `config_class.model_type`. On the same fixed CPU distribution,
its 15 selected checks passed: mixed-alias stability, repeated aliases, native
class metadata/identity, ordinary and fresh-interpreter pickle, and the existing
`hf_overrides` check. That was **not** a sufficient repair contract.

A separate seven-check save/reload comparison passed on the original package
but failed six checks on that prototype. Five aliases became canonical types
after `save_pretrained()` followed by `get_config()`. In particular, `kimi_k2`
became `deepseek_v3`; the installed `get_tool_call_id_type` helper then selected
`random` instead of `kimi_k2` using a minimal model-config-shaped wrapper.
`RefinedWeb` aliases also reloaded as `FalconConfig`, not `RWConfig`.
The prototype was rejected, not submitted as a vLLM repair.

For a future repair, test this additional local-config-only path as well:

```python
from types import SimpleNamespace
from vllm.renderers.chat_utils.tool_call import get_tool_call_id_type
from vllm.transformers_utils.config import get_config

before = get_config(local_kimi_config_dir, trust_remote_code=False)
before.save_pretrained(fresh_saved_dir)
after = get_config(fresh_saved_dir, trust_remote_code=False)
assert after.model_type == before.model_type
def select(config):
    return get_tool_call_id_type(SimpleNamespace(
        hf_config=config, hf_text_config=config, hf_overrides=None))
assert select(after) == select(before) == "kimi_k2"
```

Here `local_kimi_config_dir` contains only a synthetic `config.json` with
`model_type="kimi_k2"`; `fresh_saved_dir` is task-private. This is a dispatch
helper check, not an engine run or evidence of a model-output incident.
Preserving canonical class metadata and passing pickle must not replace the
existing alias/persistence contract. These checks used the fixed CPU wheel,
not current-main, ModelScope, full CI or a new prospective research sample.

### Alias subclasses also need consumer qualification

A separate offline probe in the same environment found that both DeepSeek
aliases resolve to Transformers' native `DeepseekV3Config`, not a vLLM-specific
config class. That class is recognized by both `TOKENIZER_MAPPING` and
`MODEL_FOR_CAUSAL_LM_MAPPING`; a differently named, unregistered subclass is
recognized by neither. The other two alias families' original custom classes
already have neither mapping, so those are not newly lost mappings.

[Transformers 5.19's auto factory](https://github.com/huggingface/transformers/blob/c4c4605f961877852b89b97478536bb3a26b6fd1/src/transformers/models/auto/auto_factory.py)
checks the concrete config class, and its lazy fallback matches registered class
names rather than arbitrary subclass inheritance. Therefore, separate stable
alias classes are not a drop-in fix merely because `isinstance` and pickle work.
Any such design must independently preserve or explicitly review tokenizer/model
registration and the existing `hf_overrides` behavior. The probe installed no
alias classes, registered no mappings and loaded no tokenizer/model. It does not
prove that all wrapper designs fail or qualify an actual serving regression.

This is an exposed operational candidate and reusable reproduction, not a new
prospective research sample or evidence of Scout efficacy/PR conversion.

## Check the documentation assistant's reference, not only its answer

The documentation-assistant consultation was completed on 2026-10-20. Its reply
called the side effect unintended and pointed to
[PR39554](https://github.com/vllm-project/vllm/pull/39554). Independent inspection
found that PR merged on 2026-04-21, but it fixes a different boundary: an
`hf_overrides` type differing from the checkpoint's on-disk type must still load
the registered config class. Its added test is the compatibility control already
used above; it does not check sequential aliases or prior-object serialization.

The review explicitly preserves the AutoConfig path so model, tokenizer and
processor config construction stays consistent. The final patch registers both
names while changing/restoring the shared class attribute. It is related work
and a repair constraint, not evidence that this serialization witness is fixed,
a maintainer confirmation of our report, or permission to bypass validation.
Do not classify the candidate as a duplicate merely from the assistant's link,
or call it accepted merely from the assistant's description.

The independently reproduced serialization behavior is now reported in
[vLLM issue #62645](https://github.com/vllm-project/vllm/issues/62645), with the
tested package versions, both mixed-alias orders, the same-alias control and
reviewed official environment-collector output. The collector's bytes match the
separately inspected main revision; that does not turn the fixed-wheel
reproduction into a latest-main execution. Publication is not maintainer
confirmation, an accepted repair or evidence of model-output impact.
