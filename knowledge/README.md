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
```

The standalone entry point is `python scripts/knowledge_notes.py` with the same
commands. It uses only the Python standard library and performs no network
requests. Its optional `--directory PATH` goes before the command and selects
a different lesson directory.

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

Where present, `methods/`, `primitives/`, `method_revisions/` and `community/`
remain specialist archives for explicit investigation and compatibility. Default search reads
only `lessons/`; archive cards are not automatically promoted into it.
