# Structured observations before another model layer

This example preserves a limited negative comparison, not a proposed new agent
method. When an owner-reviewed native probe already returns the requested facts,
first compare direct handling of those facts with another model reviewing them.
Neither path decides that a change deserves a PR or satisfies its public contract.

## Reproduce the native facts

Prepare private, reviewed raw-Git source exports with
`scripts/qualification_source_bundle.py`. Do not run arbitrary generated code or
replace a shared installation. The examples need no GPU, model weights or network
after setup; they are not sandboxes. Record the actual interpreter/compiler and
imported source. A hash of one module does not bind the complete environment.

For Click, compare parent `6d5bac5c712195cbfa9666ba0ecbf0573cdea356`
with [repair f67c2bb6](https://github.com/pallets/click/commit/f67c2bb6c2f055c1c7a57cd46c3697fc26a7742e).
Run in separate processes with each export's raw `src/click/utils.py` SHA256:

```text
python -B probe_click.py --source REVIEWED_EXPORT --utils-sha256 RAW_MODULE_SHA256
```

On native Windows CPython 3.14.3 the parent returned
`["Weigh apples vs.", "Weigh apples vs.", "Pick a fruit.", ""]`;
the repair returned
`["Weigh apples vs. pears.", "Weigh apples vs....", "Pick a fruit.", ""]`.
The same four selected upstream test cases, overlaid unchanged on both packages,
had 2 failures/2 passing controls before and 4 passes after.

For mapstructure, compare parent `9aa3f77c68e2a56222ea436c1bfa631f1b1072d5`
with [repair cd52f897](https://github.com/go-viper/mapstructure/commit/cd52f897d661ab270360ef886f72cd1a09325c55).
Copy `observe_hooks_test.go` into each **private** complete module export, then run:

```text
go test -json -count=1 -run '^TestObserveHookOutputs$' .
```

Linux amd64 Go 1.25.10 recorded `PANIC, foobar, PANIC` before and
`NIL, foobar, NIL` after. The observer recovers its own panics to report both
states: its passing exit does **not** mean nil handling is correct. Separately,
the unchanged upstream `TestComposeDecodeHookFunc_NilValue` failed before and
passed after; ordinary composition remained passing. No full CI is claimed.

## Limited model comparison

A metadata-enrolled two-repair pilot froze source windows, questions, ordering,
action menus and output limits before model calls. Parent/head states are related,
not four independent repair groups. It used 31 calls and 38,476 reported tokens.
The owner constructed the questions/windows after seeing repair semantics. Both
revisions in each group have identical initial views but different correct
outputs: source-only cannot distinguish them from that evidence. This is a
partial-information diagnostic, not a held-out or all-context capability test.
With a common M3 final reviewer, exact-vector results across four states were:

| Evidence route | Exact states | Reported model tokens |
| --- | ---: | ---: |
| Initial source only | 0/4 | 2,746 |
| Next source window rule | 0/4 | 5,750 |
| Fixed native probe + reviewer | 4/4 | 2,848 |
| M3-selected observation + reviewer | 4/4 | 5,989 |
| GLM-selected observation + reviewer | 2/4 | 8,350 |
| Sequential act–observe GLM adaptation | 0/4 | 12,793 |
| Direct structured native values | 4/4 | 0 |

Every M3 selection chose native. The direct route shares the fixed-native
observations, not four additional independent runs. Six GLM selection attempts
hit the frozen 2,048-output-token limit, including a second step after acquiring
native evidence. Their final usage was retained, not counted as free failures or
retried. This does not rank the models' unrestricted reasoning capabilities.

The sequential route was a constrained Act-only adaptation discussed in
[ReAct](https://arxiv.org/html/2210.03629v3), not its full prompting method,
environment or benchmark. It did not yield a usable completed sequence here.
One repetition, common caps, different provider deadlines/tokenizers and unknown
prices/owner effort do not establish budget-matched general superiority. Probe
construction and setup remain outside the zero **model-token** figure. There
were no new PRs, recall measurement or unseen-group efficacy claims.

The next study should test contract/reachability judgments and diverse native
costs or availability, retaining the fixed-native competitor. Merely predicting
deterministic outputs cannot establish improved OSS discovery. The native probes
above reproduce the facts, not the entire private model-call experiment.
