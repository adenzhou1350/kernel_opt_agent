# FlashInfer CAKE import preflight

Before reserving an SM100/SM103 GPU or compiling attention kernels, run this
small check with the intended worker interpreter and reviewed source. It hashes
the selected launcher before import, hides CUDA, isolates the FlashInfer cache,
records installed distribution versions and bounds captured output in memory.
The process executes source; this is not a security sandbox. The timeout bounds
the import process, not arbitrary descendant processes or disk output volume.

```sh
python check_cake_import.py --source /path/to/flashinfer \
  --source-sha256 SHA256_OF_RAW_LAUNCHER_BYTES
```

For a source checkout that includes its own compatible JIT-cache shim, explicitly
select and hash it as well. Do not disable version checks or invent provider APIs:

```sh
python check_cake_import.py --source /path/to/flashinfer \
  --source-sha256 SHA256_OF_RAW_LAUNCHER_BYTES \
  --jit-cache-source /path/to/flashinfer/flashinfer-jit-cache \
  --jit-cache-sha256 SHA256_OF_RAW_SHIM_INIT_BYTES
```

Development check at `ac30bfabfc40cca1971bea7a41ac10e6960d6bfd`:
the launcher hash is `b5f612c81011566511979f6ef7de98526f8e12f8b2c37995c8fd7b38b32d386f`
and shim hash is `6d1df56aee32df968bf93e67185be36385544abbec53978c07372efb8b61931e`.
An installed 0.6.12 JIT-cache shim lacks `get_jit_cache_providers`; explicitly
selecting the same-source shim passed that import boundary, but an older installed
CUTLASS DSL then lacked `cute.FastDivmodDivisorV2`. This is an environment block,
not evidence that a CAKE kernel is wrong. No GPU input or malformed kernel was
launched. A passing import would still not prove dependency completeness, source
submodule materialization, native kernel correctness, graph safety or throughput.

Sparse checkout note: absent checkout paths do not prove absent Git-tree paths.
The shim and review guidance existed in the pinned tree although excluded locally.
Inspect `git ls-tree`, `git show` and `git sparse-checkout list` before deciding to
recreate a module or declare contribution instructions unavailable.
