"""Conservative Linux RAM headroom, including visible cgroup-v2 ancestors.

Read only; never reclaim caches or change limits. This is a racy admission
observation, not an allocation guarantee or a diagnosis of process leaks.
"""
from pathlib import Path, PurePosixPath
import math
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


def _host_available_bytes(text):
    entries = [line.split() for line in text.splitlines()
               if line.startswith('MemAvailable:')]
    if len(entries) != 1 or len(entries[0]) != 3 or entries[0][2] != 'kB':
        raise ValueError('invalid host MemAvailable observation')
    return _count(entries[0][1]) * 1024


def _pressure(text):
    """Read the documented PSI shape for diagnostics, never for admission."""
    if len(text) > 2048:
        raise ValueError('oversized pressure observation')
    result = {}
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0] not in ('some', 'full') or fields[0] in result:
            raise ValueError('invalid pressure row')
        pairs = [field.split('=', 1) for field in fields[1:]]
        if any(len(pair) != 2 for pair in pairs) or len(dict(pairs)) != len(pairs):
            raise ValueError('invalid pressure counters')
        values = dict(pairs)
        if set(values) != {'avg10', 'avg60', 'avg300', 'total'}:
            raise ValueError('missing pressure counters')
        row = {key: float(values[key]) for key in ('avg10', 'avg60', 'avg300')}
        if any(not math.isfinite(value) or not 0 <= value <= 100 for value in row.values()):
            raise ValueError('invalid pressure average')
        row['total'] = _count(values['total'])
        result[fields[0]] = row
    if set(result) != {'some', 'full'}:
        raise ValueError('missing pressure row')
    return result


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
        available = _host_available_bytes(read('/proc/meminfo'))
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


def linux_memory_diagnostics(read_text=None):
    """Explain the conservative probe without crediting cache as capacity.

    Capture the paths/counters used by the real admission reader, then inspect
    optional statistics at those same visible levels. No writes, allocations,
    process control, hidden-ancestor inference or admission-policy change.
    The cache-adjusted estimate follows Kubernetes' inactive_file working-set
    convention, not a promise that those pages can be reclaimed on demand.
    """
    read = read_text or _read_text
    captured = {}

    def capture(path):
        try:
            value = read(path)
        except OSError:
            captured[path] = None
            raise
        captured[path] = value
        return value

    available = linux_available_memory_mb(capture)
    try:
        host_available_mb = _host_available_bytes(captured.get('/proc/meminfo') or '') // MIB
    except ValueError:
        host_available_mb = None
    result = {
        'admission_available_mb': available,
        'host_mem_available_mb': host_available_mb,
        'host_memory_pressure': None,
        'status': 'OBSERVED' if available is not None else 'UNKNOWN',
        'cgroups': [],
        'boundary': 'Read-only, non-atomic diagnostics. Inactive file bytes are '
                    'not guaranteed reclaimable allocation capacity; admission '
                    'still uses max-current and host MemAvailable. Host '
                    'MemAvailable is not a cgroup allocation allowance; cgroup '
                    'charged memory includes file cache, not just process RSS.',
    }
    try:
        result['host_memory_pressure'] = _pressure(read('/proc/pressure/memory'))
    except (OSError, ValueError, KeyError):
        pass  # Optional interface unavailable; raw admission is unchanged.
    for path, limit in captured.items():
        if not path.endswith('/memory.max'):
            continue
        node = str(PurePosixPath(path).parent)
        row = {'level': len(result['cgroups']), 'limit_mb': None,
               'charged_mb': None, 'raw_headroom_mb': None,
               'cache_adjusted_headroom_estimate_mb': None,
               'memory_pressure': None, 'oom_group': None,
               'stat_mib': {}, 'events': {}, 'unavailable': []}
        bound = charged = None
        try:
            current = captured.get(node + '/memory.current')
            if limit not in (None, 'max') and limit.strip() != 'max':
                bound, charged = _count(limit), _count(current)
                row.update(limit_mb=bound // MIB, charged_mb=charged // MIB,
                           raw_headroom_mb=max(0, bound - charged) // MIB)
        except (ValueError, AttributeError, TypeError):
            row['unavailable'].append('limit/current')
        for filename, keys, destination, divisor in (
            ('memory.stat', ('anon', 'file', 'shmem', 'inactive_file',
                             'active_file', 'file_dirty', 'file_writeback',
                             'file_mapped', 'unevictable'), 'stat_mib', MIB),
            ('memory.events', ('low', 'high', 'max', 'oom', 'oom_kill',
                               'oom_group_kill'), 'events', 1),
        ):
            try:
                pairs = [line.split() for line in read(node + '/' + filename).splitlines()]
                if any(len(pair) != 2 for pair in pairs):
                    raise ValueError('malformed statistics')
                values = dict(pairs)
                if len(values) != len(pairs):
                    raise ValueError('duplicate statistics')
                row[destination] = {key: _count(values[key]) // divisor
                                    for key in keys if key in values}
                if (filename == 'memory.stat' and bound is not None
                        and {'file', 'inactive_file'} <= values.keys()):
                    file_bytes = _count(values['file'])
                    inactive_bytes = _count(values['inactive_file'])
                    if 0 <= inactive_bytes <= file_bytes <= charged:
                        row['cache_adjusted_headroom_estimate_mb'] = max(
                            0, bound - charged + inactive_bytes,
                        ) // MIB
            except (OSError, ValueError):
                row['unavailable'].append(filename)
        try:
            row['memory_pressure'] = _pressure(read(node + '/memory.pressure'))
        except (OSError, ValueError, KeyError):
            row['unavailable'].append('memory.pressure')
        try:
            group = _count(read(node + '/memory.oom.group'))
            if group not in (0, 1):
                raise ValueError('invalid group OOM setting')
            row['oom_group'] = bool(group)
        except (OSError, ValueError, KeyError):
            row['unavailable'].append('memory.oom.group')
        result['cgroups'].append(row)
    try:
        if read('/proc/self/cgroup') != captured.get('/proc/self/cgroup'):
            result['status'] = 'STALE_MEMBERSHIP'
    except OSError:
        result['status'] = 'UNKNOWN'
    return result


if __name__ == '__main__':
    import json
    print(json.dumps(linux_memory_diagnostics(), indent=2))
