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
