"""Proc/cgroup fixtures only: no allocations, cgroup writes or model calls."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import kimi_scout as scout
from scout_linux_memory import linux_available_memory_mb, supervisor_memory_action, MIB


def fixture(member='/', mount_root='/', mount_point='/sys/fs/cgroup'):
    return {'/proc/meminfo': 'MemTotal: 2000000 kB\nMemAvailable: 1048576 kB\n',
            '/proc/self/cgroup': '0::'+member+'\n',
            '/proc/self/mountinfo': f'1 2 0:3 {mount_root} {mount_point} rw - cgroup2 cgroup rw\n'}


class LinuxMemoryTests(unittest.TestCase):
    def test_supervision_pause_recovers_without_restart_or_lowering_admission(self):
        samples = [5000, 4096, 4095, 2048, 4300, 2047, None]
        observed = [supervisor_memory_action(value, admission_floor_mb=4096,
                                            critical_floor_mb=2048) for value in samples]
        self.assertEqual(observed, ['NORMAL', 'NORMAL', 'PAUSE', 'PAUSE',
                                    'NORMAL', 'DRAIN', 'DRAIN'])
        self.assertFalse(scout.memory_admits_call(4095, 4096, 64, 0))
        self.assertTrue(scout.memory_admits_call(4300, 4096, 64, 0))

    def test_supervision_unknown_samples_drain_and_bad_thresholds_fail_closed(self):
        for value in (True, -1, '5000', 5000.0, float('nan')):
            self.assertEqual(supervisor_memory_action(value, admission_floor_mb=4096,
                                                     critical_floor_mb=2048), 'DRAIN')
        for admission, critical in ((4096, 0), (4096, 4097), (True, 1), (4096, 1.0)):
            with self.assertRaises(ValueError):
                supervisor_memory_action(5000, admission_floor_mb=admission,
                                         critical_floor_mb=critical)

    def observe(self, files):
        def read(path):
            value = files.get(path, FileNotFoundError(path))
            if isinstance(value, Exception):
                raise value
            return value
        return linux_available_memory_mb(read)

    def limit(self, files, node, limit, current):
        files[node+'/memory.max'] = str(limit)
        files[node+'/memory.current'] = str(current)

    def test_container_limit_not_host_free_memory_and_no_cache_discount(self):
        files = fixture()
        self.limit(files, '/sys/fs/cgroup', 16*MIB, 13*MIB)
        files['/sys/fs/cgroup/memory.stat'] = 'inactive_file 13000000\n'
        self.assertEqual(3, self.observe(files))

    def test_host_bound_still_wins(self):
        files = fixture()
        self.limit(files, '/sys/fs/cgroup', 2048*MIB, 0)
        self.assertEqual(1024, self.observe(files))

    def test_parent_usage_including_siblings_can_bind_unlimited_leaf(self):
        files = fixture('/jobs/one')
        self.limit(files, '/sys/fs/cgroup/jobs/one', 'max', 0)
        self.limit(files, '/sys/fs/cgroup/jobs', 20*MIB, 17*MIB)
        self.limit(files, '/sys/fs/cgroup', 100*MIB, 80*MIB)
        self.assertEqual(3, self.observe(files))

    def test_subtree_mount_resolves_membership_relative_to_mount_root(self):
        files = fixture('/delegated/one', '/delegated', '/private/cg')
        self.limit(files, '/private/cg/one', 16*MIB, 8*MIB)
        self.limit(files, '/private/cg', 10*MIB, 7*MIB)
        self.assertEqual(3, self.observe(files))

    def test_escaped_mountpoint_is_decoded(self):
        files = fixture(mount_point='/private/cg\\040space')
        self.limit(files, '/private/cg space', 16*MIB, 9*MIB)
        self.assertEqual(7, self.observe(files))

    def test_widest_mount_retains_parent_constraints(self):
        files = fixture('/jobs/one')
        files['/proc/self/mountinfo'] += '3 2 0:3 /jobs /narrow rw - cgroup2 cgroup rw\n'
        self.limit(files, '/narrow/one', 'max', 0)
        self.limit(files, '/sys/fs/cgroup', 16*MIB, 15*MIB)
        self.assertEqual(1, self.observe(files))

    def test_unlimited_root_and_absent_root_controller_use_host(self):
        files = fixture()
        self.assertEqual(1024, self.observe(files))
        self.limit(files, '/sys/fs/cgroup', 'max', 500*MIB)
        self.assertEqual(1024, self.observe(files))

    def test_absent_leaf_controller_does_not_hide_parent_limit(self):
        files = fixture('/disabled')
        self.limit(files, '/sys/fs/cgroup', 16*MIB, 14*MIB)
        self.assertEqual(2, self.observe(files))

    def test_over_limit_clamps_to_zero_and_rounds_down(self):
        files = fixture()
        for limit, current, expected in ((4*MIB, 5*MIB, 0), (4*MIB, 3*MIB+1, 0), (0, 0, 0)):
            self.limit(files, '/sys/fs/cgroup', limit, current)
            self.assertEqual(expected, self.observe(files))

    def test_missing_current_or_malformed_counters_stay_unknown(self):
        for limit, current in (('4', '-1'), ('-1', '0'), ('4.0', '0'), ('4', 'oops'), ('MAX', '0')):
            files = fixture();self.limit(files, '/sys/fs/cgroup', limit, current)
            self.assertIsNone(self.observe(files))
        files = fixture();files['/sys/fs/cgroup/memory.max'] = '4'
        self.assertIsNone(self.observe(files))
        files['/sys/fs/cgroup/memory.max'] = PermissionError('denied')
        self.assertIsNone(self.observe(files))

    def test_membership_unknown_unsafe_or_unmapped_does_not_fall_back_to_host(self):
        for member in ('/../outside', '/jobs/../one', '/gone (deleted)'):
            files = fixture(member)
            self.assertIsNone(self.observe(files))
        files = fixture('/outside', '/delegated')
        self.assertIsNone(self.observe(files))
        files = fixture();files['/proc/self/mountinfo'] = ''
        self.assertIsNone(self.observe(files))

    def test_v1_memory_is_explicitly_unknown_even_in_hybrid_mode(self):
        for membership in ('2:memory:/job\n', '0::/\n2:cpu,memory:/job\n'):
            files = fixture();files['/proc/self/cgroup'] = membership
            self.assertIsNone(self.observe(files))

    def test_no_memory_hierarchy_uses_host_but_bad_meminfo_stays_unknown(self):
        files = fixture();files['/proc/self/cgroup'] = '1:cpu:/job\n'
        self.assertEqual(1024, self.observe(files))
        for mem in ('', 'MemAvailable: -1 kB\n', 'MemAvailable: 100 MB\n'):
            files['/proc/meminfo'] = mem
            self.assertIsNone(self.observe(files))

    def test_migration_during_observation_stays_unknown(self):
        files = fixture();calls = 0
        def read(path):
            nonlocal calls
            if path == '/proc/self/cgroup':
                calls += 1
                return '0::/\n' if calls == 1 else '0::/new\n'
            if path not in files:
                raise FileNotFoundError(path)
            return files[path]
        self.assertIsNone(linux_available_memory_mb(read))

    def test_linux_dispatch_uses_cgroup_aware_probe(self):
        with patch.object(scout.os, 'name', 'posix'), patch.object(scout.sys, 'platform', 'linux'), patch.object(scout, 'linux_available_memory_mb', return_value=3) as probe:
            self.assertEqual(3, scout.available_memory_mb())
            probe.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
