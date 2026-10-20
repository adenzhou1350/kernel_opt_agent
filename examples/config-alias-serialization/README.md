# Shared config-class alias serialization witness

This standalone native Transformers check illustrates a mechanism in vLLM
[`_register_config_class`](https://github.com/vllm-project/vllm/blob/3897f95cf17619137536d2a7d325d9c2f39dc38f/vllm/transformers_utils/config.py):
it changes `config_class.model_type` before registering that same class. At this
revision the registry maps both `kimi_k2` and `deepseek_v32` to Transformers'
`DeepseekV3Config`. The script reproduces those two registration statements;
it **does not import or test the full vLLM package**.

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

The development check used native Windows CPython 3.14.3, Transformers 5.16.1 and
Hugging Face Hub 1.31.0. The private environment inherited system packages,
including Torch 2.11.0+cu128; it was not a supported full vLLM/Torch 2.14 closure.
Both cross-alias orders changed the first object's serialized/saved `model_type`
to the second alias, despite its instance field retaining the first alias. The
same-alias control stayed stable. **Exit 1 is the expected defect witness**, not
a passing regression suite. Import or other unexpected exceptions must not be
counted as that witness; inspect the three output records.

No project repair, native vLLM `get_config` integration, serving/accuracy impact,
full CI or performance result is established. The existing vLLM
[`hf_overrides` test](https://github.com/vllm-project/vllm/blob/3897f95cf17619137536d2a7d325d9c2f39dc38f/tests/transformers_utils/test_hf_overrides_model_type.py)
requires both override and on-disk aliases to resolve to the selected class.
A future fix must preserve that contract and check class identity, caching and
pickling; blindly removing registration or creating unpicklable dynamic classes
is not qualified. Complete target-package validation and current duplicate-work
checks remain necessary before a vLLM contribution.

This is an exposed operational candidate and reusable reproduction, not a new
prospective research sample or evidence of Scout efficacy/PR conversion.
