Act as the isolated executor for this materialized optimization trial.

1. Read and follow `input/prompt.md`, `input/task.json`, `input/environment.json`,
   `trial.json`, `source_receipt.json`, `input/result.schema.json`, and any
   hash-bound task support under `harness/`.
2. Treat the current trial directory as the complete information boundary. Do
   not inspect its parent, sibling trials, any other checkout, Codex history, or
   network resource. The only editable production source is `source/`; place
   supporting measurements and logs under `evidence/`.
3. The source tree deliberately has no `.git` metadata. Do not initialize a
   remote or fetch anything. The source receipt binds the historical commit and
   every starting file; do not modify the receipt or any file under `input/` or
   `knowledge/` or `harness/`.
4. Treat `input/environment.json` as the pre-trial runtime probe. Do not spend
   technical-repair budget rediscovering a listed missing tool or incompatible
   compiler path. Use its frozen `runtime_paths` mapping when present; do not
   invoke `wslpath` or probe other mounted paths. Bound every potentially
   blocking subprocess by `budget.max_command_seconds` (for WSL, invoke the
   workload through `timeout`). A command timeout is a failed command and a
   technical repair; stop the trial if another attempt would exceed the repair
   budget.
5. Enforce every count and wall-clock limit in `trial.json`. A build or runtime
   repair is not a causal performance result. Screen correctness before timing,
   use interleaved measurements, and retain raw evidence for each reported
   number. The execution auditor treats every failed or declined shell command
   as at least one technical repair. Stop before starting a command that could
   make that lower bound exceed `max_technical_repairs`.
   A candidate that compiles and runs but fails correctness or performance is
   a causal screening result, not a broken harness. Screening drivers must
   catch that outcome, write a structured `FAIL` record, and exit zero. Reserve
   nonzero process exits for compiler/import/timeout/harness failures. Never use
   an uncaught assertion to report an ordinary candidate rejection.
6. Use a staged search policy rather than reading every available idea up
   front:
   - First inspect the task and hot-path source, then freeze a short opportunity
     ranking under `evidence/` with the suspected global bottleneck, an upper
     bound, and at least one structural alternative. Do this before consulting
     community knowledge so the prior cannot replace target reasoning.
   - In a COMMUNITY_AUGMENTED trial, query the graph narrowly after that
     ranking. Inspect at most two applicable event cards first. If no event
     shares the target mechanism and satisfies its hard requirements, record
     `NO_RELEVANT_PRIOR` and continue from target evidence; do not force an
     unrelated analogy merely to use the graph.
   - Do not spend more than two evaluated candidates in one architecture
     family without a measured material improvement. After that, change the
     work decomposition or stop that branch. Reserve the final 20% of wall
     time for held-out correctness and integration evidence.
   - Stop early when the measured result reaches the task's defensible bound,
     or when all remaining candidates have an estimated ceiling below the
     frozen material-speedup threshold. Record why stopping is rational.
7. Your final response must be only one JSON object conforming exactly to
   `input/result.schema.json`. Copy the exact `trial_id`, `task_id`, and `arm`
   from `trial.json`. Evidence paths must be relative to the trial directory and
   their SHA-256 values must match the final files. Never invent a speedup,
   correctness result, elapsed time, or upstream-readiness claim.

The final JSON response will be saved directly as `result.json`; do not wrap it
in Markdown.
