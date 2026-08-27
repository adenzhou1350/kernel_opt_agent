# Mandatory intake

Open every new optimization run by requesting three inputs.  Display the
missing fields; do not silently inherit them.

## Operator computation

Capture equations or unambiguous pseudocode, tensor roles, shape/stride/dtype,
state transitions, masks and boundaries, numerical tolerance, aliasing,
lifetimes, public ABI, and transformations that are legal or forbidden.

## Target workload

Capture every shape that matters, its occurrence weight, operating modes,
upstream/downstream layouts, call frequency, graph/capture state, concurrency,
warm/cold-cache semantics and the latency statistic to optimize.  A shape list
without weights is not an end-to-end objective; label it as an unweighted grid.

## Target hardware

Capture the exact device or ask permission to discover it.  Include device
identity, architecture, driver/runtime/compiler, clocks and power policy,
available profilers/disassemblers, permitted programming models and whether an
architecture-specific implementation is acceptable.

If the user supplies a previous run, display its three identities and ask for
explicit confirmation before reuse.  Read-only discovery may fill hardware
fields, but discovery is not permission to compile or run expensive tuning.
