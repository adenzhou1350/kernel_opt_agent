# Native sqlparse verification

This optional discovery profile targets public `parse`, `split` and `format`
behavior in [sqlparse](https://github.com/andialbrecht/sqlparse). It is a
**non-validating** parser: accepting malformed SQL is not a defect by itself.
Use the real package and its tests, not a reconstructed tokenization helper.
Respect existing grouping depth/token guards and avoid unbounded stress inputs.

Use a private checkout/environment with Python >=3.10 and pytest available:

```text
git clone --config core.autocrlf=false https://github.com/andialbrecht/sqlparse.git sqlparse-native
cd sqlparse-native
git checkout --detach REVIEWED_COMMIT
python -B -c "import sqlparse; print(sqlparse.__file__)"
python -B -m pytest tests -q --junitxml=/path/to/private-baseline.xml
```

The imported module must lie inside that checkout. Check tracked source bytes
against the chosen Git objects when exporting between Windows and Linux. Record
Python/pytest versions and preserve failed, skipped, xfailed and xpassed results.
The recorded baseline disables ambient plugin autoload with
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and bytecode writes with
`PYTHONDONTWRITEBYTECODE=1`; set these per child, not globally for other tasks.
Use the same source/dependencies for both arms except the reviewed change, and
verify affected public behavior with a regression that fails before the fix.
Keep caches/output task-private. No local WSL or GPU is needed; repository
tests still execute trusted native Python and require an owner-reviewed scope.

At `60cdc649726bf1bc4f1b336050560b336da715ec`, the unchanged Windows-native
Python 3.14.3 / pytest 9.0.3 baseline completed with **506 passed, 2 xfailed,
1 xpassed**. This is environment/testability evidence, not a discovered bug,
candidate qualification, cross-version guarantee or throughput result. Recheck
source/dependency drift rather than treating these counts as a permanent oracle.
Read the current AGENTS.md, CONTRIBUTING.md and PR template; check related work
before publication. The profile does not automatically execute generated tests
or authorize a PR.
