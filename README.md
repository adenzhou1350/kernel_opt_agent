# Kernel Optimization Agent

A small working kit for turning GPU and framework optimization ideas into
tested, reviewable changes. It gives a coding agent reusable lessons and
measurement tools while leaving analysis and implementation to the agent.

**The default is an ordinary PR workflow.** Detailed hardware modeling and
performance-limit certification are available when the problem needs them.

## Start

Python 3.10+ is enough for the lightweight commands; no model API, GPU framework,
database, scheduler service or agent framework is required to use the notebook
and knowledge search. Run these commands from the repository root:

```bash
python scripts/kernel_opt.py knowledge search "collective launch overhead"
python scripts/kernel_opt.py worklog init --run runs/my-optimization \
  --objective "Reduce overhead in the affected production path" \
  --source "repository URL and commit" \
  --workload "representative shapes, mode and numerical requirements" \
  --hardware "device and runtime version"
```

Run the repository's normal tests and benchmark in your chosen environment, then
record a result with its reproduction command and existing evidence:

```bash
python scripts/kernel_opt.py worklog record --run runs/my-optimization \
  --kind correctness --summary "Focused tests passed" \
  --evidence /path/to/test-output.txt --command "pytest tests/test_affected.py"
python scripts/kernel_opt.py worklog record --run runs/my-optimization \
  --kind decision --status INCONCLUSIVE \
  --summary "Correctness passed; representative workload comparison remains"
python scripts/kernel_opt.py worklog status --run runs/my-optimization
```

The notebook links and hashes evidence automatically. It does not execute the
recorded command, infer missing measurements, or certify a PR as Ready. Change
the source/workload/hardware descriptions to the actual experiment before
interpreting results. Unknown values remain explicit when starting discovery.

For an agent, point it at [AGENTS.md](AGENTS.md) and the
[kernel-optimizer skill](skill/kernel-optimizer/SKILL.md). Ask it to:

1. Confirm a correct baseline and the production path being optimized.
2. Test a small, high-value hypothesis using the cheapest informative experiment.
3. Validate correctness and compare representative baseline/candidate runs.
4. Deliver a focused PR or record why the candidate should stop.

## Reuse and contribute knowledge

Start with [knowledge/README.md](knowledge/README.md). The maintained shortlist
is in `knowledge/lessons/`: applicability, a useful lesson, exceptions and public
evidence. Search returns a few related entries; it never chooses the optimization
for you. Specialist archives, where present in your checkout, remain available
for explicit searches.

```bash
python scripts/kernel_opt.py knowledge search "graph mode latency"
python scripts/kernel_opt.py knowledge add --file /path/to/lesson.json
python scripts/kernel_opt.py knowledge check
```

Contribute a lesson with a small PR. Search first, reuse its stable ID when
improving an existing lesson, and explain which evidence changed the advice.
Upload reusable code and sanitized evidence; keep private logs, machine access
details, model downloads and raw profiles outside the PR. Git records revisions;
ordinary knowledge edits do not need a new versioned approval chain.

## Tools and research mode

For a new GPU, [hardware-aware profiling](hardware/PROFILING.md) can produce a
first-layer `HARDWARE.md` + `profile.json` briefing for a fresh agent: queried
capacities, observed topology, unknowns and the next useful measurements.
`hardware-profile inspect --cuda --topology` queries NVIDIA metadata without
compiling or running kernels; `handoff` and conditional `estimate` work offline.
No environment installation or automatic calibration is performed. Unsupported
fields stay unknown; documented capacities, empirical rates and operator timings
remain separate. This does not claim arbitrary-vendor support or an absolute optimum.

`python scripts/kernel_opt.py --help` shows the small default interface.
`python scripts/kernel_opt.py --all` lists optional and historical commands.
Existing command names and recorded research runs retain their meaning.

Useful specialist tools include paired sample analysis, source bundle transport,
runtime import checks, hardware queries and profiler analysis. Use whichever is
available in your checkout and relevant to the experiment. They are not a required
sequence. For an explicit lower-bound or performance-limit claim, use
[performance-limit research](skill/kernel-optimizer/references/limit_research.md).

## Layout

| Path | Purpose |
| --- | --- |
| `AGENTS.md`, `skill/kernel-optimizer/` | Short default instructions; opt-in research references |
| `knowledge/lessons/` | Reviewed, portable lessons shared through Git |
| `scripts/` | Notebook, retrieval and reusable measurement tools |
| `tests/` | Tests for maintained tools |
| `runs/` | Local experiment notebooks, commands and raw results |
| `hardware/`, `microbench/`, `schemas/`, `templates/` | Existing specialist research assets |

New runs and caches are ignored by Git. Previously tracked research material is
preserved for reproducibility; there is no automatic deletion or migration.
Historical community governance documents are records, not default instructions.

## Checks

```bash
python -B -m pytest -q -p no:cacheprovider tests/test_worklog.py tests/test_knowledge_notes.py
python -B -m pytest -q -p no:cacheprovider tests/test_hardware_probe.py tests/test_hardware_profile.py tests/test_hardware_cuda.py tests/test_hardware_topology.py tests/test_hardware_handoff.py
python scripts/kernel_opt.py knowledge check
```

See [REVIEW.md](REVIEW.md) for scope, tradeoffs and review guidance. Success is
measured by useful, correctly validated changes and avoided repeated mistakes,
not the number of cards, agents, test cases or generated documents.
