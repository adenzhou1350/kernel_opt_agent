# Optional remote tool-free backend

Keep the SQLite queue, source retrieval and dashboard on the controller. Move
only Kimi SDK calls to an authorized Linux host when local SDK processes consume
scarce commit capacity. This is not a GPU worker or a publication agent.

Provision a fresh private directory (mode 0700) with:

- `venv/bin/python`: isolated environment with exact Kimi 1.30.0 metadata and its
  tool-free SDK (`kosong==0.48.0`, `httpx==0.28.1`, `loguru==0.7.3`); a wheel-only
  `kimi-cli --no-deps` install plus these SDK dependencies avoids unnecessary
  full-CLI packages. This subset does not support the Kimi agent/CLI entrypoint;
- `scripts/kimi_scout_backend.py`, `kimi_scout_resident.py`, `kimi_scout_remote.py`;
- `provider.toml` (0600): only default model, its model name and API-key provider;
- private `tmp/` and `cache/` directories.

Explicit user authority is required before moving credentials. Do not copy an
entire Kimi home, OAuth tokens, agent configuration, MCP, plugins or GitHub keys.
Verify transferred source hashes, installed dependencies, and the backend's
`--check --config-file ...` before a bounded real call. Pin the authorized SSH
host key in a controller-owned known-hosts file; do not disable verification.

The local transport JSON contains exactly `host`, `port`, `root`, `known_hosts`.
It contains no API key. `root` is the remote absolute private directory;
`known_hosts` is the local absolute pinned file. Keep deployment identities and
all credentials out of Git. Select it with `run --remote-backend <transport>`
instead of `--resident-backend`. `--kimi-python` remains accepted for compatibility
but the SDK interpreter used by this mode is the remote private venv.

At most 16 owned SSH workers reuse imports for 32 independent calls each. No
conversation state or tools are shared. A failed/ambiguous call is never replayed
by the transport. The existing queue failure/cooldown policy remains in effect.
Closing SSH stdin ends its remote Python process even during an API call; an
idle worker exits after five minutes. Only these owned processes are closed.
Remote admission checks available RAM (including cgroup-v2 limits) and disk
before each call. CUDA is hidden; no GPU or system environment is modified.

Local progress exposes requesting and terminal answer phases, not live remote
token streaming. Usage/finish reason remain provider-reported. Requests and
results stay in the existing local record; the remote worker does not save them.

Keep local physical/disk and commit protection enabled. Remote mode uses a
64 MiB local SSH startup floor instead of the local SDK's 256 MiB floor, while
retaining the 512 MiB margin below the 90% commit ceiling. Set worker RAM to a
verified local SSH budget, not the remote SDK footprint. External host pressure
can still pause the controller; migration does not fix kernel-pool growth or
guarantee continuous concurrency. Measure both hosts before increasing load.
