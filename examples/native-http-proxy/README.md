# A real-HTTP proxy-boundary reproduction

This optional, owner-reviewed CPU example independently exercises the unmodified
Mooncake example proxy from [vLLM issue #62559](https://github.com/vllm-project/vllm/issues/62559).
It is a reproduction, not a fix or automatic Scout execution profile. Respect
target contribution rules and the report author's existing work; do not open a
competing PR from this example.

It starts three **owned loopback** Uvicorn services: a synthetic prefill service,
a synthetic decode service, and the real imported proxy. The ordinary proxy
lifespan creates its HTTPX pools and performs prefill discovery. No proxy
iterator, routing function, HTTP client or transport is replaced. Only P/D are
stand-ins; their unmodeled paths return 501. Test traffic contains no credentials
or real inference data. This is not GPU, RDMA, native transfer, inference,
connection-cancellation, private-fix or complete-vLLM qualification.

## Run in a fresh task directory

Use a reviewed Python environment with FastAPI, HTTPX and Uvicorn. Follow the
existing [offline-wheelhouse route](../native-python-wheelhouse/README.md) when
the worker cannot fetch packages. Standard installation into a task-private
`--target` directory is sufficient here; do not modify a shared environment.
Inspect wheel hashes, target dependency resolution and actual import paths.
The small installed CPU sandbox's 1 MiB per-file limit cannot accommodate this
Pydantic-core binary: use a suitable authorized native worker, not a relaxed
sandbox or split-file workaround.

Copy `test_proxy_wire.py` to a **fresh private directory**, and export the
reviewed raw proxy source there as `proxy.py`. Do not run in this example's
repository directory or reuse an old `wire.json`: the test writes that fresh
observation alongside itself with exclusive creation. On an authorized Linux
worker, with `AGENT_ROOT`, `VLLM_ROOT` and `TASK_ROOT` already set to their literal,
reviewed locations:

```sh
cp "$AGENT_ROOT/examples/native-http-proxy/test_proxy_wire.py" "$TASK_ROOT/test_proxy_wire.py"
git -C "$VLLM_ROOT" show 5fd62688ffe995c0c11c8708fe51dbff53235b74:examples/disaggregated/mooncake_connector/mooncake_connector_proxy.py > "$TASK_ROOT/proxy.py"
cd "$TASK_ROOT"
python -B "$AGENT_ROOT/scripts/scout_unittest.py" --report unittest.json test_proxy_wire -v
```

Use the matching interpreter and startup for the task-private dependencies.
`scout_unittest.py` is the existing observer; its output does not grant source
execution authority or prove full discovery. Bound the parent command's time,
memory, logs and process ownership, retain its exit, and stop only its children.
Each server has bounded startup/shutdown and each client request has a timeout;
these checks are not OS isolation. The example binds no public interface.

## Observed outcome and interpretation

The raw source at that revision is SHA256
`fea24b40fa8ea11d4757c3298271525fdfa16a01b57cc693c00785aa7c28e359`.
On Linux CPython 3.12.3 with FastAPI 0.136.3, Starlette 1.0.0, HTTPX 0.28.1,
HTTPcore 1.0.9, Uvicorn 0.40.0, Pydantic 2.13.5 and pydantic-core 2.46.5:

- Eight tests ran: **four assertion failures, four passes, no errors/skips**.
- For completion/chat × stream false/true with a decode HTTP 500, the client
  received HTTP 200 followed by `RemoteProtocolError`; it did not receive the
  JSON error. These are the discriminating failures, not a green bug verdict.
- All four healthy JSON/SSE route controls passed with exact body and media type.
- Eight P and eight D requests were observed, and all three owned server threads
  were stopped. Source and test bytes remained unchanged.

The result agrees with the reporter's ASGI/mock observation while adding a real
HTTP boundary and ordinary proxy startup. It does **not** reproduce the reporter's
private fix or their hardware tests. Four red assertions here are expected on
that baseline; do not turn them into green tests by expecting incorrect status.
Different versions, cancellation, prefill failures and transfer behavior require
their own evidence.

The run reused already recorded wheels through offline pip resolution, with no
new package download, model call or GPU work. Target tests took about 1.17 s and
installation about 0.77 s, excluding prior wheel acquisition, transport and owner
work. These are not total-cost or PR-conversion measurements. This exposed
public-report validation is not a fresh prospective-study group or new discovery.
