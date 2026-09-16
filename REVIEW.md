# Review guide

The default workflow supports a normal optimization PR: understand the target,
establish a baseline, test a focused change and report the result. It assumes a
capable coding agent and keeps bookkeeping out of its reasoning path.

## What to review

- `AGENTS.md` and `skill/kernel-optimizer/SKILL.md`: the default workflow should
  lead to code and measurements without requiring certification artifacts.
- `scripts/worklog.py`: a local notebook with explicit unknowns and evidence
  references. It records judgments; it does not certify their truth.
- `scripts/knowledge_notes.py` and `knowledge/lessons/`: small, inspectable search
  and contribution tools. Results expose conditions and sources, not authority.
- `scripts/hardware_probe.py`, `scripts/hardware_profile.py` and their tests:
  passive inventory and supplied-input resource arithmetic. Unsupported metadata
  stays unknown; empirical rates never become physical ceilings. This is not an
  automatic calibration service or an optimality certificate.
- `tests/test_worklog.py` and `tests/test_knowledge_notes.py`: executable examples
  of the default path, duplicate handling and malformed-input behavior.
- `skill/kernel-optimizer/references/limit_research.md`: intentional entry into
  the existing strict research workflow when a bound/certificate is requested.

## Compatibility and boundaries

Existing research tools, schemas and historical runs are retained. The default
CLI help is shorter; `--all` exposes the full installed command catalog. Legacy
commands remain callable and keep their original validation semantics. An old
run does not become qualified merely because the default instructions changed.

New experiments live under ignored `runs/`. Share compact, sanitized evidence
and reusable lessons through Git; keep worker addresses, credentials, weights
and large raw profiles private. Existing tracked evidence is not deleted.

A notebook ACCEPT is the operator's recorded decision, not automatic GitHub
Ready status. The target project's contribution rules and the claims actually
made determine the required tests and review. A knowledge entry's public source
may document a mechanism without proving a local speedup; preserve that boundary.

## Why retain optional tools?

Source identity checks, measurement analysis and resource modeling can answer
real questions. Requiring all of them for every change creates avoidable work.
The refactor removes that default requirement and keeps working tools callable.
Removing the legacy implementation wholesale would break recorded reproductions
without establishing any benefit to ordinary delivery.

Future additions should demonstrate a concrete reduction in repeated failure,
time to a correct result or validation cost. Compare workflow changes on new,
similar tasks with the same model and budget before claiming improved PR yield.
