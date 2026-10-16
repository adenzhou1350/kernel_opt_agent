"""Conservative Linux RAM headroom, including visible cgroup-v2 ancestors.

Read only; never reclaim caches or change limits. This is a racy admission
observation, not an allocation guarantee or a diagnosis of process leaks.
"""
from pathlib import Path, PurePosixPath
import re

MIB = 1024 * 1024


def supervisor_memory_action(available_mb, *, admission_floor_mb, critical_floor_mb):
    """Separate a recoverable admission pause from a terminal owned drain.

    The controller must still enforce its worker reservations and admission
    floor. This only guides supervision: it never allocates, restarts a child,
    clears STOP, replays work or changes cgroup limits.
    """
    if (type(admission_floor_mb) is not int or type(critical_floor_mb) is not int
            or not 0 < critical_floor_mb <= admission_floor_mb):
        raise ValueError('require 0 < critical floor <= admission floor in MiB')
    if type(available_mb) is not int or available_mb < critical_floor_mb:
        return 'DRAIN'
    if available_mb < admission_floor_mb:
        return 'PAUSE'
    return 'NORMAL'


def _read_text(path):
    return Path(path).read_text(encoding='ascii')


def _absolute(text):
    value = PurePosixPath(text)
    if (not value.is_absolute() or str(value) != text or '..' in value.parts
            or text.endswith(' (deleted)')):
        raise ValueError('noncanonical proc path')
    return value


def _mount_path(text):
    return _absolute(re.sub(r'\\(040|011|012|134)', lambda m: chr(int(m[1], 8)), text))


def _count(text):
    text = text.strip()
    if not text.isascii() or not text.isdecimal():
        raise ValueError('invalid memory counter')
    return int(text)


def linux_available_memory_mb(read_text=None):
    """Min of host MemAvailable and finite visible v2 max-current, in MiB.

    Inspect the process's actual mount/membership and each visible ancestor,
    not a guessed root cgroup. Absent max files mean no controller bound at
    that level (including the real hierarchy root); unreadable or malformed
    observations stay unknown. A v1 memory hierarchy currently also abstains.
    Do not discount file cache, add swap, or infer hidden ancestor capacity.
    """
    read = read_text or _read_text
    try:
        entries = [line.split() for line in read('/proc/meminfo').splitlines()
                   if line.startswith('MemAvailable:')]
        if len(entries) != 1 or len(entries[0]) != 3 or entries[0][2] != 'kB':
            return None
        available = _count(entries[0][1]) * 1024
        membership = read('/proc/self/cgroup')
        rows = [line.split(':', 2) for line in membership.splitlines()]
        if any(len(row) != 3 for row in rows):
            return None
        # Hybrid systems may bind memory to v1 even with a unified entry.
        if any('memory' in row[1].split(',') for row in rows):
            return None
        unified = [row[2] for row in rows if row[:2] == ['0', '']]
        if not unified:
            return available // MIB
        if len(unified) != 1:
            return None
        member = _absolute(unified[0])
        mounts = []
        for line in read('/proc/self/mountinfo').splitlines():
            before, separator, after = line.partition(' - ')
            if not separator or not after.startswith('cgroup2 '):
                continue
            fields = before.split()
            if len(fields) < 6:
                return None
            mount_root, mount_point = _mount_path(fields[3]), _mount_path(fields[4])
            if member.is_relative_to(mount_root):
                mounts.append((mount_root, mount_point))
        if not mounts:
            return None
        # The widest applicable mount exposes the most ancestor constraints.
        mount_root, mount_point = min(mounts, key=lambda item: len(item[0].parts))
        node = mount_point / member.relative_to(mount_root)
        while True:
            try:
                limit = read(str(node / 'memory.max')).strip()
            except FileNotFoundError:
                limit = 'max'  # Root/disabled controller has no limit file.
            if limit != 'max':
                headroom = _count(limit) - _count(read(str(node / 'memory.current')))
                available = min(available, max(0, headroom))
            if node == mount_point:
                break
            node = node.parent
        if read('/proc/self/cgroup') != membership:
            return None  # Migration during a non-atomic observation.
        return available // MIB
    except (OSError, ValueError, IndexError):
        return None
