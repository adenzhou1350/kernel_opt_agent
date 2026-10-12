"""Missing historical names must not masquerade as another useful excerpt."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_context import PublicContext
from scout_requested_definition import absent_requested_identifiers


class MissingIdentifierTests(unittest.TestCase):
    def test_language_neutral_absence_does_not_guess_renamed_function(self):
        raw = "func (f *FlagSet) fail(err error) error { return err }\n"
        self.assertEqual(absent_requested_identifiers(raw, "references(failf)"), ["failf"])
        self.assertEqual(absent_requested_identifiers(raw, "definition(FlagSet.fail)"), [])

    def test_occurrence_outside_window_or_in_trivia_prevents_absence_claim(self):
        for tail in ("// failf", 'const hint = "failf"', "failfOld", "func failf() {}"):
            self.assertEqual(
                absent_requested_identifiers("\n" * 300 + tail, "references(failf)"), []
            )

    def test_malformed_multiple_or_implicit_requests_abstain(self):
        for request in (
            "look for failf", "xreferences(failf)", "references(\nfailf)",
            "definition(failf repo:other)", "references(a) definition(b) references(c)",
            "references(failf) definition(broken", "definition(" + "a" * 129 + ")",
        ):
            with self.subTest(request=request):
                self.assertEqual(absent_requested_identifiers("", request), [])

    def test_two_targets_and_qualified_terminal_name_are_bounded(self):
        self.assertEqual(
            absent_requested_identifiers("Usage", "references(Usage) definition(FlagSet.failf)"),
            ["failf"],
        )
        self.assertEqual(
            absent_requested_identifiers("", "references(failf) definition(failf)"), ["failf"]
        )
        self.assertEqual(absent_requested_identifiers("", " " * 2000 + "references(failf)"), [])

    def test_actual_reader_reports_full_source_absence_without_extra_fetch(self):
        raw = "func fail(err error) error { return err }\n" + "\n" * 200 + "// Usage\n"
        with tempfile.TemporaryDirectory() as temp:
            reader = PublicContext(temp)
            with (
                patch.object(reader, "snapshot", return_value={"files": ["flag.go"]}),
                patch.object(reader, "_source_text", return_value=(raw, "raw")) as read,
            ):
                # The cache acquisition still uses the pinned Git blob identity.
                reader.snapshot.return_value["blobs"] = {"flag.go": "b" * 40}
                item = reader.source("owner/project", "a" * 40, "flag.go",
                                     start=1, max_lines=1,
                                     request_hints="references(failf) references(Usage)")
                self.assertEqual(read.call_count, 1)
                observation = item["requested_identifier_absence"]
                self.assertEqual(observation["identifiers"], ["failf"])
                self.assertEqual(observation["source_sha256"], hashlib.sha256(raw.encode()).hexdigest())
                self.assertNotIn("Usage", item["text"])
                cached = reader.source("owner/project", "a" * 40, "flag.go",
                                       start=1, max_lines=1, request_hints="references(fail)")
                self.assertEqual(read.call_count, 1)
                self.assertNotIn("requested_identifier_absence", cached)


if __name__ == "__main__":
    unittest.main()
