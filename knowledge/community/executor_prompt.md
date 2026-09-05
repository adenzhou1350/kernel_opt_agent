Act as the isolated executor for this materialized optimization trial.

1. Read and follow `input/prompt.md`, `input/task.json`, `input/environment.json`,
   `trial.json`, `source_receipt.json`, and `input/result.schema.json`.
2. Treat the current trial directory as the complete information boundary. Do
   not inspect its parent, sibling trials, any other checkout, Codex history, or
   network resource. The only editable production source is `source/`; place
   supporting measurements and logs under `evidence/`.
3. The source tree deliberately has no `.git` metadata. Do not initialize a
   remote or fetch anything. The source receipt binds the historical commit and
   every starting file; do not modify the receipt or any file under `input/` or
   `knowledge/`.
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
6. Your final response must be only one JSON object conforming exactly to
   `input/result.schema.json`. Copy the exact `trial_id`, `task_id`, and `arm`
   from `trial.json`. Evidence paths must be relative to the trial directory and
   their SHA-256 values must match the final files. Never invent a speedup,
   correctness result, elapsed time, or upstream-readiness claim.

The final JSON response will be saved directly as `result.json`; do not wrap it
in Markdown.
