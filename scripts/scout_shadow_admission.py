"""Bounded read-only capacity wait for a shadow experiment, not a reservation.

Freeze cases independently of this observation. Waiting before a request is not
retrying a failed request. This never dispatches, restarts or changes Scout.
"""
import math
import time


def observed_capacity(runtime, now, *, max_active=14, max_age=30):
    if not isinstance(runtime, dict):
        return "INVALID_RUNTIME"
    if runtime.get("state") != "RUNNING":
        return "NOT_RUNNING"
    active, limit = runtime.get("active"), runtime.get("admission_limit")
    heartbeat = runtime.get("heartbeat_at")
    cooldown = runtime.get("cooldown_until")
    if (type(active) is not int or type(limit) is not int
            or not 0 <= active <= limit or not 1 <= limit <= 64
            or type(heartbeat) not in (int, float) or not math.isfinite(heartbeat)
            or (cooldown is not None and (type(cooldown) not in (int, float)
                                          or not math.isfinite(cooldown)))):
        return "INVALID_RUNTIME"
    if not 0 <= now - heartbeat <= max_age:
        return "STALE_RUNTIME"
    if runtime.get("memory_paused") is not False or runtime.get("disk_paused") is not False:
        return "RESOURCE_PAUSED_OR_UNKNOWN"
    if cooldown is not None and cooldown > now:
        return "COOLDOWN"
    if active > max_active or active >= limit:
        return "BUSY"
    return "OBSERVED_SPARE_CAPACITY"


def wait_for_capacity(read_runtime, *, max_wait=120, poll_seconds=2,
                      max_active=14, max_age=30, clock=time.monotonic,
                      wall_clock=time.time, sleep=time.sleep):
    """Return a bounded observation; caller must recheck immediately at dispatch.

    No calls are made here. A full/unknown runtime cannot be treated as a model
    failure or an accuracy verdict. Keep wait time and admission failures in costs.
    """
    if (type(max_wait) not in (int, float) or not math.isfinite(max_wait)
            or not 0 <= max_wait <= 600
            or type(poll_seconds) not in (int, float) or not math.isfinite(poll_seconds)
            or not 0 < poll_seconds <= 10 or type(max_active) is not int
            or not 0 <= max_active <= 63 or type(max_age) not in (int, float)
            or not math.isfinite(max_age) or not 0 < max_age <= 60):
        raise ValueError("invalid bounded observation budget")
    started = clock()
    observations = 0
    while True:
        observations += 1
        try:
            reason = observed_capacity(read_runtime(), wall_clock(),
                                       max_active=max_active, max_age=max_age)
        except (OSError, ValueError):
            reason = "RUNTIME_READ_FAILED"
        elapsed = max(0.0, clock() - started)
        if reason == "OBSERVED_SPARE_CAPACITY" or elapsed >= max_wait:
            return dict(status=reason if reason == "OBSERVED_SPARE_CAPACITY"
                        else "ADMISSION_WAIT_EXHAUSTED", last_observation=reason,
                        wait_seconds=elapsed, observations=observations,
                        atomic_reservation=False)
        sleep(min(poll_seconds, max_wait - elapsed))
