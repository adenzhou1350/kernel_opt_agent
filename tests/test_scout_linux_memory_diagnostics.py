"""Injected counters only; no reclaim, process control or memory pressure."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scout_linux_memory import MIB, linux_memory_diagnostics
from tests.test_scout_linux_memory import fixture


class MemoryDiagnosticsTests(unittest.TestCase):
    def observe(self, files):
        def read(path):
            value = files.get(path, FileNotFoundError(path))
            if isinstance(value, Exception):
                raise value
            return value
        return linux_memory_diagnostics(read)

    def bounded(self, member='/'):
        files = fixture(member)
        files['/sys/fs/cgroup/memory.max'] = str(16 * MIB)
        files['/sys/fs/cgroup/memory.current'] = str(15 * MIB)
        return files

    def test_large_file_cache_never_increases_admission_headroom(self):
        files = self.bounded()
        files['/sys/fs/cgroup/memory.stat'] = (
            f'anon {MIB}\nfile {14*MIB}\ninactive_file {13*MIB}\n'
            f'shmem {2*MIB}\nfile_dirty {MIB}\n')
        files['/sys/fs/cgroup/memory.events'] = 'oom 0\noom_kill 0\nmax 4\n'
        result = self.observe(files)
        self.assertEqual(result['admission_available_mb'], 1)
        self.assertEqual(result['status'], 'OBSERVED')
        row = result['cgroups'][0]
        self.assertEqual(row['raw_headroom_mb'], 1)
        self.assertEqual(row['stat_mib']['inactive_file'], 13)
        self.assertEqual(row['stat_mib']['shmem'], 2)
        self.assertEqual(row['events'], {'oom': 0, 'oom_kill': 0, 'max': 4})
        self.assertEqual(row['unavailable'], [])

    def test_missing_optional_stats_do_not_change_available_result(self):
        result = self.observe(self.bounded())
        self.assertEqual(result['admission_available_mb'], 1)
        self.assertEqual(result['cgroups'][0]['stat_mib'], {})
        self.assertEqual(result['cgroups'][0]['unavailable'],
                         ['memory.stat', 'memory.events'])

    def test_parent_levels_are_retained_not_just_the_leaf(self):
        files = self.bounded('/jobs/one')
        files['/sys/fs/cgroup/jobs/one/memory.max'] = 'max\n'
        files['/sys/fs/cgroup/jobs/memory.max'] = str(8 * MIB)
        files['/sys/fs/cgroup/jobs/memory.current'] = str(5 * MIB)
        result = self.observe(files)
        self.assertEqual(result['admission_available_mb'], 1)
        self.assertEqual([row['level'] for row in result['cgroups']], [0, 1, 2])
        self.assertEqual(result['cgroups'][1]['raw_headroom_mb'], 3)
        self.assertIsNone(result['cgroups'][0]['limit_mb'])

    def test_malformed_or_duplicate_stats_are_unavailable_not_capacity(self):
        for stat in ('inactive_file -1\n', 'inactive_file 1.5\n',
                     'inactive_file 1\ninactive_file 2\n', 'inactive_file\n'):
            with self.subTest(stat=stat):
                files = self.bounded()
                files['/sys/fs/cgroup/memory.stat'] = stat
                result = self.observe(files)
                self.assertEqual(result['admission_available_mb'], 1)
                self.assertEqual(result['cgroups'][0]['stat_mib'], {})
                self.assertIn('memory.stat', result['cgroups'][0]['unavailable'])

    def test_invalid_current_does_not_acquire_a_positive_capacity(self):
        files = self.bounded()
        files['/sys/fs/cgroup/memory.current'] = '-1'
        result = self.observe(files)
        self.assertIsNone(result['admission_available_mb'])
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertIsNone(result['cgroups'][0]['raw_headroom_mb'])

    def test_unified_membership_change_during_extra_reads_is_explicit(self):
        files = self.bounded()
        calls = 0
        def read(path):
            nonlocal calls
            if path == '/proc/self/cgroup':
                calls += 1
                return '0::/\n' if calls <= 2 else '0::/moved\n'
            if path not in files:
                raise FileNotFoundError(path)
            return files[path]
        self.assertEqual(linux_memory_diagnostics(read)['status'], 'STALE_MEMBERSHIP')


if __name__ == '__main__':
    unittest.main()
