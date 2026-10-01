# Native CPU tests before broadening Scout discovery

Add a repository when a supported baseline can actually run, not just because
source is available. A baseline may reveal a known upstream failure; retain it
and compare the same affected tests before/after a candidate. Do not suppress
warnings or weaken assertions to manufacture a green environment.

## HTTPX example

The [official contribution guide](https://www.python-httpx.org/contributing/)
routes installation through `scripts/install` and tests through `scripts/test`.
Its CI installs `requirements.txt`; `scripts/test` uses coverage + pytest when
`GITHUB_ACTIONS=true`. That flag deliberately omits the separate linting and
coverage-threshold steps. These commands are native tests, not complete CI.

Use a reviewed **full Git source export**, not one module over unrelated installed
siblings. Export with `git -c core.autocrlf=false archive` on Windows too; verify
important members against raw Git blobs. Keep `.git`, credentials, local config,
model weights and unrelated files out of the build context/source export.

Build the [example Dockerfile](../examples/scout-native-httpx/Dockerfile) with a
`source.tar` in its small task-private build context. The pinned Python 3.10 base
must already be cached. Installing public dependencies needs network only during
this secretless setup step; run project code only inside the container. Record
the resulting image ID and `/opt/dependencies.freeze.txt`. Upstream intentionally
leaves some dependencies unpinned: rebuilding later need not yield the same image.

For each complete baseline/candidate export, use the same immutable image:

```sh
docker run --rm --init --pull never --runtime runc \
  --network none --read-only --user 65534:65534 \
  --cap-drop ALL --security-opt no-new-privileges=true \
  --memory 768m --memory-swap 768m --cpus 1 --pids-limit 64 \
  --tmpfs /tmp:rw,nosuid,nodev,size=256m,mode=1777 \
  --mount type=bind,src=/absolute/source-export,dst=/input,readonly \
  --env HOME=/tmp --env GITHUB_ACTIONS=true --env PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint sh sha256:REVIEWED_IMAGE_ID -c '
    set -eu
    cmp /input/requirements.txt /opt/httpx/requirements.txt
    cmp /input/pyproject.toml /opt/httpx/pyproject.toml
    cp -R /input /tmp/source
    cd /tmp/source
    python -c "import httpx; assert httpx.__file__.startswith(\"/tmp/source/httpx/\")"
    sh scripts/test -m "not network" -q
  '
```

Do not mount the Docker socket, home directory or devices inside the container,
publish ports, or inherit operator credentials. Track the owned container ID and
bound its execution; on timeout inspect/stop only that container. HTTPX's local
test servers then use its private network namespace, not shared host ports.
Dependency-manifest drift needs a new reviewed environment, not an ignored `cmp`
failure. Extra candidate regressions can be passed to the native test script;
keep source/import provenance and both arms' results.

## Observed boundary, not a new bug or throughput claim

At HTTPX `b5addb64f0161ff6bfe94c124ef76f6a1fba5254`, Python 3.10.19,
pytest 8.4.1, Trio 0.31.0, AnyIO 4.15.1 and httpcore 1.0.9, the unmodified native
offline suite produced **1,412 passed, 1 failed, 5 deselected**. The failure was
`test_write_timeout[trio]`: `ByteStream.__aiter__` was finalized before exhaustion.
[PR #3777](https://github.com/encode/httpx/pull/3777) and
[PR #3700](https://github.com/encode/httpx/pull/3700) already cover this problem;
do not open a competing fix. This is not an environment-wide failure or proof of
an unrelated candidate. Keep the exact baseline failure visible.

The cached native test command took about 8 seconds in that one run; cold image
setup time was not recorded. This is not cold setup cost, a speedup, or Scout PR
conversion evidence. Five network-marked cases were not run; external network,
proxy behavior, other Python versions, lint, package/docs build and the 100%
coverage threshold remain separate checks. HTTPX generally asks for a prior
Discussion before escalation to an Issue/PR; verify current policy before posting.

This optional owner recipe does not add an automated delivery profile, enable
network in model-generated tests, or promote a candidate to Ready. Native capacity
and publication quality still require independent evidence for the actual lead.

## Optional delivery use of the reviewed HTTPX image

`kimi_scout_delivery.py --httpx-native` enables a **generated-test package screen**
for HTTPX only; it is off by default. The cached profile currently binds the
exact source revision above and image
`sha256:ad47b9d7b2ed3afc265fdf95732bd35527cdf092362ba4382c722949a36a4309`.
This is a locally reviewed image ID, not an image available for registry download.
Use the setup recipe before opting in; a rebuilt image or later source revision
requires its own reviewed identity rather than silently replacing this profile.

The controller passes the fetched revision, module path and baseline byte digest.
Each container checks its original module against that digest **before** loading
any candidate or generated test, copies the complete package into private scratch,
overlays only the selected file and checks package/subject import paths. Sibling
modules and dependencies are the same in both arms. Network, credentials, devices,
installation and host ports remain unavailable; memory is bounded at 768 MiB and
the delivery timeout remains 30 seconds per arm. Reserve sufficient controller
memory as well; the memory cap is not a proof of current host headroom.

For a reviewed local pair, the same route can be invoked directly:

```text
python3 -I -B scripts/kimi_scout_verify.py \
  --baseline /private/baseline.py --candidate /private/candidate.py \
  --test /private/test.py --profile httpx-cpu \
  --module-path httpx/_urlparse.py \
  --source-commit b5addb64f0161ff6bfe94c124ef76f6a1fba5254 --timeout 30
```

This is not HTTPX's full native pytest suite. Generated assertions and output
remain untrusted evidence, requiring owner review of the contract, actual caller,
duplicates, native tests and contribution policy. Missing images or mismatched
preimages/imports remain inconclusive, never a pass. Old blocked, reviewed or
published records are not reset or replayed when enabling the flag.

In an exposed IPv6 development case, the package screen ran three identical
tests per arm: baseline had two errors plus a passing normal control, candidate
passed all three; both owned containers were removed. A deliberately wrong
baseline stopped before testing in both arms. These checks establish runnable
capacity and rejection behavior, not prospective PR conversion or cost savings.

## Windows-native checks of owner-reviewed code

Local WSL is not required to test an already reviewed Python change. Use a fresh
Windows virtual environment and full source exports for both arms. This is an
owner-run test route, **not a sandbox for arbitrary Scout-generated code**. Do
not connect unreviewed queue entries to it or treat Python's `-I` flag as isolation.

For the URL tests, the native environment needs HTTPX's runtime dependencies
plus the upstream test/conftest dependencies: pytest, Trio, trustme,
cryptography, uvicorn and sniffio. Install them only into the task-private venv,
using the repository's tooling pins where present; record the resolved versions.
Do not silently use a global installed HTTPX in place of the exported package.

Export baseline and candidate with `git -c core.autocrlf=false archive`. Verify
changed source and test members against raw Git blobs before extracting. Place
the exact candidate regression test file in both trees; disclose that test-only
overlay on the baseline, leaving its production files unchanged. From each source
root, run the same private interpreter in separate processes:

```powershell
& $taskPython -B -c "import httpx; print(httpx.__file__)"
& $taskPython -B -m pytest tests/models/test_url.py -q -p no:cacheprovider
```

Check the reported import path lies inside that arm's source root. Retain both
results, failures and exact test bytes; a baseline failure unrelated to the
candidate is not test discrimination. This file-scoped command does not start
HTTPX's local test servers, run its full suite or establish CI/coverage completion.

At the same baseline `b5addb64` and reviewed bracketed-netloc change, Windows
CPython 3.12.13 with pytest 8.4.1, Trio 0.31.0, AnyIO 4.15.1 and httpcore 1.0.9
independently reproduced **14 IPv6 failures / 108 passes** on the baseline and
**122 passes** on the candidate. The same regression file was used for both
arms, both imports resolved into their full source exports, and no WSL or GPU
was used. This confirms that URL-test result across the two observed environments;
it is not an additional PR, a full-suite pass or a throughput measurement.

## Remote sandbox feasibility before model execution

Before moving automated delivery to a shared Linux worker, check that the
isolation backend really works, not only that Python or a container command is
installed. A reachable worker with ample storage is not automatically a verifier.
Do not install a privileged daemon, mount a host socket into generated tests or
fall back to running untrusted code directly as the SSH user.

If evaluating a namespace-based alternative, probe the actual namespaces the
backend requires. An observed worker allowed `unshare --user --map-root-user
--net true` but rejected the mount namespace with `cannot change root filesystem
propagation: Permission denied`. The first probe alone would falsely advertise
usable sandbox capacity. Keep such a worker ineligible for automatic execution
until a separately reviewed isolation policy and real canaries pass. Resource
limits, hidden host files/devices, network isolation, child cleanup and output
bounds remain necessary; namespace availability by itself proves none of them.
