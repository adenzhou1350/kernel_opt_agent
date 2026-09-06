Act as the isolated executor for this materialized optimization trial.

1. Read and follow `input/prompt.md`, `input/task.json`, `input/environment.json`,
   `trial.json`, `source_receipt.json`, `input/result.schema.json`, and any
   hash-bound task support under `harness/`.
2. Treat the current trial directory as the complete information boundary. Do
   not inspect its parent, sibling trials, any other checkout, Codex history, or
   network resource. The only editable production source is `source/`; place
   supporting measurements and logs under `evidence/`.
   When `harness/` provides a baseline snapshot/bootstrap operation, run it
   before the first production-source edit. Use the supplied correctness and
   timing driver instead of rebuilding equivalent scaffolding. A task-specific
   harness is a shared measurement instrument, not a candidate suggestion.
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
   - Before consulting any prior, record a `prior_gate` beside the opportunity
     ranking: diagnosis confidence, the leading local candidate, its expected
     ceiling, the largest unresolved risk, and whether knowledge has positive
     expected value. A high-confidence structural candidate may be screened
     first. Consult knowledge only when the diagnosis is uncertain, the local
     candidate fails, or its measured result leaves a material gap to the
     defensible bound. Knowledge availability alone is not a reason to read it.
   - In a COMMUNITY_AUGMENTED trial whose gate opens, spend at most 10% of the
     wall budget on retrieval. When `knowledge/prior_shortlist.json` exists,
     inspect it first and do not scan the full graph or method snapshot unless
     the shortlist records a named unresolved uncertainty requiring one
     additional lookup. Inspect one
     applicable event card first and a second only if it resolves a named
     uncertainty. If `knowledge/methods.json` exists, apply the same rule to at
     most two method cards whose problem signatures and hard requirements match
     the frozen opportunity. Prefer cards with an
     explicit `algorithmic_decomposition`: instantiate its partition axis,
     local state, combine rule, and finalization for this operator before
     tuning launch parameters. If a method is selected, either evaluate at
     least one production candidate that materially realizes that instantiated
     decomposition or write hash-bound evidence showing why the decomposition
     is structurally infeasible under the frozen correctness/ABI contract.
     Falling back to a familiar implementation does not count as method
     realization. Method cards are discovery priors, never target performance
     evidence.
   - Record `PRIOR_GATE_CLOSED` when local evidence makes retrieval negative
     expected value. Otherwise record `NO_RELEVANT_COMMUNITY_PRIOR` and/or
     `NO_RELEVANT_METHOD_PRIOR` independently when the corresponding source has
     no applicable entry. Do not force an unrelated analogy merely to claim
     that knowledge was used. A prior-selected candidate must displace or
     materially modify the frozen local plan; merely attaching a method label
     to the same candidate does not count as realization.
   - Do not spend more than two evaluated candidates in one architecture
     family without a measured material improvement. After that, change the
     work decomposition or stop that branch. Stop candidate search by the
     runner's explicit phase deadline and reserve at least the final 30% of wall
     time for one held-out pass, evidence hashes, and a valid conservative
     result. Optional prose is the first thing to drop near the deadline.
   - Stop early when the measured result reaches the task's defensible bound,
     or when all remaining candidates have an estimated ceiling below the
     frozen material-speedup threshold. Record why stopping is rational.
7. Your final response must be only one JSON object conforming exactly to
   `input/result.schema.json`. Copy the exact `trial_id`, `task_id`, and `arm`
   from `trial.json`. Evidence paths must be relative to the trial directory and
   their SHA-256 values must match the final files. Never invent a speedup,
   correctness result, elapsed time, or upstream-readiness claim. When the
   trial exposes `method_snapshot`, populate `method_realization`: list at most
   two inspected IDs and report exactly one of `NO_RELEVANT_METHOD_PRIOR`,
   `REALIZED_IN_CANDIDATE`, or `STRUCTURALLY_INFEASIBLE`. A realized method must
   reference its actual candidate IDs and evidence; an infeasibility claim must
   reference evidence. Omit this field when no method snapshot is exposed.

The final JSON response will be saved directly as `result.json`; do not wrap it
in Markdown.
