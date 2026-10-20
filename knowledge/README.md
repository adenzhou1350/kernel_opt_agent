# Reusable lessons

`lessons/` is the small default library. Read a few relevant lessons when forming
a hypothesis, then apply the ones whose conditions fit the current work.
After learning something reusable, update an existing lesson or add one scoped
lesson. A run does not owe the library a new card.

Knowledge is an evidence-backed starting point, not a method whitelist. A newer
model may choose a different algorithm or overturn old advice. Preserve the
applicability and counterexample when updating a lesson so the next task saves
experiments rather than inherits an unexplained rule. Same-architecture matches
help discovery; they do not establish equal device capacity or transferable rates.

```sh
python scripts/kernel_opt.py knowledge search "graph launch overhead" --limit 3
python scripts/kernel_opt.py knowledge add --file lesson.json
python scripts/kernel_opt.py knowledge add --file lesson.json --replace
python scripts/kernel_opt.py knowledge check
python scripts/kernel_opt.py knowledge inventory
```

The standalone entry point is `python scripts/knowledge_notes.py` with the same
commands. It uses only the Python standard library and performs no network
requests. Its optional `--directory PATH` goes before the command and selects
a different lesson directory.

For deployment, compare `inventory` output from the local and actual Scout
library. It reports filename, raw-byte SHA256 and canonical parsed-content
SHA256 without card bodies or local paths. Different raw hashes alone can mean
JSON formatting/BOM changes; differing content hashes mean advice differs.
Missing, changed and remote-only cards require separate decisions: do not mirror
an older checkout over newer remote advice or delete remote-only lessons.
Use reviewed committed cards and compare-and-swap checks for any copy. Inventory
is read-only, per-file evidence rather than an atomic snapshot of concurrent
writers, deployment authority, model consumption or measured knowledge benefit.

Each card has these fields:

- `id`: stable lowercase slug; its filename is `<id>.json`.
- `title`: one specific lesson, with a name useful for searching.
- `applies_when`: the workload, semantics or failure pattern where it helps.
- `lesson`: a concise explanation and a useful next action.
- `avoid_when`: counterconditions and limits to transfer.
- `evidence`: public `{ "url": "https://...", "note": "what this supports" }`
  entries. Distinguish a documented mechanism from a measured result.
- `status`: `hypothesis` for an unverified proposal, `validated` for a lesson
  supported within its stated scope, or `counterexample` for evidence against
  a specific claim. None qualifies a new candidate automatically.

For example, copy the structure of an existing card, choose its stable ID if
updating it, and edit the conditions, lesson and evidence together. Exact repeat
adds are no-ops. A new ID with an existing normalized title **or** lesson returns
the existing ID without writing; case, punctuation and whitespace do not create
new knowledge. Review that card and use its ID with `--replace` to incorporate
new evidence. Conflicting same-ID edits need `--replace`; replacements that
duplicate another card are rejected. Git already provides revision history.
The tool is intended for one writer at a time.

Search returns JSON with deterministic lexical scores, source paths, complete
cards and a scope caution. Scores rank word overlap, not evidence strength or
applicability. Unmatched queries return no cards. Read the public sources and
the current code before transferring a lesson; no match authorizes execution,
publishing, acceptance or a readiness claim.

Scout may prefer a card whose immutable GitHub evidence link names the same
repository and full source path as a supplied excerpt. Exact revisions rank
first. For equal revision/path affinity, query word overlap breaks the tie before
the stable ID; alphabetization should not hide a relevant lesson when several
cards cite the same large source file. A cross-revision path match is only a reason to read the old lesson and
check today's implementation, not proof that its conclusion still holds. This
lookup adds no source fetches, supplies at most one complete card within the
existing budget, and never displaces primary source evidence. A retrieval test
does not establish better discovery accuracy or PR conversion.

When no source-path card fits, the reader also preserves the running Scout's
bounded `source_text` interface: simple imported namespaces in the already
supplied text can suggest a more focused API lesson before generic task prose.
This lexical hint reads at most 24,000 characters and requires at least two
matching title terms. It does not parse/execute imports, resolve modules, fetch
missing code or prove applicability; comments and strings can match too. A
partial excerpt without imports falls back to the task query. Protocol/source
identity, exclusions and the complete-card budget still take precedence.

The Scout reader admits a complete card up to 8,192 serialized UTF-8 JSON bytes;
larger cards are omitted rather than clipped. Validate structure and the actual
reader tests available in this checkout:

```sh
python scripts/knowledge_notes.py check
python -B -m unittest tests.test_knowledge_context_budget tests.test_scout_lesson_source_paths
```

These checks establish format and advice availability, not scientific truth or
measured discovery yield. Keep a new finding scoped rather than raising every
prompt's allowance to fit an oversized card.

Keep private experiment logs, machine addresses, local run paths, credentials,
raw timing samples and private discussions out of cards. Contribute the reusable
finding with public references; if public evidence only explains a possible
mechanism, say so and keep the claim a hypothesis. `check` validates structure,
obvious private URL forms, filename safety and duplicates; it cannot establish
public accessibility, truth or the absence of sensitive prose.

The starter lessons distill recurring concerns from the existing primitives,
method revisions and methods: actual production work, execution mode, imported
source, timing order, precision contracts, intermediate ranges and excluding
exact-restored outliers from neighboring quantization estimates. Their public
sources explain the mechanisms; unpublished runs and numerical speedup claims
are deliberately absent.

When an existing card accumulates a different decision with its own applicability
and evidence, consider moving that part to a focused card rather than growing a
catch-all near the context limit. Move its sources with it; do not count the split
as a new finding. Check the original query, neighboring topics and complete-card
delivery without keyword stuffing or increasing every prompt's budget.

Where present, `methods/`, `primitives/`, `method_revisions/` and `community/`
remain specialist archives for explicit investigation and compatibility. Default search reads
only `lessons/`; archive cards are not automatically promoted into it.
