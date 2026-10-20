# Native feedback through an existing agent loop

This optional, no-model canary checks whether an actual sequential agent can
read source, receive a discriminating native test result, and stop. It uses the
unchanged `DefaultAgent` and deterministic **test model** from
[mini-SWE-agent 04d809c](https://github.com/SWE-agent/mini-swe-agent/tree/04d809ceab9df28f9adaed044884180159172930).
It does not replace that loop with our own action selector. Its custom
`Environment` sends only four reviewed command strings to an already configured
CPU agent-sandbox client. There is no host-shell fallback, provider connection,
package installation, network-dependent test, GPU use, or Scout queue mutation.

```sh
python -B examples/native-agent-loop/check.py \
  --source /path/to/reviewed/mini-swe-agent \
  --client /path/to/configured/agent-sandbox/client.py \
  --output /path/to/NEW/private-canary-output
```

Prerequisites are explicit, not installed by this example:

- The reviewed source root must contain `src/minisweagent`. The 16 import-path
  module hashes in `source_sha256.json` bind raw Git bytes from that commit.
  A Windows checkout with newline conversion will fail this check; use the
  existing [raw-Git source bundler](../../docs/scout_native_cpu_validation.md#commit-exact-source-before-native-validation)
  rather than weakening the hashes. No upstream source is copied into this repo.
- The trusted controller needs Pydantic, Jinja2, Rich, python-dotenv and
  platformdirs. Development used Python 3.14.3 and versions
  2.12.5 / 3.1.6 / 15.0.0 / 1.2.2 / 4.10.0 respectively. This is an import
  closure, not a complete official mini-SWE-agent installation or lockfile.
- The separately configured sandbox client exposes `call(action, arguments)`
  with `health/create/write/run/release`. Its own private connection configuration
  stays outside this repository. The example requires the CPU profile: offline,
  nonroot execution, read-only root filesystem, 512 MiB, one CPU and a real
  per-container 64-task cgroup limit. Every command gets a fresh container; only
  regular `/work` files persist. This is not equivalent to the upstream persistent
  Docker environment. No local WSL/Docker startup is performed by the example.

The known synthetic subject intentionally implements an exclusive slice end
incorrectly. The first native test must produce **one ordinary control pass and
one boundary failure**. Its nonzero exit and both test names must reach the
next scripted query. The submission marker must stop the real loop after three
queries. A separate one-query limit must stop before running the test again.
Finally, an owned sleep command times out: its container must be removed and
the adapter must classify that event as infrastructure failure, not a target
assertion or a no-bug result. The example's `fixture_checks.py` is intentionally
failing, so it uses a non-discovery filename and is invoked explicitly inside
the sandbox rather than joining ordinary repository test discovery.

The final public example passed all these assertions in a development run, with
five sandbox invocations and four scripted queries. It retained full broker
records, trajectories, source hashes, runtime versions and a release receipt.
The broker confirmed container removal for all five invocations and session
release. Earlier private local-driver failure, a private sandbox canary and the
public canary before its fixture-file rename are separate development work, not
extra independent study cases. The rename prevents accidental test collection;
the final version was checked in a fresh session with the same assertions.

`actual_model_api_calls` is zero. The upstream trajectory's `api_calls` field
counts scripted queries here; do not interpret it as paid/provider traffic.
The recorded wall interval excludes earlier diagnosis, source/dependency setup,
owner review and the final session release. No priced total-cost claim is made.

Infrastructure exceptions are terminal for this canary. After an uncertain SSH
result, use its saved session identity and the client's `history/evidence`
operations to resolve the same invocation; do not rerun into another directory
merely because observation timed out. No uncertain attempt is retried here.

The adapter joins captured stdout and stderr; it does not preserve their joint
chronology. This fixture does not require mixed-stream ordering. Any future
comparison requiring it must qualify a matching capture policy first.

This demonstrates a narrow execution capability, **not** an unmodified upstream
environment, real-model tool parsing, equal experimental budgets, arbitrary
model-command safety, full upstream tests, held-out discovery, improved recall,
PR conversion or paper novelty. Do not admit a new prospective cohort on this
component check alone; provider realization, matched action capacity, cost and
blinded miss auditing remain independent requirements.

A later [private real-provider compatibility check](../../docs/references/scout_source_inception_pilot_v2_results.md#real-provider-feedback-compatibility-known-fixture-check-2026-10-20)
used the unchanged upstream text parser and three actual Scout HTTP responses.
It verified that the native failure reached the next real request and that its
answer distinguished the control from the boundary failure. That separate run
does not turn this deterministic example into a provider integration test or
demonstrate action-selection effectiveness; no private connection settings or
raw provider traces are included here.

A subsequent [native function-calling component check](../../docs/references/scout_source_inception_pilot_v2_results.md#native-function-calling-path-qualified-component-2026-10-20)
used the unchanged installed `LitellmModel` instead of the text adapter. It
qualified tool-call IDs and native feedback on this same known fixture, while
retaining dependency, controller-configuration and malformed-command failures.
It required an explicit optional MCP dependency closure; it did not modify this
no-model example, make Scout depend on LiteLLM, or establish a matched discovery
benchmark. The source/dependency/command and accounting differences matter;
do not compare its five responses with the earlier three-response text check
as an effectiveness or cost result.
