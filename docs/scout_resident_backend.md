# Bounded tool-free backend reuse

Scout's `run --resident-backend` is opt-in. The default remains one isolated
Python backend process per request, useful as a comparison or rollback path.
Neither mode starts local WSL, enables model tools, executes suggested tests,
publishes contributions, or authorizes GPU use.

Resident mode keeps at most `--concurrency` owned children (maximum 16), lazily
started with the configured Kimi Python's `-I -B` flags. Each child retires after
32 requests; any unsuccessful completion or protocol/transport failure retires
it earlier. Configuration and Python/SDK imports are reused, **not conversations**.
Each call still creates and closes its own provider HTTP client and stream.
Credentials never enter the controller's request/response protocol.

The existing request, token, evidence, tool-denial and progress-output checks
remain in effect. JSONL frames are bounded and request IDs must match. The
controller deadline includes queueing and pipe writes, not just provider time.
A timeout or malformed response kills only the owned child and records failure;
it does not replay a request whose provider completion may be unknown. An
operator can investigate before explicitly choosing any later work.

Runtime output records `backend_mode` and `backend_process_starts`. A normal
shutdown drains in-flight tasks, then closes its resident children. Keep existing
memory/disk guards and independent supervision: fewer process starts is not proof
that a Windows kernel-pool leak is fixed, nor of increased PR quality. Profile
host memory and actual candidate outcomes separately. Resident imports also hold
memory while idle, so measure both retained memory and startup churn.

Offline tests use native fake subprocesses and cover recycling, concurrency,
cross-wiring, broken/oversized replies, blocked stdin, hard deadlines, no replay,
server frame checks, no conversation history and real controller persistence.

```powershell
python -B -m unittest discover -s tests -p test_kimi_scout_resident.py
python -B -m unittest discover -s tests -p test_kimi_scout_backend.py
python -B -m unittest discover -s tests -p test_kimi_scout.py
python -B -m unittest discover -s tests -p test_kimi_scout_cooldown.py
```

These test entry points resolve this checkout's scripts themselves; no external
workspace or `PYTHONPATH` is needed. The controller CLI also resolves its sibling
modules when run normally (`python scripts/kimi_scout.py --help`). Python's `-I`
flag is for the self-contained backend, not the controller script's CLI.

Use an already configured Kimi installation for a separately budgeted live trial.
Offline fake-provider tests are not API throughput, long-run memory or scientific
comparison evidence. Keep raw local trial records and credentials out of Git.
