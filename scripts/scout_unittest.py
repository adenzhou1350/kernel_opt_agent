"""Observe a reviewed stdlib unittest suite without replacing its assertions.

No sandbox, source selection, provisioning or PR verdict. Run only reviewed
tests inside existing process/resource controls. JSON supplements the unchanged
TextTestRunner log; subtests and fixture errors are not flattened into passes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import unittest


class ObservedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.events = []

    def event(self, action, test, **details):
        self.events.append(dict(action=action, test=test.id(), **details))

    def startTest(self, test):
        super().startTest(test)
        self.event("start", test)

    def stopTest(self, test):
        super().stopTest(test)
        self.event("stop", test)

    def addSuccess(self, test):
        super().addSuccess(test)
        self.event("success", test)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.event("failure", test)

    def addError(self, test, err):
        super().addError(test, err)
        # Class/module fixture errors use _ErrorHolder, without startTest.
        self.event("error", test)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.event("skip", test, reason=str(reason))

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.event("expected_failure", test)

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.event("unexpected_success", test)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        outcome = ("success" if err is None else
                   "failure" if issubclass(err[0], test.failureException) else "error")
        self.event("subtest", test, subtest=subtest.id(), outcome=outcome)


class ObservedRunner(unittest.TextTestRunner):
    resultclass = ObservedResult

    def run(self, test):
        # Reusing a runner must not leave an old successful observation after
        # an interrupted later execution.
        if hasattr(self, "observation"):
            del self.observation
        result = super().run(test)
        self.observation = {
            "format": "scout-unittest-observation-v1",
            "python": sys.version,
            "tests_run": result.testsRun,
            "was_successful": result.wasSuccessful(),
            "stopped_early": result.shouldStop,
            "events": result.events,
            "failures": [case.id() for case, _ in result.failures],
            "errors": [case.id() for case, _ in result.errors],
            "skips": [{"test": case.id(), "reason": reason} for case, reason in result.skipped],
            "expected_failures": [case.id() for case, _ in result.expectedFailures],
            "unexpected_successes": [case.id() for case in result.unexpectedSuccesses],
            "boundary": "Completed unittest runner observation, not complete discovery, "
                        "source/import identity, sandboxing, test quality or PR qualification. "
                        "tests_run counts parent executions; failures/errors can include subtests "
                        "and fixture events. Embedded doctest counts require separate observation.",
        }
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--report", type=Path, required=True)
    options, remaining = parser.parse_known_args(argv)
    # Reserve before loading target code. Existing reports/symlinks are never
    # overwritten. Parse/import/runner abort leaves no successful JSON report.
    with options.report.open("x", encoding="utf-8") as report:
        class ReportingRunner(ObservedRunner):
            def run(self, suite):
                result = super().run(suite)
                json.dump(self.observation, report, indent=2, ensure_ascii=True)
                report.write("\n")
                return result

        # Pass the class, not an instance: unittest must apply its parsed
        # verbosity/failfast/buffer/warnings flags to the real runner.
        program = unittest.main(module=None, argv=[sys.argv[0], *remaining],
                                testRunner=ReportingRunner, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    # A file entry point normally puts its tool directory at sys.path[0],
    # whereas `python -m unittest` puts the caller's working directory there.
    # Match module-mode name loading, but honor -I/-P/PYTHONSAFEPATH exclusions.
    if not getattr(sys.flags, "safe_path", False):
        sys.path[0] = str(Path.cwd())
    raise SystemExit(main())
