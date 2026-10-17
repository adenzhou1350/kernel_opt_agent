"""Injected reporter controls; actual Bun replay is a separate observation."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

from scripts.scout_bun_junit import case_id
from scripts.scout_native_results import compare_regression, summarize

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import scout_native_run as runner


def report(outcomes=('passed', 'passed', 'passed'), *, nested=True):
    """One regression plus two same-location parameterized controls."""
    root = ET.Element('testsuites', name='bun test')
    outer = ET.SubElement(root, 'testsuite', name='probe.test.ts', file='probe.test.ts')
    parent = outer
    if nested:
        parent = ET.SubElement(outer, 'testsuite', name='group', file='probe.test.ts', line='1')
    for index, outcome in enumerate(outcomes):
        case = ET.SubElement(parent, 'testcase', file='probe.test.ts',
            line='2' if index == 0 else '3', name='regression' if index == 0 else 'parameterized',
            classname='group' if nested else '')
        if outcome == 'failed':
            ET.SubElement(case, 'failure', type='AssertionError', message='fixture mismatch')
        elif outcome == 'skipped':
            ET.SubElement(case, 'skipped', message='TODO')
    for element in root.iter():
        if element.tag in {'testsuites', 'testsuite'}:
            element.set('tests', str(len(outcomes)))
            element.set('failures', str(outcomes.count('failed')))
            element.set('skipped', str(outcomes.count('skipped')))
    return root


def text(root):
    return ET.tostring(root, encoding='unicode')


REGRESSION = case_id('probe.test.ts', 2, [('group', 1)], 'regression')
CONTROL = case_id('probe.test.ts', 3, [('group', 1)], 'parameterized')


class BunReaderTests(unittest.TestCase):
    def read(self, root=None, exit_code=0, expected=None):
        return summarize(text(report() if root is None else root), format='bun-junit',
            exit_code=exit_code, expected_tests=expected or [REGRESSION, CONTROL])

    def test_nested_cases_count_once_and_parameter_groups_keep_multiplicity(self):
        value = self.read()
        self.assertEqual(value['status'], 'TESTS_PASSED')
        self.assertEqual(value['passed'], 3)
        self.assertEqual(value['batches'], 1)
        self.assertEqual(value['expected_test_results'][CONTROL]['passed'], 2)
        self.assertEqual(value['bun_junit']['case_groups'], 2)
        self.assertFalse(value['bun_junit']['parameter_values_identified'])

    def test_top_level_classless_cases_have_file_line_identity(self):
        value = self.read(report(nested=False), expected=[case_id('probe.test.ts', 2, [], 'regression')])
        self.assertEqual(value['status'], 'TESTS_PASSED')
        self.assertEqual(value['passed'], 3)

    def test_skip_and_todo_are_not_executed_or_double_charged(self):
        value = self.read(report(('passed', 'skipped', 'skipped')), expected=[REGRESSION])
        self.assertEqual(value['status'], 'TESTS_PASSED')
        self.assertEqual((value['passed'], value['skipped'], value['executed']), (1, 2, 1))
        self.assertEqual(value['bun_junit']['todo'], 2)
        self.assertEqual(self.read(report(('passed', 'skipped', 'skipped')))['status'], 'INCONCLUSIVE')

    def test_declared_same_group_mixed_outcomes_are_not_an_all_failed_regression(self):
        before = text(report(('passed', 'failed', 'passed')))
        result = compare_regression(before, text(report()), format='bun-junit',
            baseline_exit=1, candidate_exit=0, regressions=[CONTROL], controls=[REGRESSION])
        self.assertEqual(result['status'], 'PATTERN_NOT_OBSERVED')

    def test_real_shaped_matched_failure_and_controls(self):
        result = compare_regression(text(report(('failed', 'passed', 'passed'))), text(report()),
            format='bun-junit', baseline_exit=1, candidate_exit=0,
            regressions=[REGRESSION], controls=[CONTROL])
        self.assertEqual(result['status'], 'MATCHED_REGRESSION_OBSERVED')
        self.assertEqual(result['baseline']['failed'], 1)
        self.assertEqual(result['candidate']['passed'], 3)

    def test_missing_parameter_instance_changes_inventory_not_just_a_set(self):
        result = compare_regression(text(report(('failed', 'passed', 'passed'))),
            text(report(('passed', 'passed'))), format='bun-junit', baseline_exit=1,
            candidate_exit=0, regressions=[REGRESSION], controls=[CONTROL])
        self.assertEqual(result['status'], 'PATTERN_NOT_OBSERVED')
        self.assertIn('Bun grouped test inventories or multiplicities differ', result['issues'])

    def test_inventory_is_order_independent_but_not_location_independent(self):
        first = report(); reordered = copy.deepcopy(first)
        group = next(node for node in reordered.iter('testsuite') if node.get('name') == 'group')
        group[:] = reversed(list(group))
        self.assertEqual(self.read(first)['bun_junit'], self.read(reordered)['bun_junit'])
        next(reordered.iter('testcase')).set('line', '30')
        self.assertNotEqual(self.read(first)['bun_junit']['grouped_case_inventory_sha256'],
                            self.read(reordered)['bun_junit']['grouped_case_inventory_sha256'])

    def test_hook_missing_location_and_timeout_are_inconclusive_not_bug_proofs(self):
        for defect in ('hook', 'timeout'):
            root = report(('failed', 'passed', 'passed'))
            case = next(root.iter('testcase'))
            if defect == 'hook':
                case.attrib.pop('line'); case.set('name', '(unnamed)')
            else:
                case[0].set('type', 'TimeoutError')
            value = self.read(root, exit_code=1)
            self.assertEqual(value['status'], 'INCONCLUSIVE')
            self.assertEqual(value['failed'], 1)

    def test_malformed_truncated_foreign_and_dtd_reports_are_inconclusive(self):
        for raw in ('', '<testsuites', '<testsuites name="other"/>',
                    '<!DOCTYPE a [<!ENTITY x "x">]><testsuites name="bun test"/>'):
            value = summarize(raw, format='bun-junit', exit_code=1, expected_tests=[REGRESSION])
            self.assertEqual(value['status'], 'INCONCLUSIVE')

    def test_report_contradictions_fail_closed(self):
        changes = [
            lambda root: root.set('tests', '2'),
            lambda root: root.set('errors', '1'),
            lambda root: root[0].set('skipped', '1'),
            lambda root: next(root.iter('testcase')).set('classname', 'wrong'),
            lambda root: next(root.iter('testcase')).set('file', '../private.test.ts'),
            lambda root: ET.SubElement(next(root.iter('testcase')), 'error'),
            lambda root: ET.SubElement(root, 'testcase', name='out of suite'),
            lambda root: ET.SubElement(next(root.iter('testcase')), 'skipped'),
        ]
        for change in changes:
            root = report(); change(root)
            self.assertEqual(self.read(root)['status'], 'INCONCLUSIVE')
        self.assertEqual(self.read(exit_code=-15)['status'], 'INCONCLUSIVE')
        self.assertEqual(self.read(exit_code=7)['status'], 'INCONCLUSIVE')
        self.assertEqual(self.read(exit_code=1)['status'], 'INCONCLUSIVE')

    def test_case_ids_do_not_split_delimiters_and_reject_invalid_locations(self):
        self.assertEqual(json.loads(case_id('a.test.ts', 1, [('a::b', 2)], 'c::d')),
                         ['a.test.ts', 1, [['a::b', 2]], 'c::d'])
        for args in (('../a', 1, [], 'x'), ('C:/a', 1, [], 'x'), ('a', True, [], 'x'),
                     ('a', 1, [('group', None)], 'x'), ('a', 1, [], 'x'*513)):
            with self.assertRaises(ValueError): case_id(*args)


class BunCaptureControls(unittest.TestCase):
    """Python emits injected Bun-shaped XML; not native Bun on this OS."""
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        (self.root/'probe.test.ts').write_bytes(b'// reviewed fixture\n')
        self.sha = hashlib.sha256((self.root/'probe.test.ts').read_bytes()).hexdigest()

    def execute(self, code, tail=()):
        return runner.run(cwd=self.root, output=self.root/'output',
            command=[sys.executable, '-B', '-c', code, *tail],
            sources=[('probe.test.ts', self.sha)], format='bun-junit',
            expected_tests=[REGRESSION, CONTROL], timeout=5, native_windows=os.name=='nt')

    def test_runner_owns_bun_report_and_preserves_console_log(self):
        code = ("import sys; from pathlib import Path; "
            "assert sys.argv[-2]=='--reporter=junit'; "
            "Path(sys.argv[-1].split('=',1)[1]).write_text("+repr(text(report()))+"); print('fixture stdout')")
        value = self.execute(code)
        self.assertEqual(value['status'], 'TESTS_PASSED', value)
        self.assertEqual(value['summary']['passed'], 3)
        self.assertEqual(Path(value['test_report']['path']).name, 'bun.xml')
        self.assertIn('fixture stdout', (self.root/'output/terminal.log').read_text())
        self.assertFalse(value['post_exit_group_cleanup_required'])

    def test_overridden_reporter_is_rejected_before_launch(self):
        for flag in ('--reporter=json', '--reporter', '--reporter-outfile=old.xml'):
            with patch.object(runner.subprocess, 'Popen') as child, self.assertRaises(ValueError):
                self.execute("raise RuntimeError('must not run')", [flag])
            child.assert_not_called()
        self.assertFalse((self.root/'output').exists())

    def test_import_failure_without_xml_does_not_become_a_test_failure(self):
        value = self.execute("import sys; print('fixture import error'); sys.exit(1)")
        self.assertEqual(value['status'], 'INCONCLUSIVE')
        self.assertIsNone(value['summary'])
        self.assertIn('missing or non-regular test report', value['issues'])


if __name__ == '__main__': unittest.main()
