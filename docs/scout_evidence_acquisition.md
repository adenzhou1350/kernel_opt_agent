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

## Optional missing-implementation discovery

An explicit `references(identifier)` request now also supports the primary
cached Python file. AST name loads and attribute reads locate up to two unseen
80-line windows, replacing ordinary follow-up reads. Plain strings, comments,
imports, definitions and name stores are not reference hits. The file is parsed,
never imported or executed. Invalid syntax, a cache miss, a different revision,
or only already-supplied matches leave the ordinary selection intact. This
same-file hint does not resolve aliases, attribute owners, conditional execution
or dynamic string lookups, and must not be treated as a call graph.

The development failure motivating this extension asked for a Python helper's
callers but reacquired its definition. Offline replay now exposes the cached
consumer. This establishes acquisition behavior, not reduced false positives,
PR yield or prospective selector superiority; the known case is not a holdout.

A repository may opt into `followup_code_search=true`. When a needs-context
follow-up explicitly asks for `references(identifier)` (one or two bounded ASCII
identifiers or hyphenated reason codes), and no cached reference, import,
registration, continuation or kernel-definition read already supplies the next
step, the controller makes at most one GitHub code-search query. Five current
default-branch index hits are only path hints: intersect them with the already
observed immutable source tree, prefer implementations to test paths, then read
at most two 80-line windows at that fixed commit. A second requested literal can
use another window in the same cached file. Search results' URLs and contents
are never trusted as source; a window lacking its requested literal is discarded.
Unavailable search is observable and falls back to the existing bounded selection.
The index may be stale or incomplete, and a literal can be a comment/declaration,
not a definition or reachable caller. No call graph, defect verdict, native
execution or novelty is inferred. This does not increase the two-source-read
ceiling, but the discovery API request is an additional cost. Query results are
cached for the existing 15-minute snapshot TTL, keyed by repository, target
commit and literal, with tree membership rechecked on reuse.

C-family `.cc`, `.c` and `.cxx` files are included in observed-path selection;
a tree member with one of these extensions must not be silently excluded.

Offline checks:

```text
python -B -m unittest tests.test_scout_code_search
```

Development evidence motivating the opt-in: an unexecuted report
[TileLang #3381](https://github.com/tile-ai/tilelang/issues/3381) requested
`LowerToSTGPredicated` / `LowerToLDGPredicated`, but its supplied catalog had
carver policy and engine entry Python, not
[the actual pass](https://github.com/tile-ai/tilelang/blob/994b44eca1a83a00d19d926e5264a6c608700656/src/cuda/transform/lower_ldg_stg.cc).
Independent inspection and a native CPU-only TileLang 0.1.15 IR transform showed
an outer-store/inner-load predicate discrepancy. This was extra owner work, not
a selector win, GPU execution or a current-source native rebuild. Current code
search located the missing observed path. That development check establishes
feasibility, not prospective conversion/cost superiority.

## Displayed-row review citations (experimental)

`scout_review_citations.citation_view` preserves each bounded excerpt as a rows
array with a local evidence ID. `resolve_review` accepts one-based excerpt row
ranges and extracts their exact displayed text, including existing line prefixes,
instead of requiring a model to reproduce escaped quotes. These are display
positions, **not** original file line numbers. At most two spans, eight rows and
1,400 characters per span are allowed. A valid span does not verify the reason,
producer/consumer contract, execution or candidate quality; independent semantic
adjudication remains required. This interface is not enabled in live Scout.

```text
python -B -m unittest tests.test_scout_review_citations
```

Two fresh, nonrandom follow-up inputs in an interface feasibility pilot still
had no eligible implementation file in their catalogs. All acquisition selectors
abstained, with zero GETs. Six reviewer completions correctly described missing
implementation evidence, but only two respected the citation interface; four
chose unavailable or over-budget ranges. No incremental verified solve was
demonstrated. Do not repair those answers into successes or claim cross-cohort
accuracy from this negative result. Explicit rendered row labels are a candidate
for a future fresh trial, not a retroactive improvement to this one.


`numbered_citation_view` offers an optional model-facing rendering with explicit
`{"row": 1, "text": "315: ..."}` labels. Preserve the plain `citation_view` as
resolver input: rendering does not change normalized text, IDs or digests. It
performs no fetch or live routing change.

A subsequent predeclared recent-follow-up trial requested four cases but enrolled
only one; the three empty slots were not replaced after inspection. All three
arms used the numbered interface. No-additional and the explicit-file rule
returned valid INSUFFICIENT reviews; the rule abstained. The model selected one
80-line pinned window containing the missing encoder, but its review cited 13
rows against the frozen eight-row cap and was rejected, without retry or repair.
Reported total tokens were 2,636 / 2,582 / 7,388 respectively (four calls total);
only the model arm made a source GET (21,857 body bytes). These are observed
reported token costs, not dollar or cached-latency savings.

After predictions were sealed, six separate pinned owner source reads found
small-M caller reachability but no demonstrated runtime defect; the owner label
remained INSUFFICIENT pending applicable TMA-store semantics/native verification.
This is unresolved, not a negative bug label. There were zero incremental
owner-supported decisive solves. The one-case underfilled, nonrandom trial does
not establish citation-accuracy improvement, acquisition superiority or PR yield.
Explicit labels alone did not eliminate invalid ranges. Owner review is not an
independent human judgment; vendor-document browsing is separate from model GET
cost. Raw private experiment records remain local.
