# Native Harmony streaming audit

This optional test executes the **complete, unmodified, stdlib-only parser**
from reviewed raw Git bytes. It neither imports a fake SGLang package nor
extracts methods. No model, GPU, package installation or network is needed during
the check; the Git objects must already exist in an explicitly selected checkout.

The source is SGLang main `35f3c96ff4794a4de15daf12caad371084a037ee`
and the independently fetched [existing repair PR #42246](https://github.com/sgl-project/sglang/pull/42246)
at `bb00fda98c3de8878ab80eed9198a361827fc64e`. This is someone else's
work, not a new contribution by this repository. Do not open a competing PR.

PowerShell, with a reviewed checkout containing both revisions:

```powershell
$env:HARMONY_AUDIT_GIT_ROOT = 'D:/your/sglang-checkout'
$env:HARMONY_AUDIT_REVISION = '35f3c96ff4794a4de15daf12caad371084a037ee'
python -m pytest -q examples/scout-native-sglang/test_harmony_chunks.py
$env:HARMONY_AUDIT_REVISION = 'bb00fda98c3de8878ab80eed9198a361827fc64e'
python -m pytest -q examples/scout-native-sglang/test_harmony_chunks.py
```

Observed on native Windows Python 3.14.3 / pytest 9.1.1:

- Main: 3 failed / 1 passed. The three tool-header tests check 341 delivery
  plans in total; 177 fail. The original five-chunk, whole-marker failure is
  included, so the result does not depend on splitting structural tokens.
- Existing PR: 4 passed; all 341 plans match one-shot tool content and raw text.
- Both versions preserve incremental ordinary reasoning before an end marker.

Recipient-before-channel, recipient-after-channel, whitespace and nested JSON
are covered. Character-level and exhaustive two-way splits are defensive
component checks, not 341 independent production cases. This does **not** test
`ReasoningParser`, downstream tool execution, installed-package imports, official
CI or whole-model/server correctness. It does not measure performance or prove
arbitrary malformed-input recovery. Tests skip without explicit opt-in and reject
unreviewed revisions/changed source bytes.

Before investing in implementation, check the live issue/PR timeline as well as
main. A cached issue saying no linked PR was already stale here; the live
[issue #42143](https://github.com/sgl-project/sglang/issues/42143) showed #42246.
