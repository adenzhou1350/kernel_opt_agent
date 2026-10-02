# Observable next-evidence acquisition

`scripts/scout_evidence_acquisition.py` is an optional standard-library helper
for fresh shadow experiments. It does not replace the live Scout fetcher, decide
candidate quality, launch code, or write files. A caller supplies already
sanitized public targets and enforces its cohort repository/revision constraints.

`fetch_source(url)` accepts only HTTPS `raw.githubusercontent.com` URLs with an
exact 40-character commit and a safe path. Percent-encoded targets are excluded
in this initial interface. It makes one GET, without authentication, redirect,
retry, model call, or fallback. A response is source text only on HTTP 200,
complete bounded UTF-8 body. HTTP failure bodies remain digest/accounting data,
not source evidence. A short body inconsistent with Content-Length fails.

For success and failure it records HTTP status when observed, application body
bytes returned to the reader, digest of that observed body/prefix, completeness,
error class, and client elapsed time. A read-budget sentinel permits at most one
byte over the declared cap. These are not total network/TLS bytes; a connection
failure may have unobserved traffic. The 20-second default is a socket-operation
timeout, **not a hard total-wall deadline**. Experiments needing a hard deadline
must separately enforce and account for one, including incomplete observations.

`AcquisitionSession.acquire(url)` shares an identical response across arms,
including failures, for at most 64 requests. It reports logical requested GETs
and actual GETs separately. A cache hit incurs no additional observed GET cost;
the original latency is not a measured counterfactual uncached latency.
`costs()` includes failed/invalid targets and explicitly leaves model/owner
cost, pricing, wire bytes, and counterfactual latency unmeasured.

Use this in a newly declared protocol. Historical pilot records remain immutable:
re-fetching their missing target does not recover the historical failure cost or
turn development examples into a prospective cohort. Source acquisition alone
does not establish native correctness, independent adjudication, PR conversion,
miss rate, dollar savings, or superiority to a strong-model/rules comparator.

Offline transport/accounting checks:

For a future utility study, include a no-additional-acquisition arm as well as
rules and model-selected evidence. Give each downstream reviewer the same
original input, frozen model/version, stopping rule and total resource cap;
charge target selection, failed reads, review and native verification to the
acquisition arms. Identical GET/window caps alone do not match total budgets.
Judge the incremental verified decision or reproduction, not window validity.
The present small acquisition trials do not satisfy this study design.

This is our experimental-design inference, informed by
[Scrouting (sections 6–9)](https://arxiv.org/html/2608.04804v1): its no-router,
cheap-fixer-plus-verified-handoff ablation ties the routed system on its measured
benchmark. It also explicitly lacks an unverified-handoff pass-through ablation,
so the verification guard's effect on final solves was not isolated. Neither
result proves a Scout-specific evidence selector helps. Treat verified handoff
and routing as separate interventions, with separate ablations.

```text
python -B -m unittest tests.test_scout_evidence_acquisition
```

The tests inject controlled responses to cover partial timeout/EOF, HTTP error
bodies, invalid UTF-8/targets/budgets, byte caps and cache accounting. They test
the reader's behavior, not remote availability or scientific utility.

## Language-neutral window selection

After a successful fetch, `scripts.scout_source_window.source_window(text,
anchor="export function example(")` selects up to 80 lines/10,000 characters
starting at a unique single-line literal. Alternatively pass an exact one-based
`start_line`. It is standard-library-only and does not execute source. The
original UTF-8 bytes are hashed; displayed newlines are normalized. Ambiguous,
missing, beyond-EOF or over-budget targets fail explicitly, with no fallback.
A comment or string match is only a text location, not a function definition,
reachable caller or quality verdict. The caller still binds repository/commit
and judges whether the returned evidence answers the question.

This avoids pretending that a Python-only symbol resolver supports TypeScript
or C++. It does not infer unknown anchors, find a call graph or fix guessed
paths. Declare this selector in a fresh comparison before seeing its cases;
post-trial repaired windows are development checks, not prospective wins.

```text
python -B -m unittest tests.test_scout_source_window
```

For acquisition-only shadow comparisons,
`scout_pending_cohort.compact_acquisition_view(packet)` offers a shared input
under 6,500 serialized characters. It retains a catalog of up to 24 source
URLs/ranges, discloses omissions, and allocates text to three snippets, pinned
code first in original order. It does not rank candidate merit, consult later
answers or change the live Scout prompt. Catalog-only entries have empty text;
clipped ranges describe the original snippets. An oversized catalog fails
explicitly rather than silently excluding a case. Apply it consistently to
every arm under a new declaration. Better source coverage is not demonstrated
utility, PR conversion or accuracy.

## Requested Python wrapper interfaces

The live producer's optional per-repository `followup_import_context=true`
uses `scout_import_context.import_requests` to replace guessed follow-up reads,
not add a new read tier. It accepts relative-import hints in top-level Python
free functions, including deferred/conditional imports. Competing targets,
nested functions/classes, missing cache and revision drift abstain. These are
module locations, not proof of Python binding or runtime support. An already
supplied complete export module is not requested again. A fully supplied cached
Python package with a literal `__all__` and the simple
`__getattr__ -> relative module import -> getattr(module, name)` pattern can
provide one observed-tree implementation hint. Missing cache, unsupported hook
syntax or ambiguous module/package files abstain. The helper does not fetch,
execute, recursively chase hooks, or expand the existing follow-up read budget.

For fresh shadow comparisons, `scout_catalog_target.mentioned_catalog_target`
provides a zero-model, language-neutral file baseline. It uses only the explicit
next-check text and at most 24 catalog entries: a unique full path outranks a
bare filename, repeated snippets are deduplicated, and competing paths/revisions
abstain. Only safe pinned URLs in the packet's repository qualify. Missing files
are not guessed, and the returned line 1 does not imply that the desired evidence
is there. Source text can be acquired and windowed with the existing helpers;
any definition lookup, fallback, or abstention must be declared identically
before a new comparison. This helper is not enabled in live routing. Offline
tests establish targeting/boundedness, not useful evidence or model superiority.

```text
python -B -m unittest tests.test_scout_catalog_target
```

Development example: at FlashInfer `426d028e`, the
[wrapper](https://github.com/flashinfer-ai/flashinfer/blob/426d028e18a270b60a1ac72306b29754bf087c67/flashinfer/fused_moe/cudnn_frost_selected.py#L56-L77)
imports `workspace_size` inside a function. Its
[export module](https://github.com/flashinfer-ai/flashinfer/blob/426d028e18a270b60a1ac72306b29754bf087c67/flashinfer/experimental/cudnn_frost_selected_kernels_moe_grouped_gemm/__init__.py#L15-L21)
defers to `bf16.runtime`; the
[actual signature](https://github.com/flashinfer-ai/flashinfer/blob/426d028e18a270b60a1ac72306b29754bf087c67/flashinfer/experimental/cudnn_frost_selected_kernels_moe_grouped_gemm/bf16/runtime.py#L235-L252)
accepts optional `out`. Five arguments in one wrapper do not establish that
another wrapper's six-argument call is invalid. The observed previous follow-ups
missed this interface. Offline producer tests now cover the two-hop acquisition
and unchanged two-read-per-follow-up ceiling, not native kernel correctness,
model accuracy, prospective cost savings or PR conversion. The limited cached
lazy-export hint now covers this source pattern; it is still not evaluation of
the export hook or proof of the installed package's binding.
