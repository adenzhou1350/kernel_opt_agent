# Offline pytest startup with standard wheels

Use this optional route when an authorized CPU worker already has Python/pip but
cannot fetch dependencies. Prefer its normal offline installer over hand-picking
package directories: distribution files can include top-level modules, and
conditional dependencies depend on the **target** interpreter. This is a small
Python 3.12 pytest-stack example, not a replacement for a project's locked tool,
native dependencies, test command or contribution rules.

## Collect and review on a connected machine

Use a fresh task-private wheel directory. These explicit example versions were
replayed on Linux Python 3.12; choose the real target project's requirements.

```powershell
python -I -m pip --isolated download --index-url https://pypi.org/simple --only-binary=:all: --platform any --implementation py --abi none --python-version 3.12 --dest D:/your-private-task/wheels pytest==8.4.2 pytest-asyncio==1.2.0 pytest-mock==3.15.1 pytest-repeat==0.9.4 pytest-timeout==2.4.0 typing-extensions==4.15.0
```

Record every artifact's version, filename, size, source and SHA256; verify against
the intended publisher before transferring to the worker. Transitive versions
are not frozen by these six top-level pins. Preserve the complete wheel inventory
and target install report for an exact replay. Do not commit downloaded wheels,
credentials or raw worker records into this repository.

[Foreign download options](https://pip.pypa.io/en/stable/cli/pip_download/) select
compatible wheel tags/Requires-Python; do not infer complete target conditional
dependency resolution from a successful source-host download. The explicit
typing-extensions pin covers this example's Python-below-3.13 requirement.
Missing target artifacts must still fail at the target's offline resolver.

Transfer the reviewed wheels and `test_startup.py` using the task's existing
authorized transport. Check its real per-file limits first: the default small
CPU agent-sandbox also enforces a 1 MiB process file-size limit, including `/tmp`.
An intact Pygments wheel can exceed it even when uploaded in smaller chunks.
Retain that setup failure; use another authorized appropriate worker rather than
relaxing the sandbox, bypassing the limit or substituting an older dependency.

## Install and preflight on the authorized Linux worker

Here `TASK_ROOT` is an already created, fresh private task directory, **not** a
shared environment or workspace root. Verify its reviewed artifact hashes first.
Use reviewed code with bounded time/process/resource ownership; `--no-index`
restricts installer lookup but is not OS network or filesystem isolation.

```sh
TASK_ROOT=/path/to/your/fresh/private/task
test ! -e "$TASK_ROOT/deps" || exit 1
python3 -I -m pip --isolated install --no-index --find-links "$TASK_ROOT/wheels" --only-binary=:all: --no-compile --no-cache-dir --target "$TASK_ROOT/deps" --report "$TASK_ROOT/pip-report.json" pytest==8.4.2 pytest-asyncio==1.2.0 pytest-mock==3.15.1 pytest-repeat==0.9.4 pytest-timeout==2.4.0 typing-extensions==4.15.0 || exit 1
PYTHONPATH="$TASK_ROOT/deps" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -c /dev/null --rootdir "$TASK_ROOT" -o asyncio_mode=auto -o asyncio_default_fixture_loop_scope=function -p no:cacheprovider -p pytest_asyncio.plugin -p pytest_mock -p pytest_repeat -p pytest_timeout "$TASK_ROOT/test_startup.py" --junitxml="$TASK_ROOT/startup.xml"
```

Stop on nonzero setup **before** launching pytest. Check actual imported paths,
installed versions and the captured report, not only the installer exit code.
This stack has no required `.pth` processing; plain PYTHONPATH is not a general
substitute for site-directory initialization or a normal private environment.

The canary produces four cases: one synchronous fixture, one asynchronous/mock
fixture and two executions of the repeat-marked test. In the development replay,
all four passed. A separate fresh wheelhouse lacking typing-extensions failed
offline resolution on Python 3.12, even after removing the explicit top-level
pin: pytest-asyncio's conditional requirement remained. No project test launched
in that negative control. These are startup/delivery observations, not proof
pip resolves every possible project or that any candidate is correct.

Then run the real target tests with its config, plugins, exact source and public
caller contracts through the existing native capture tools. Keep acquisition,
transfer, installation, startup, target tests and owner effort separate. Two
already-known project selections were also replayed; this is not a new discovery,
prospective selector result, PR-yield improvement or measured cost advantage.
