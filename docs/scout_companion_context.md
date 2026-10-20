# Applicable test context before more model calls

A source packet paired `src/cron/store/read-only.ts` with
`src/channels/plugins/read-only.test.ts`: the basename matched, but the test
belonged to a sibling component. Including a test file does not establish a
runnable regression for the source.

The path-only `kimi_scout_research.companion_source_paths` function already ranks
exact test names, shared directories, and mirrored `src`/`test` structure. For
comparable paths under the same `src` root, it now excludes different first-level
components. A source audit still reads at most one companion test, or none; it
does not add fetches, models, code execution, dependencies, or dispatch roles.
The optional experimental-feature policy lookup remains unchanged.

Generic basenames (`util`, `utils`, `helper`, `helpers`, `common`) need more than
an exact filename match. Their ranking now prefers the source parent's component
terms, shared/mirrored directories, then the source language family before the
exact name. C/C++/CUDA suffixes share a family, as do JS/TS variants. Component
locality can still select a Python binding test for C++ code; a foreign-language
candidate remains eligible when it is the only observed hint. Specific module
names retain their existing ordering.

A replay against vLLM `dde9aca41cd3ccceb1ffa902933b6678a09c83ce`'s 8,144 pinned
paths previously paired Python `fused_moe/utils.py` with Rust chat-renderer
`test_utils.rs`. The new ordering selects `tests/kernels/moe/utils.py` instead.
An intermediate implementation still chose a quantization helper because of its
shared prefix; the full-inventory replay exposed that error before deployment.
This is retrospective path-selection evidence: a utility file is not necessarily
an executable test, and neither its name nor its selection proves coverage.

These are lexical hints, **not** a semantic relevance classifier. Separate test
trees, distinct workspace roots, integration tests within a component, and
root-level files retain the existing fallback. Explicit caller/follow-up searches
are unaffected. A useful cross-component test might therefore be omitted from
automatic pairing; request it explicitly when source/import/caller evidence
supports the link. Remaining matches must still be inspected before counting
native coverage or running them.

For a changed source, the producer also preserves a bounded list of test paths
whose blobs changed between the same two snapshots. Among otherwise eligible
companions, these precede older tests; an unrelated changed test is not admitted
just because it shares the commit. `model.py` can use observed feature-directory
names as hints, while `model_executor` in an ancestor no longer counts as a
`model.py` test. At vLLM `8a1c02efca9bb0660f70b404e1ac4cb0629144ae`, this selects
the newly added `tests/models/test_deepseek_v41_pipeline.py`, which explicitly
imports the audited module, instead of an unrelated Marlin utility test.
Parent-name and frequency-only proposals selected other models/backends in the
full tree and were rejected. This is a known-case scheduling check, not a native
vLLM result or evidence of higher PR yield. One companion read, source windows,
seen keys and model budgets are unchanged; old packets are not replayed.

```text
python -B -m unittest tests.test_scout_companion_components tests.test_kimi_scout_research
```

The regressions cover sibling false matches, genuine local tests, input-order
independence, mirrored layouts, generic tests, partial-name ranking, and actual
producer read counts/packet construction with fake source responses. The earlier
sibling-component baseline failed two of ten focused checks: false companion
selection and the resulting extra producer read. These establish selection
behavior, not PR yield or improved model accuracy. No community-code, GPU, or
whole-workload performance claim is made.

## Python companion windows reuse observed owners

Pairing the right test file is not enough: a generic `core` or `prefetcher`
filename hint can select its imports rather than tests for the visible code.
For ordinary Python modules, reuse the existing, pinned window's first four
lexical owner entries. Non-dunder terminal names and conventional `test_` names
feed the existing bounded hint selector; no source body is parsed or fetched
again for this step. Package-initializer and other-language behavior is unchanged.
Without owner metadata or a matching name, ordinary hint fallback remains.

A cached four-window GCSFS/fsspec replay moved companion excerpts away from
the first70 lines without another network/model call. For example, a
`PrefetchConsumer` window selected tests containing direct `consume` and
`_advance` boundary calls. This is retrospective location evidence only:
the selected70 lines can still be partial, a generic name can match unrelated
code, and an earlier exact test-name match can favor one owner over another.
Selection does not prove coverage, test execution, improved model accuracy,
new discoveries or higher PR yield. Inspect actual admitted packet contents;
do not requeue previously reviewed windows merely because this hint changed.

```text
python -B -m unittest tests.test_kimi_scout_research tests.test_kimi_scout_context
```

## Continuation and companion requests must keep the same file identity

A supplied test window can be both an explicit continuation target and the
automatic companion test. In that case the continuation consumes the ordinary
read slot; omit the duplicate companion request. Do not first remove its path
and then apply its numeric offsets to the next lexical source. A real refill
attempt did exactly that: a test's line-179 continuation reached an unrelated
short header and repeatedly raised an end-of-file error. This was path-routing
failure, not source revision drift or a provider outage.

The regressions use the actual source reader and producer with offline fixture
text. They require correct path/window binding, no more than two source reads,
and preservation of the second tail window when needed. They establish reader
routing, not native target-project qualification or improved PR yield.

```text
python -B -m unittest tests.test_scout_source_continuation
```

An explicit re-request of a Python definition already marked incomplete can
continue at its next unread line instead of repeating the declaration prefix.
The owner/source reader must still have that exact file in its bounded raw
cache. The cached text's Git blob must equal the selected snapshot's blob;
only then may an unrelated repository revision change retain the line anchor.
Changed/missing content, ambiguous definitions/files, explicit head requests
and ranges outside the declaration retain the existing fallback. This consumes
an ordinary lexical read, not a third source slot or a complete-body assertion.
The frozen prospective pilot retains its original acquisition rules; this
production change does not retroactively change its arms or scores.

The opt-in import-context route can likewise inspect an older cached primary
file when its exact UTF-8 Git blob equals the current snapshot's blob. Missing,
changed, oversized or binary text still abstains. Imports remain syntax hints,
not installed-package resolution. Only current-tree targets are requested at the
current revision within the existing two-read budget; the inherited source URL
and text retain their original revision. This avoids losing a valid import hint
solely because an unrelated commit advanced main. It is not model-yield evidence.

When a follow-up exceeds the existing prompt cap, peripheral search snippets
still shrink first, followed by incomplete excerpts inherited from its parent,
before fresh partial evidence. Complete requested bodies keep their existing
protection. Fresh evidence can still shrink if necessary; neither completeness
nor correctness is inferred from its priority. Check the actual admitted packet,
not just the source reader's untrimmed output, when assessing evidence delivery.

## Declarative implementations are opt-in evidence text

Some repositories store implementations inside YAML, not Python files. An
operator may opt in a small directory using a repository's
`declarative_source_prefixes`, for example:

```json
{
  "source_prefixes": ["model/evaluators/"],
  "declarative_source_prefixes": ["model/evaluators/"]
}
```

Only `.yaml` and `.yml` within those explicit directories become source evidence;
the directories must also lie within the existing source prefixes. Other
repositories, excluded test/vendor/generated paths, byte/line/read budgets and
dedup keys retain their existing behavior. The same opt-in applies to issue
context and bounded adjacent-window follow-ups. A changed selection reopens a
completed empty sweep without resubmitting seen evidence.

Scout reads the files as inert UTF-8 text. It does not parse YAML tags, compile
embedded functions, execute examples, or acquire test qualification. A discovered
lead still needs an independent test through the target project's actual caller.
The motivating FutureAGI directory contained 88 YAML implementations and zero
default-eligible source files at `ea12cc3f4456fc568d9694a215c661b15be1cea2`;
restoring coverage does not establish new defects or improved PR yield.

```text
python -B -m unittest tests.test_scout_declarative_source
```

## Explicit implementation scopes

Directory source scopes skip Python `__init__.py` files by default. If a package
implements behavior in one (rather than just re-exporting names), explicitly
name its complete repository-relative path in `source_prefixes`, for example
`pyparsing/diagram/__init__.py`. This includes that file, not every initializer
under the directory; generated/vendor exclusions still apply. Selection only
supplies pinned source evidence and does not prove a defect or native execution.

## Inline function names in long issue templates

An issue can name a Python function after a long checklist, outside the generic
32-word hint budget. The source reader now considers up to eight distinct inline
backtick identifiers within the existing 2,000-character hint limit. If exactly
one actual Python function matches, its syntax location takes precedence over
generic keyword scoring. Existing qualified-member, explicit line/literal and
explicit definition requests retain their precedence. Paths, URLs, code fences,
duplicate declarations, multiple matching functions and invalid Python do not
activate this selection; classes and JavaScript declarations are not resolved by
this additional hint.

This reuses already-read source and the existing bounded window. It does not
fetch another file, infer a receiver, execute code or claim the function body is
complete. The exposed-case regression moved a window from unrelated tail text
to the named function; it is retrospective reader evidence, not a prospective
PR-yield or model-accuracy result.

```text
python -B -m unittest tests.test_scout_inline_issue_anchor tests.test_kimi_scout_context tests.test_scout_requested_definition
```
