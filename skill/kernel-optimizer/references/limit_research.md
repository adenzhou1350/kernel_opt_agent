# Optional performance-limit research

Use this mode when the requested result is a justified performance bound,
architecture-level explanation or limit certificate. Ordinary PR delivery uses
the repository's short default workflow and does not inherit these requirements.

The existing strict pipeline remains:

`PLANNING -> BASELINE -> MODELING -> EXPERIMENT -> PRODUCTION_VALIDATION -> CERTIFICATION -> COMPLETE`

Create a research run using `scripts/kernel_opt.py new-run` and advance it with
`advance`; the validators preserve the original evidence requirements. Inspect
`--all` for optional commands. Do not relabel an incomplete historical run as
certified or migrate it by dropping failed gates.

Load references for the research question:

- [global_scheduler.md](global_scheduler.md): resource-model ownership and
  independent review when planning supervised research experiments.
- [modeling.md](modeling.md) and
  [microarchitecture_planning.md](microarchitecture_planning.md): mathematical
  work, dependencies, service rates, resource limits and schedule predictions.
- [instruction_analysis.md](instruction_analysis.md): final binary PTX/SASS
  evidence for instruction and resource claims.
- [microbenchmark_precision.md](microbenchmark_precision.md) and
  [optimization_workflow.md](optimization_workflow.md): measurement validity,
  controls, qualification and production comparisons.
- [evidence_grades.md](evidence_grades.md): what each level of evidence can prove.

A limit claim needs applicable lower bounds, a feasible upper bound, measured
uncertainty and a reproducible gap calculation. A fast benchmark or plausible
SASS explanation alone is not a proof. When those inputs cannot be obtained,
report the measured result and uncertainty without claiming optimality.

These documents describe strict research procedures. Their general-sounding
"every run" rules apply only to runs intentionally using this research mode.
Old community-cohort authorization and broker records are historical; follow
current shared-machine instructions for new executions.
