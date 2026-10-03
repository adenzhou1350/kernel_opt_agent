# Owner-reviewed Transformers cache checks on native Windows

This is a recipe for an independently reviewed change, not a sandbox or an
automatic executor for arbitrary Scout output. Use repository-native tests
before treating a reduced-method reproducer as delivery evidence. A retained
real defect can still be blocked on contribution policy or accelerator coverage.

## Reuse capacity without silently changing the system

Use a task-private virtual environment. An already installed compatible Torch
can be inherited deliberately with `--system-site-packages` to avoid another
large download, but disclose that inheritance: this is not a fully isolated or
reproducible dependency lock. Record the interpreter, Torch version and module
path, and the packages installed into the private environment. Install missing
public test wheels there, not into the global environment; keep cache/temp files
on the intended storage drive. Do not start local WSL as a fallback.

At the reviewed [source commit](https://github.com/huggingface/transformers/commit/02d8fb9784e8f14a1251e4c992cd82a5762417c6),
the native cache test module imports `parameterized`. The root pytest plugin
also uses xdist hooks. Missing either prevented our initial full test entry;
extracting a method bypassed those imports but was not repository-native pytest.
The owner environment used Python 3.14.3, inherited Torch 2.11.0+cu128, and
task-private parameterized 0.9.0 / pytest-xdist 3.8.0 / pytest 9.1.1, alongside
the reviewed source's runtime dependencies. These versions describe one tested
environment, not a recommended matrix or complete upstream testing extra.

## Check source and device in the test process

Set child environment values before importing Torch or Transformers:

```powershell
$env:CUDA_VISIBLE_DEVICES = '-1'
$env:TRANSFORMERS_TEST_DEVICE = 'cpu'
$env:HF_HUB_OFFLINE = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = "$reviewedArmRoot/src"
```

Do not infer zero GPU use from an empty environment value, a parent-shell
variable, or successful exit alone. In the **same fresh process** that invokes
`pytest.main`, first assert `torch.cuda.device_count() == 0`,
`not torch.cuda.is_available()`, and
`transformers.testing_utils.torch_device == 'cpu'`. Assert the resolved
`transformers.cache_utils.__file__` equals the reviewed arm's source file;
record its byte hash and recheck the module path after pytest. These checks are
provenance/preflight, not isolation from malicious code.

Use complete baseline/candidate source roots, the same private interpreter,
same regression test bytes and repository conftest in fresh processes. A
candidate test-only overlay on the baseline must be explicit. One observed
comparison kept the candidate test module/conftest as the pytest entry for
both arms and switched the complete imported production root through
`PYTHONPATH`; neither original production tree was edited during comparison.
No AST-extracted replacement method was used in that comparison.

The affected native entry was:

```text
pytest -q tests/utils/test_cache_utils.py::CacheTest
```

This selects the non-model-loading cache class, not the entire module. Keep
accelerator skips, warnings and negative controls. Offline flags prevent the
normal Hub download route but are not a network sandbox.

## Observed defect and limits

The pinned [Cache.prefetch](https://github.com/huggingface/transformers/blob/02d8fb9784e8f14a1251e4c992cd82a5762417c6/src/transformers/cache_utils.py)
searches for an eligible offloaded layer. With only resident sliding layers,
the eligible list is empty and both the initial search and wraparound search
raise `ValueError`. Real `DynamicCache` and `StaticCache` constructors plus
CPU tensor updates reproduce it; CUDA stream APIs are mocked only in the new
regression test. An early return when no layer is eligible fixes that branch.

In the native paired run, the baseline produced **two failing subtests** of
the added regression (DynamicCache and StaticCache). The candidate summary
was **10 passed, 1 skipped, 2 subtests passed**. Retained warnings included the
missing pytest-env config plugin and already-imported AnyIO assertion rewrite.
An earlier attempt without explicit CPU selection had two compiler/device
failures; those did not reproduce in the attested CPU pair. That observation
does not establish the exact cause of the earlier run or qualify GPU execution.

This establishes local CPU test discrimination, not full-suite, GPU offload,
model-generation, performance or PR acceptance. The upstream contribution
rules require human review and issue coordination and ask autonomous agents
not to publish issues/PRs. Check current rules before publication; passing this
recipe does not authorize a public contribution or replace `make style`.
