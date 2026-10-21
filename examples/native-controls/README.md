# Native hypothesis controls

These are opt-in checks of real dependency behavior, not tests of this project's
ordinary import closure. Review the source and target environment before running
them; no package installation or environment provisioning is performed.

## HTTP upload URL ownership

`http_upload_url_checks.py` checks a specific Scout hypothesis: fsspec's
Requests-backed `put_file()` passes the URL directly, whereas other methods call
`encode_url()`. That difference alone does not prove a broken upload: Requests
also prepares URLs. The six explicit wire-path expectations are not calculated
by calling the same implementation under test.

Use an unmodified checkout of fsspec
`9704dd2a772c1f3380152ad692422660eda4b20e`, with its package and test fixture
importable. Pytest, requests and aiohttp must already be available. For example,
set `PYTHONPATH` to that absolute checkout path, change to a directory outside
it, then run:

```sh
python -m pytest -q /absolute/kernel_opt_agent/examples/native-controls/http_upload_url_checks.py
```

The actual fsspec clients send requests to a loopback-only instance of the
upstream `HTTPTestHandler`, not a stubbed `Session`. The server verifies actual
request method, encoded path and exact uploaded bytes. Tests also preserve
caller-owned streams and close their own sessions/server. The initial Windows
Python3.14.3 and Linux Python3.12.3 checks each passed all24 cases without skips;
the Linux receipt binds the original HTTP module/fixture bytes before and after.

That rejects this hypothesis only for these six URL vectors, two methods and
CPython clients. It is not a proof about every URL, `encoded=True`, signed URLs,
browser/Pyodide/JS behavior, real cloud storage, full CI, throughput or improved
Scout discovery/recall. New contract or transport evidence can reopen it. No
upstream repair PR follows from this passing control. Postman tooling was
unavailable due to a missing bundled dependency; this is a native loopback check,
not a Postman simulation/application-test result.

## Original urllib3 Retry-module capacity

Before adding HTTP-library work to Scout, the owner ran the complete original
`test/test_retry.py` from urllib3 commit
`ef8b211bc9cc688a7d68242fbfb583f545793293` on Linux CPython3.12.3: **66 passed,
zero skipped**. The original `conftest`, strict configuration/markers and socket
restrictions were retained. All178 tracked files matched a raw-Git source export
before/after; JUnit contained exactly the66 tests collected before execution.
This is one unchanged unit module, not a new fix, full nox/CI, HTTP2/TLS/server
qualification, Windows result, performance result or evidence-selection result.
The latest commit's Retry-After fix already belongs to upstream PR5310.

Reusable preparation details:

1. Use a fresh task-private environment, not an existing serving/SDK environment.
   Resolve the original `test` dependency group for the target interpreter and
   platform, keeping the project's source overrides. The observed Linux3.12
   resolution had41 dependencies; it is not a timeless lock or official CI lock.
2. This revision requires `urllib3/hypercorn`, resolved here to
   `d1719f8c1570cbd8e6a3719ffdb14a4d72880abb`, not the registry's same-version
   Hypercorn0.15.0. Build from raw-LF Git source; compare every tracked package
   member in the resulting wheel with its original Git blob. The two observed
   wheels matched37 urllib3 and39 Hypercorn files. Reject empty comparison sets.
3. Carry a reviewed fork wheel into pip's hash-checked requirements as an explicit
   file source, for example `hypercorn @ file:///absolute/private/hypercorn.whl`
   plus its actual `--hash=sha256:...`. Merely adding `--find-links` allowed pip
   to choose the distinct registry wheel and fail the hash check in this run.
   An additional bare CLI wheel argument also lacked its own required hash.
   Both failed preparations were preserved; neither ran target tests.
4. Build urllib3 with its unmodified Hatch/VCS hook and separately bind the
   generated `_version.py`; do not fake it to make imports pass. The shallow
   checkout produced `0.1.dev1`, not a published urllib3 release. Every tracked
   source byte still matched the pinned commit. Verify actual imported paths,
   the complete test dependency closure and `pip check` before claiming capacity.
5. From that exact source root, with `src` and the root on `PYTHONPATH`, run:

   ```sh
   python -B -m pytest -q test/test_retry.py --strict-config --strict-markers \
     --disable-socket --allow-unix-socket \
     --allow-hosts=localhost,127.0.0.1,::1,127.0.0.0,240.0.0.0 \
     --junitxml=/absolute/private/fresh-result.xml
   ```

Bound the reviewed test process separately (this run used two CPU affinities,
3GiB address space, a60s test deadline, CUDA hidden and clean owned process-group
exit). A private venv is not a sandbox for arbitrary model-generated code.
Acquisition/build/installation failures and costs remain separate from the
0.41s native test capture; that test duration is not end-to-end preparation time.
