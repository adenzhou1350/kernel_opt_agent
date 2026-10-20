"""Saved-request diagnostics, not model-quality or provider-receipt tests."""

import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import scout_git_source
import scout_source_exposure as exposure


class ExposureTests(unittest.TestCase):
    def setUp(self):
        self.url = "https://raw.githubusercontent.com/owner/repo/" + "a" * 40 + "/module.py"
        self.expected = dict(url=self.url, text="10: if stopped:\n11:     return\n12: drain()")
        self.packet = dict(repo="owner/repo", sources=[copy.deepcopy(self.expected)])

    def inspect(self, packet=None, request=True):
        raw = json.dumps(packet if packet is not None else self.packet)
        saved = {"prompt": scout.SYSTEM + exposure.MARKER + raw} if request is True else request
        return exposure.inspect_exposure(raw, saved, self.expected)

    def test_complete_exact_request_and_output_omit_source_text(self):
        result = self.inspect()
        self.assertEqual(result["status"], "EXPECTED_LINES_PRESENT")
        self.assertEqual(result["present_lines"], 3)
        self.assertEqual(result["missing_ranges"], [])
        self.assertNotIn("drain()", json.dumps(result))
        self.assertIn("not public provenance authentication", result["boundary"])

    def test_partial_text_not_declared_metadata_controls_coverage(self):
        self.packet["sources"][0].update(text="10: if stopped:", start_line=1, end_line=900)
        result = self.inspect()
        self.assertEqual(result["status"], "EXPECTED_LINES_PARTIAL_OR_ABSENT")
        self.assertEqual(result["missing_ranges"], [[11, 12]])

    def test_joint_sources_in_one_packet_and_equal_duplicates(self):
        first = dict(url=self.url, text="10: if stopped:")
        second = dict(url=self.url, text="11:     return\n12: drain()")
        self.packet["sources"] = [first, first.copy(), second]
        self.assertEqual(self.inspect()["status"], "EXPECTED_LINES_PRESENT")

    def test_separate_requests_must_not_be_unioned(self):
        self.packet["sources"][0]["text"] = "10: if stopped:"
        one = self.inspect()
        self.packet["sources"][0]["text"] = "11:     return\n12: drain()"
        two = self.inspect()
        self.assertEqual([one["present_lines"], two["present_lines"]], [1, 2])
        self.assertEqual(one["status"], two["status"])
        self.assertNotEqual(one["status"], "EXPECTED_LINES_PRESENT")

    def test_wrong_revision_or_quote_in_question_is_not_source(self):
        self.packet["question"] = self.expected["text"]
        self.packet["sources"][0]["url"] = self.url.replace("a" * 40, "b" * 40)
        self.assertEqual(self.inspect()["status"], "NO_MATCHING_PINNED_SOURCE")

    def test_wrong_text_and_conflicting_duplicate_remain_inconsistent(self):
        changed = dict(url=self.url, text="12: cancel()")
        self.packet["sources"].append(changed)
        result = self.inspect()
        self.assertEqual(result["status"], "INCONSISTENT_SOURCE_LINES")
        self.assertEqual(result["conflicting_ranges"], [[12, 12]])
        self.assertEqual(result["present_lines"], 2)

    def test_unrecognized_numbered_text_does_not_become_absence(self):
        for text in ("10: if stopped:\n...", "10: if stopped:\n10: if stopped:", "unrelated"):
            with self.subTest(text=text):
                self.packet["sources"][0]["text"] = text
                self.assertEqual(self.inspect()["status"], "INCONSISTENT_SOURCE_LINES")

    def test_missing_mismatched_or_different_serialization_request_is_unknown(self):
        for request in (None, {}, {"prompt": "other"}, {"prompt": scout.SYSTEM + exposure.MARKER + json.dumps(self.packet, indent=2)}):
            with self.subTest(request=request is None):
                result = self.inspect(request=request)
                self.assertEqual(result["status"], "SAVED_REQUEST_UNVERIFIED")
                self.assertEqual(result["packet_status"], "EXPECTED_LINES_PRESENT")
                self.assertFalse(result["saved_request_matches_packet"])

    def test_pin_validation_and_expected_source_validation(self):
        for url in (self.url.replace("a" * 40, "main"), self.url + "?token=secret", self.url.replace("https:", "http:"), self.url.replace("/module.py", "/../module.py")):
            with self.subTest(url=url):
                self.expected["url"] = url
                with self.assertRaises(ValueError):
                    self.inspect()
        self.expected["url"] = self.url
        for text in ("", "line without number", "2: two\n1: one", "01: padded"):
            self.expected["text"] = text
            with self.assertRaises(ValueError):
                self.inspect()

    def test_unicode_literals_and_crlf_do_not_add_fake_source_lines(self):
        self.expected["text"] = '10: value = "a\u2028b"\n12: drain()'
        self.packet["sources"][0]["text"] = self.expected["text"].replace("\n", "\r\n")
        self.assertEqual(self.inspect()["status"], "EXPECTED_LINES_PRESENT")
        self.assertEqual(self.inspect()["expected_lines"], 2)

    def test_bounds_duplicates_and_malformed_types_reject(self):
        with self.assertRaises(ValueError):
            exposure.inspect_exposure('{"sources":[],"sources":[]}', None, self.expected)
        with self.assertRaises(ValueError):
            exposure.inspect_exposure(" " * (exposure.MAX_RECORD_BYTES + 1), None, self.expected)
        for packet in ([], {"sources": "not a list"}, {"sources": [{}] * 65}):
            with self.assertRaises(ValueError):
                self.inspect(packet)

    def test_cli_is_read_only_and_unknown_request_is_not_a_failed_model(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            packet = root / "packet.json"
            expected = root / "expected.json"
            packet.write_text(json.dumps(self.packet), encoding="utf-8")
            expected.write_text(json.dumps({"sources": [self.expected]}), encoding="utf-8")
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = exposure.main(["--packet", str(packet), "--expected", str(expected)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "SAVED_REQUEST_UNVERIFIED")
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})

    def test_expected_packet_from_raw_git_not_dirty_checkout(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            def git(*args):
                return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
            git("init", "-q")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@example.invalid")
            git("config", "core.autocrlf", "false")
            git("config", "commit.gpgsign", "false")
            path = root / "module.py"
            path.write_bytes(b"if stopped:\n    pass\ndrain()\n")
            git("add", "module.py")
            git("-c", "core.hooksPath=NUL", "commit", "-qm", "fixture")
            commit = git("rev-parse", "HEAD")
            path.write_bytes(b"dirty\r\n")
            spec = dict(name="fixture", repo="owner/repo", commit=commit, question="Inspect public source.", files=[dict(path="module.py", ranges=[dict(start=1, end=1), dict(start=3, end=3)])])
            expected = scout_git_source.build_packet(root, spec)
            raw = json.dumps(expected)
            result = exposure.inspect_exposure(raw, dict(prompt=scout.SYSTEM + exposure.MARKER + raw), expected["sources"][0])
            self.assertEqual(result["status"], "EXPECTED_LINES_PRESENT")
            self.assertEqual(result["expected_lines"], 2)


if __name__ == "__main__":
    unittest.main()
