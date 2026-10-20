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

This is an exposed operational candidate and reusable reproduction, not a new
prospective research sample or evidence of Scout efficacy/PR conversion.
