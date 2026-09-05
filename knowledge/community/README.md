# Community optimization evidence

Community pull requests are discovery evidence, not target-hardware performance
proof. The reusable representation has two layers:

1. An immutable `community-pr-snapshot-v1` bundle containing the pull request,
   complete diff, changed-file metadata, commits, issue comments, reviews,
   review comments and timeline. Every artifact is SHA-256 bound.
2. A reviewed `community-optimization-event-v1` that explains the baseline,
   transformation, removed and added work, applicability, bottleneck shift,
   limitations and source-reported measurements. Every claim points back to a
   snapshot artifact hash and locator.

Generated corpora do not belong in this source directory. Capture them into a
run-owned or external corpus directory:

```bash
python scripts/kernel_opt.py community capture-pr \
  --repository vllm-project/vllm --number 48870 \
  --corpus /path/to/community-corpus

python scripts/kernel_opt.py community sync-repository \
  --repository vllm-project/vllm \
  --since 2026-08-01T00:00:00Z --until 2026-09-01T00:00:00Z \
  --max-captures 20 --corpus /path/to/community-corpus \
  --receipt /path/to/sync-receipts/vllm-2026-08.json

python scripts/kernel_opt.py community validate-corpus \
  --corpus /path/to/community-corpus

python scripts/kernel_opt.py community build-graph \
  --corpus /path/to/community-corpus \
  --repository vllm-project/vllm \
  --repository sgl-project/sglang \
  --repository kvcache-ai/Mooncake \
  --output /path/to/community-graph.json

python scripts/kernel_opt.py community attach-graph \
  --run runs/<run-id> --graph /path/to/community-graph.json \
  --corpus /path/to/community-corpus
```

`sync-repository` searches an explicit, closed update window, classifies
performance changes, regressions, reverts, kernel/runtime work and data-movement
changes, then captures at most the declared PR budget. The receipt records every
matched candidate, budget skip, query URL and whether GitHub truncated search
coverage. Feed its `next_since` into the next scheduled window; never silently
advance a cursor after a failed run.

Never treat merge status, a PR author's benchmark, review approval or a method
match as proof that a technique improves the current target. Reverts, closed
changes, regression reports and contradictory reviews remain first-class
evidence and must not be filtered out of the source lake.

Event cards also declare machine-readable hard requirements for compute
capability, explicit parallel width and workload context. Routing fails closed
when those requirements are missing or contradicted, and records the rejected
event plus blockers instead of letting topical similarity create an invalid
candidate. `COMPLEMENTS` means implementation-composable; mutually exclusive
representations must use `CONFLICTS` even when they address the same bottleneck.

## Temporal A/B evaluation

Use `community-eval` to test whether the knowledge layer actually improves the
agent instead of merely producing plausible recommendations. A suite freezes a
cutoff, graph, task packet, hidden oracle, full source revision, model/prompt identity,
arm order and candidate/compile/measurement/per-command/wall-clock budgets.
Validation rejects training
snapshots captured after the cutoff and target PRs already present in the
training graph.

The suite also freezes a `minimum_material_speedup` greater than 1.0. The
assessor uses this threshold for time-to-first-improvement so a nominal 1.001x
result inside timing noise cannot count as successful discovery.

`materialize-suite` uses the suite's frozen random seed to create every task,
repeat and arm in a hash-bound execution schedule. A control trial withholds the
community graph; an augmented trial contains only the frozen graph. Neither arm
receives the hidden oracle. Each trial also carries a hash-bound JSON result
contract so an isolated executor does not have to guess the reporting format.
The materialized executor prompt also freezes the filesystem boundary, runtime
adapter and evidence-writing rules shared by both arms.
Execute `schedule.json` in order with networking
disabled. Before execution, materialize the exact historical commit from a local
repository into each trial. The source receipt binds the commit, Git tree and every
extracted file hash, and validation rejects later source edits. On Windows, Git
symlinks are materialized as inert target-text blobs rather than live links so they
cannot escape the trial root; the original Git tree identity remains bound. Write each raw
`community-trial-result-v1`, then assess and compare:

```bash
python scripts/kernel_opt.py community-eval validate-suite \
  --suite /path/to/suite/suite.json --corpus /path/to/corpus

python scripts/kernel_opt.py community-eval materialize-suite \
  --suite /path/to/suite/suite.json --corpus /path/to/corpus \
  --output /path/to/materialized-schedule

python scripts/kernel_opt.py community-eval validate-schedule \
  --schedule /path/to/materialized-schedule/schedule.json

python scripts/kernel_opt.py community-eval prepare-source \
  --trial /path/to/materialized-schedule/trials/001-control \
  --repository /path/to/local/source-repository

python scripts/kernel_opt.py community-eval validate-source \
  --trial /path/to/materialized-schedule/trials/001-control

python scripts/kernel_opt.py community-eval audit-execution \
  --trial /path/to/materialized-schedule/trials/001-control \
  --sandbox-mode AUDITED_UNRESTRICTED

python scripts/kernel_opt.py community-eval assess-trial --trial /path/to/control \
  --require-execution-audit

python scripts/kernel_opt.py community-eval compare \
  --control /path/to/control --community /path/to/community \
  --output /path/to/paired-report.json
```

The assessor derives time-to-first-correct, time-to-first-improvement, best
speedup, architecture-family coverage, held-out correctness, whole-model
speedup and upstream readiness from candidate-level evidence. It rejects stale
hashes, incomplete upstream claims and any trial that exceeds its frozen
budget. A paired report is scoped to one task and repeat; repeated-task
statistics must not be inferred from a single pair.

`audit-execution` independently parses Codex JSONL rather than trusting the
Agent's final summary. It rejects incomplete turns, missing/invalid results,
network or remote-Git commands, parent/external data paths and a failed-command
lower bound above the frozen technical-repair budget. An audited unrestricted
run is therefore evidence only when its complete transcript passes this gate.
Strict assessment additionally binds the passing audit to the current trial and
result hashes, so editing a result after audit cannot silently enter a comparison.
