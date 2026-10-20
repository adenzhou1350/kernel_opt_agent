"""Pinned same-file test evidence, without network, models or Rust execution."""

import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_audit_context import contextual_audit_tests
import kimi_scout as scout
import kimi_scout_research as research


class InlineRustTests(unittest.TestCase):
    def setUp(self):
        self.repo, self.commit, self.path = "owner/project", "a" * 40, "src/tensor.rs"
        self.raw = "\n".join([
            "impl Tensor {", "    fn resolve_aux_frame(&self) {}", "}",
            *["// source"] * 125,
            "#[cfg(test)]", "mod tests {", "    use super::*;",
            "    #[test]", "    fn unrelated_roundtrip() {}",
            *["    // padding"] * 80,
            "    #[test]", "    fn resolve_aux_frame_uses_primary_message_slot() {",
            "        tensor.resolve_aux_frame(&[primary, payload]);", "    }", "}",
        ])
        data = self.raw.encode()
        self.snapshot = dict(commit=self.commit, files=[self.path], blobs={
            self.path: hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
        })
        self.context = SimpleNamespace(cached_source_text=Mock(return_value=self.raw))
        self.source = dict(
            url=f"https://raw.githubusercontent.com/{self.repo}/{self.commit}/{self.path}",
            text="\n".join(f"{i+1}: {line}" for i, line in enumerate(self.raw.splitlines()[:120])),
            start_line=1, end_line=120, total_lines=len(self.raw.splitlines()),
        )

    def select(self):
        return contextual_audit_tests(self.context, self.repo, self.snapshot, self.path, self.source)

    def test_prefers_observed_method_test_to_unrelated_test_prefix(self):
        before = deepcopy((self.snapshot, self.source))
        result = self.select()
        self.assertEqual(result["url"], self.source["url"])
        self.assertIn("fn resolve_aux_frame_uses_primary_message_slot()", result["text"])
        self.assertIn("&[primary, payload]", result["text"])
        self.assertNotIn("fn unrelated_roundtrip", result["text"])
        self.assertLessEqual(len(result["text"].splitlines()), 70)
        self.assertEqual((self.snapshot, self.source), before)
        self.context.cached_source_text.assert_called_once_with(self.repo, self.commit, self.path)
        self.assertIn("not execution", result["inline_test_hint"]["scope"])

    def test_no_declared_method_match_uses_first_inline_test(self):
        self.source["start_line"], self.source["end_line"] = 5, 6
        self.source["text"] = "5: // source\n6: // source"
        self.assertIn("fn unrelated_roundtrip", self.select()["text"])

    def test_primary_window_crossing_into_tests_does_not_prefer_already_seen_test(self):
        self.source["end_line"] = 135
        self.source["text"] = "\n".join(
            f"{i+1}: {line}" for i, line in enumerate(self.raw.splitlines()[:135]))
        self.assertIn("fn unrelated_roundtrip", self.source["text"])
        self.assertIn("&[primary, payload]", self.select()["text"])

    def test_rejects_wrong_blob_revision_url_and_excerpt(self):
        source, snapshot = deepcopy(self.source), deepcopy(self.snapshot)
        for key, value in (("url", source["url"] + "?revision=other"),
                           ("text", source["text"] + "\n121: invented"),
                           ("start_line", True), ("total_lines", 1)):
            with self.subTest(key=key):
                self.source = {**source, key: value}
                self.assertIsNone(self.select())
        self.source = source
        for key, value in (("blobs", {self.path: "b" * 40}),
                           ("commit", "main"), ("files", [])):
            with self.subTest(key=key):
                self.snapshot = {**snapshot, key: value}
                self.assertIsNone(self.select())

    def test_optional_cache_absence_errors_and_non_rust_abstain(self):
        for raw in (None, "\0", "x" * (512 * 1024 + 1), "\ud800"):
            with self.subTest(raw_type=type(raw).__name__, length=len(raw or "")):
                self.context.cached_source_text.return_value = raw
                self.assertIsNone(self.select())
        for exc in (OSError("cache unavailable"), ValueError("bad cache")):
            self.context.cached_source_text.side_effect = exc
            self.assertIsNone(self.select())
        self.context = SimpleNamespace()
        self.assertIsNone(self.select())
        self.path = "src/tensor.py"
        self.assertIsNone(self.select())

    def test_no_repeat_of_already_supplied_test_window(self):
        selected = self.select()
        self.source = selected
        self.assertIsNone(self.select())

    def test_crlf_identity_and_long_test_window_bounds(self):
        changed = self.raw.replace("        tensor.resolve_aux_frame(&[primary, payload]);",
                                   "        tensor.resolve_aux_frame(&[primary, payload]);\n"
                                   + "        // extra line\n" * 100).replace("\n", "\r\n")
        data = changed.encode()
        self.snapshot["blobs"][self.path] = hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        self.context.cached_source_text.return_value = changed
        self.source["total_lines"] = len(changed.splitlines())
        result = self.select()
        self.assertEqual(result["end_line"] - result["start_line"] + 1, 70)
        self.assertEqual(len(result["text"].splitlines()), 70)
        self.assertTrue(result["truncated"])

    def test_oversized_optional_excerpt_abstains_instead_of_clipping_its_identity(self):
        changed = self.raw.replace("        tensor.resolve_aux_frame(&[primary, payload]);",
                                   "        // " + "x" * 9000)
        data = changed.encode()
        self.snapshot["blobs"][self.path] = hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        self.context.cached_source_text.return_value = changed
        self.assertIsNone(self.select())

    def test_ambiguous_missing_or_nontrailing_module_keeps_ordinary_selector(self):
        raw = self.raw
        for changed in (
            raw.replace("#[cfg(test)]", "// no conditional test module"),
            raw + "\n#[cfg(test)]\nmod tests {}",
            raw + "\npub fn outside_tests() {}",
            raw.replace("    #[test]", "    // not a test"),
        ):
            with self.subTest(changed=changed[-70:]):
                data = changed.encode()
                self.snapshot["blobs"][self.path] = hashlib.sha1(
                    b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
                self.context.cached_source_text.return_value = changed
                self.source["total_lines"] = len(changed.splitlines())
                self.assertIsNone(self.select())

    def test_primary_packet_uses_inline_test_without_second_public_read(self):
        unrelated = "tests/distributed/test_packed_tensor.py"
        snapshot = deepcopy(self.snapshot)
        snapshot["files"].append(unrelated)
        snapshot["blobs"][unrelated] = "b" * 40
        old_packets = []
        for enabled in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                scout.initialize(root)
                config = root / "config.json"
                config.write_text(json.dumps(dict(
                    objective="Find falsifiable boundaries", queue_target=4,
                    repos=[dict(repo=self.repo, source_prefixes=["src/"], question="Wire contract")],
                )), encoding="utf-8")

                def source(repo, commit, path, **kwargs):
                    if path == self.path:
                        return dict(self.source)
                    return dict(url=f"https://raw.githubusercontent.com/{repo}/{commit}/{path}",
                                text="1: unrelated packed Python collective helper")

                context = SimpleNamespace(
                    snapshot=Mock(return_value=snapshot), source=Mock(side_effect=source),
                    cached_source_text=Mock(return_value=self.raw),
                )
                producer = research.ResearchProducer(root, config, context=context)
                route = (nullcontext() if enabled else
                         patch.object(research, "contextual_audit_tests", return_value=None))
                with route:
                    self.assertTrue(producer.source_audit(producer.config["repos"][0], {}))
                with scout.connect(root) as db:
                    packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
                self.assertEqual(len(packet["sources"]), 2)
                if enabled:
                    self.assertEqual(packet["sources"][0], old_packets[0]["sources"][0])
                    self.assertEqual(context.source.call_count, 1)
                    self.assertIn("&[primary, payload]", packet["sources"][1]["text"])
                    self.assertEqual(packet["sources"][1]["url"], self.source["url"])
                else:
                    self.assertEqual(context.source.call_count, 2)
                    self.assertTrue(packet["sources"][1]["url"].endswith(unrelated))
                    old_packets.append(packet)

    def test_changed_external_test_keeps_existing_priority(self):
        companion = "tests/tensor_test.rs"
        old = dict(commit="d" * 40, files=[self.path], blobs={self.path: "b" * 40})
        current = deepcopy(self.snapshot)
        current["files"].append(companion)
        current["blobs"][companion] = "c" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scout.initialize(root)
            config = root / "config.json"
            config.write_text(json.dumps(dict(
                objective="Find falsifiable boundaries", queue_target=4,
                repos=[dict(repo=self.repo, source_prefixes=["src/"], question="Wire contract")],
            )), encoding="utf-8")
            context = SimpleNamespace(
                snapshot=lambda repo, ref="main": old if ref == old["commit"] else current,
                source=Mock(side_effect=lambda repo, commit, path, **kwargs:
                            dict(self.source) if path == self.path else dict(
                                url=f"https://raw.githubusercontent.com/{repo}/{commit}/{path}",
                                text="1: new Rust regression case")),
                cached_source_text=Mock(return_value=self.raw),
            )
            producer = research.ResearchProducer(root, config, context=context)
            progress = dict(commit=self.commit, last_sweep_commit=old["commit"])
            self.assertTrue(producer.source_audit(producer.config["repos"][0], progress))
            self.assertEqual(context.source.call_args_list[-1].args[2], companion)
            context.cached_source_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
