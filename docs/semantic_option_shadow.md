# Optional semantic routing probe

Use `scripts/semantic_option_shadow.py` to measure a typed-option scorer before
adding it to a research queue. It uses the Python standard library, reads a JSONL
fixture and calls a caller-supplied `/v1/score` endpoint. Each case is scored in
forward and reverse option order. No Scout database or queue is changed.

```sh
python scripts/semantic_option_shadow.py \
  --input docs/semantic_option_synthetic_cases.jsonl \
  --endpoint http://127.0.0.1:8877/v1/score \
  --health-url http://127.0.0.1:8877/health \
  --output runs/semantic-shadow/report.json
```

The supplied examples are authored synthetic cases, useful for checking the
interface rather than estimating real accuracy.
Use `--unlabeled` for a JSONL file with `expected_action` omitted. Other fields
are `id`, `question`, `state`, `options` (`id` and `description` per option), and
`data_classification` (`synthetic` or `public_sanitized`). Inputs are bounded at
6,000 state characters and 2–12 options. Send only suitable public or sanitized
content to the selected endpoint.

The report checks option identities and normalized finite probabilities, retains
both probability distributions, and reports action disagreement, probability
total variation and client request p50/p95. Failed calls remain in latency
accounting and make the report incomplete. Without labels, correctness counts
are null. A model's normalized option probability is not a calibrated probability
that a candidate is correct, valuable or ready for a PR.

## Development observations and decision

A local 2026-09-30 probe selected one immutable public source window from each
of 12 repositories in an existing frozen development draw, without consulting
later outcomes. It used MiniCPM5-2B revision
`12a3808a956f869c767195e9266b59c4d21d92e2` with SemIf commit
`23cf1f39fc9534fe81437200959b6dfc7106e45a`.

Warm sequential request p50 was about 75–81 ms; p95 was 93–113 ms across the
development variants. All 12 windows selected more source inspection in both
orders. Removing an explicit missing-caller reminder preserved those choices.
This agrees with a constant `inspect` policy on this sample and does not
demonstrate better prioritization. Scores still changed: one window's probability
for `reproduce` fell from 0.2015 to 0.02286 when options were reversed, despite
an unchanged winning action. Checking the winning action alone hides this
instability.

These are small, exposed, incomplete-source cases without independent action
labels. They measure neither accuracy nor PR conversion, and exclude model
loading, resident service cost and throughput under concurrency. Raw runs and
service addresses remain local.

Keep semantic scores advisory until they improve a blinded real-case comparison
against rules and a cheap-model handoff. Freeze pre-decision evidence and
acceptable next actions, allow several reasonable actions, and measure valuable
lead recall, total cost and time to independent reproduction. Keep source and
environment blockers separate from candidate value. Stable option choices alone
do not justify confidence thresholds or automatic rejection.
