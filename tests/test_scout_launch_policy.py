import unittest

from scripts.scout_launch_policy import application_control_denied


class LaunchPolicyTests(unittest.TestCase):
    def test_exact_controller_launch_denial(self):
        self.assertTrue(application_control_denied({
            "state": "FAILED",
            "os_error": {"operation": "run_backend", "winerror": 4551},
        }))

    def test_other_failures_and_untrusted_text_do_not_stop_dispatch(self):
        for receipt in (
            None,
            {"state": "FAILED", "error": "OSError:4551"},
            {"state": "REVIEW", "os_error": {
                "operation": "run_backend", "winerror": 4551}},
            {"state": "FAILED", "os_error": {
                "operation": "prepare_request", "winerror": 4551}},
            {"state": "FAILED", "os_error": {
                "operation": "run_backend", "winerror": 8}},
            {"state": "FAILED", "os_error": {
                "operation": "run_backend", "winerror": "4551"}},
            {"state": "FAILED", "result": {"os_error": {
                "operation": "run_backend", "winerror": 4551}}},
        ):
            with self.subTest(receipt=receipt):
                self.assertFalse(application_control_denied(receipt))


if __name__ == "__main__":
    unittest.main()
