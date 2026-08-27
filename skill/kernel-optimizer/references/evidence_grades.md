# Evidence grades and invalid methods

## Grades

- `FACT`: device query, source hash, ABI or static instruction fact.
- `MEASURED`: immutable raw data with measurement semantics and environment.
- `INFERRED`: calculation whose inputs and assumptions are cited.
- `HYPOTHESIS`: prediction with a proposed falsification test.
- `REJECTED`: invalid method or disproved hypothesis retained as a negative
  control.

## Common invalid measurements

- CUDA events enclosing CPU-paced serial launches can include GPU idle gaps.
- A graph replay is invalid when capture contains no native kernel nodes.
- Loads whose values are not consumed may be deleted by the compiler.
- A cache-resident curve must not be labeled DRAM bandwidth.
- Kernel completion does not prove write persistence at DRAM.
- Unmatched grid, block, shared-memory, layout or ABI invalidates subtraction.
- First-use compilation, module loading or attribute setup is not steady GPU
  active time, but may be relevant to end-to-end cold-start latency.
- DVFS, power throttling and competing processes require rejection or explicit
  classification, not post-hoc explanation.

Always retain raw samples and negative controls.  A monotonicity check, kernel
count check and correctness sink are minimum gates for service curves.
