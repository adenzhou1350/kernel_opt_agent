"""Windows commit headroom for bounded admission, not a memory-leak diagnosis."""

import sys

MIB = 1024 * 1024


def _windows_commit_pages():
    import ctypes
    from ctypes import wintypes

    class PerformanceInfo(ctypes.Structure):
        _fields_ = (
            [("cb", wintypes.DWORD)]
            + [
                (name, ctypes.c_size_t)
                for name in (
                    "CommitTotal",
                    "CommitLimit",
                    "CommitPeak",
                    "PhysicalTotal",
                    "PhysicalAvailable",
                    "SystemCache",
                    "KernelTotal",
                    "KernelPaged",
                    "KernelNonpaged",
                    "PageSize",
                )
            ]
            + [
                (name, wintypes.DWORD)
                for name in ("HandleCount", "ProcessCount", "ThreadCount")
            ]
        )

    info = PerformanceInfo()
    info.cb = ctypes.sizeof(info)
    if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
        raise ctypes.WinError()
    return info.CommitTotal, info.CommitLimit, info.PageSize


def available_commit_headroom_mb():
    """MiB below 90% system commit; None off Windows, -1 on probe failure.

    Physical availability and commit capacity are distinct. Do not relabel this
    as free RAM or change the supervisor's emergency ceiling.
    """
    if sys.platform != "win32":
        return None
    try:
        used, limit, page_size = _windows_commit_pages()
        if used < 0 or limit <= 0 or page_size <= 0:
            return -1
        return ((limit * 9 // 10) - used) * page_size // MIB
    except (OSError, ValueError, AttributeError):
        return -1


def commit_admits_call(headroom_mb, inflight, worker_mb=0, *, startup_mb=256):
    """Keep 512 MiB before the emergency ceiling plus pending startup charges.

    The default 256 MiB per-call floor covers cold backend startup more conservatively
    than its settled private memory. Already committed allocations may be
    charged twice; this is a safety budget, not a precise prediction. External
    workloads can still change pressure after admission. A separately verified
    SSH-only backend can specify a smaller local startup charge; the fixed
    512 MiB margin and system commit ceiling are unchanged.
    """
    return headroom_mb is None or headroom_mb >= 512 + (inflight + 1) * max(
        startup_mb, worker_mb
    )
