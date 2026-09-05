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

Never treat merge status, a PR author's benchmark, review approval or a method
match as proof that a technique improves the current target. Reverts, closed
changes, regression reports and contradictory reviews remain first-class
evidence and must not be filtered out of the source lake.

## Temporal A/B evaluation

Use `community-eval` to test whether the knowledge layer actually improves the
agent instead of merely producing plausible recommendations. A suite freezes a
cutoff, graph, task packet, hidden oracle, model/prompt identity, arm order and
candidate/compile/measurement/wall-clock budgets. Validation rejects training
snapshots captured after the cutoff and target PRs already present in the
training graph.

`materialize-trial` creates either a control directory with the community graph
withheld or an augmented directory containing only the frozen graph. It never
copies the hidden oracle. Run both arms with networking disabled, write their
raw `community-trial-result-v1` records and then assess and compare them:

```bash
python scripts/kernel_opt.py community-eval validate-suite \
  --suite /path/to/suite/suite.json --corpus /path/to/corpus

python scripts/kernel_opt.py community-eval materialize-trial \
  --suite /path/to/suite/suite.json --corpus /path/to/corpus \
  --task heldout-task --arm CONTROL --repeat 1 --output /path/to/control

python scripts/kernel_opt.py community-eval assess-trial --trial /path/to/control

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
