"""Offline source-admission tests: no credentials, model calls or upstream execution."""

import hashlib
import json
import sqlite3
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_delivery_source as delivery

REPO = "owner/project"
COMMIT = "a" * 40
PATH = "src/check.py"
RAW = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{PATH}"
API = f"https://api.github.com/repos/{REPO}"


def packet(repo=REPO, sources=None, parent=None, stage="reproduction_plan"):
    return {
        "repo": repo,
        "sources": sources
        if sources is not None
        else [{"url": RAW, "text": "1: pass"}],
        "research": {"stage": stage, "parent_job_id": parent},
    }


def lead(value=None):
    return {"id": "lead", "repo": REPO, "commit": COMMIT, "packet": value or packet()}


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = sqlite3.connect(self.root / "scout.sqlite")
        self.addCleanup(self.db.close)
        self.db.execute(
            "CREATE TABLE jobs (id TEXT PRIMARY KEY,state TEXT,packet TEXT,result TEXT,finished REAL)"
        )

    def add(self, job_id, value=None, state="REVIEW", finished=1, hypothesis=None):
        self.db.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,?)",
            (
                job_id,
                state,
                json.dumps(value or packet()),
                json.dumps(
                    {"analysis": {"hypothesis": hypothesis or job_id, "title": job_id}}
                ),
                finished,
            ),
        )
        self.db.commit()

    def test_children_in_every_state_exclude_parent(self):
        for index, state in enumerate(
            ("FAILED", "PENDING", "RUNNING", "NO_LEAD", "NEEDS_CONTEXT")
        ):
            parent = f"parent{index}"
            self.add(parent)
            self.add(f"child{index}", packet(parent=parent), state=state)
        self.add("terminal")
        self.assertEqual(
            [row["id"] for row in delivery.select_leads(self.root)], ["terminal"]
        )

    def test_round_robin_is_not_dominated_by_newest_repository(self):
        for index in range(80):
            self.add(f"busy{index}", packet(repo="busy/repo"), finished=1000 + index)
        self.add("quiet_a", packet(repo="quiet/a"), finished=2)
        self.add("quiet_b", packet(repo="quiet/b"), finished=1)
        selected = delivery.select_leads(self.root, 3)
        self.assertEqual(
            {row["repo"] for row in selected}, {"busy/repo", "quiet/a", "quiet/b"}
        )

    def test_reproduction_plan_precedes_newer_audit_within_repository(self):
        self.add("audit", packet(stage="source_audit"), finished=999)
        self.add("plan", finished=1)
        self.assertEqual(
            [row["id"] for row in delivery.select_leads(self.root)], ["plan", "audit"]
        )

    def test_staged_leads_do_not_hide_fresh_leads_at_selection_limit(self):
        self.add("staged", finished=2)
        self.add("fresh", finished=1)
        first = delivery.select_leads(self.root, 1)
        self.assertEqual([row["id"] for row in first], ["staged"])
        self.assertEqual(
            [row["id"] for row in delivery.select_leads(
                self.root,
                1,
                exclude_source_ids={"staged"},
                exclude_keys={first[0]["canonical_key"]},
            )],
            ["fresh"],
        )

    def test_exact_normalized_dedup_is_revision_stable_not_semantic(self):
        self.add("old", hypothesis="  Same  HYPOTHESIS ", finished=1)
        changed = packet(
            sources=[{"url": RAW.replace(COMMIT, "b" * 40), "text": "new"}]
        )
        self.add("new", changed, hypothesis="same\nhypothesis", finished=2)
        self.add(
            "different", hypothesis="a paraphrase of the same possible bug", finished=3
        )
        rows = delivery.select_leads(self.root)
        self.assertEqual({row["id"] for row in rows}, {"new", "different"})
        self.assertEqual(
            next(row for row in rows if row["id"] == "new")["commit"], "b" * 40
        )
        self.assertEqual(rows, delivery.select_leads(self.root))
        self.assertTrue(all(len(row["canonical_key"]) == 64 for row in rows))
        self.assertTrue(all(isinstance(row["analysis"], dict) for row in rows))

    def test_missing_database_not_created_and_existing_is_unchanged(self):
        missing = self.root / "absent"
        with self.assertRaises(sqlite3.OperationalError):
            delivery.select_leads(missing)
        self.assertFalse(missing.exists())
        self.add("one")
        before = (self.root / "scout.sqlite").read_bytes()
        delivery.select_leads(self.root)
        self.assertEqual(before, (self.root / "scout.sqlite").read_bytes())

    def test_limit_validation(self):
        self.assertEqual(delivery.select_leads(self.root, 0), [])
        for value in (-1, True, 1.5, 10001):
            with self.assertRaises(ValueError):
                delivery.select_leads(self.root, value)


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = "import ast\nfrom collections import Counter\nvalue = 1\n"
        self.metadata = {"private": False, "visibility": "public", "full_name": REPO}
        self.calls = []
        mocked = patch.object(delivery.scout, "fetch", side_effect=self.fetch)
        mocked.start()
        self.addCleanup(mocked.stop)

    def fetch(self, url, limit, github_auth=False):
        self.calls.append((url, limit, github_auth))
        if url == API:
            return json.dumps(self.metadata)
        if url == RAW:
            return self.raw
        raise AssertionError("unexpected fetch " + url)

    def cache(self, text, url=RAW):
        folder = self.root / "public-cache"
        folder.mkdir(exist_ok=True)
        key = hashlib.sha256(
            delivery.scout.dumps([REPO, COMMIT, PATH]).encode()
        ).hexdigest()
        path = folder / f"raw-{key}.json"
        path.write_text(json.dumps({"url": url, "text": text}), encoding="utf-8")
        return path

    def test_full_module_digest_context_and_no_execution(self):
        marker = self.root / "must-not-exist"
        self.raw = (
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n"
        )
        original = lead()
        loaded = delivery.load_source(original, github_auth=True)
        self.assertEqual(loaded["source"], self.raw)
        self.assertEqual(
            loaded["sha256"], hashlib.sha256(self.raw.encode()).hexdigest()
        )
        self.assertEqual((loaded["path"], loaded["url"]), (PATH, RAW))
        self.assertEqual(loaded["dependency_modules"], [])
        self.assertFalse(marker.exists())
        loaded["context"]["sources"].clear()
        self.assertTrue(original["packet"]["sources"])
        self.assertEqual(self.calls, [(API, 100000, True), (RAW, 100000, False)])

    def test_validated_cache_avoids_raw_fetch_and_is_not_written(self):
        cached = self.cache("import json\nvalue = 2\n")
        before = cached.read_bytes()
        loaded = delivery.load_source(lead(), root=self.root)
        self.assertEqual(loaded["source"], "import json\nvalue = 2\n")
        self.assertEqual(before, cached.read_bytes())
        self.assertEqual([call[0] for call in self.calls], [API])
        self.assertNotIn(str(self.root), json.dumps(loaded["context"]))

    def test_mismatched_cache_url_is_not_trusted(self):
        self.cache("import torch", url=RAW + "?other")
        self.assertEqual(
            delivery.load_source(lead(), root=self.root)["source"], self.raw
        )
        self.assertEqual([call[0] for call in self.calls], [API, RAW])

    def test_reparse_cache_entry_or_ancestor_is_rejected(self):
        cached = self.cache(self.raw).absolute()
        original = Path.lstat
        for target in (cached, cached.parent, self.root.absolute()):

            def metadata(entry, *args, target=target, **kwargs):
                if entry == target:
                    return SimpleNamespace(
                        st_mode=stat.S_IFDIR, st_file_attributes=0x400
                    )
                return original(entry, *args, **kwargs)

            with (
                self.subTest(target=target),
                patch.object(Path, "lstat", metadata),
                self.assertRaisesRegex(
                    delivery.UnsupportedEnvironment, "symlink/reparse"
                ),
            ):
                delivery.load_source(lead(), root=self.root)
        self.assertTrue(all(call[0] == API for call in self.calls))

    def test_nonregular_cache_entry_is_rejected(self):
        cached = self.cache(self.raw)
        cached.unlink()
        cached.mkdir()
        with self.assertRaisesRegex(
            delivery.UnsupportedEnvironment, "not a regular file"
        ):
            delivery.load_source(lead(), root=self.root)

    def test_nonpublic_repository_blocks_even_cached_source(self):
        self.cache(self.raw)
        for metadata in (
            {"private": True},
            {"private": False},
            {"private": False, "visibility": "internal"},
        ):
            self.metadata = metadata
            with self.assertRaisesRegex(
                delivery.UnsupportedEnvironment, "not explicitly public"
            ):
                delivery.load_source(lead(), root=self.root, github_auth=True)
        self.assertTrue(all(call[0] == API for call in self.calls))

    def test_only_exact_packet_owned_immutable_python_urls(self):
        invalid = [
            RAW.replace("https:", "http:"),
            RAW + "?token=x",
            RAW + "#L1",
            RAW.replace(COMMIT, "main"),
            RAW.replace(COMMIT, "a" * 39),
            RAW.replace(REPO, "other/repo"),
            RAW.replace(PATH, "../escape.py"),
            RAW.replace(PATH, "src/%2e%2e/escape.py"),
            RAW.replace(PATH, "src//check.py"),
            RAW.replace("raw.githubusercontent.com", "raw.githubusercontent.com.evil"),
            RAW.replace(PATH, "src/check.py/else"),
            RAW.replace(PATH, "src/check.py\\other"),
        ]
        for url in invalid:
            with (
                self.subTest(url=url),
                self.assertRaisesRegex(delivery.UnsupportedEnvironment, "no immutable"),
            ):
                delivery.load_source(lead(packet(sources=[{"url": url, "text": "x"}])))
        self.assertEqual(self.calls, [])

    def test_first_eligible_python_source_not_model_suggested_url(self):
        value = packet(
            sources=[
                {"url": RAW.replace(".py", ".cu"), "text": "x"},
                {"url": RAW, "text": "x"},
            ]
        )
        item = lead(value)
        item["analysis"] = {"next_check": "fetch https://evil.example/other.py"}
        self.assertEqual(delivery.load_source(item)["url"], RAW)

    def test_mismatched_lead_identity_is_rejected_before_fetch(self):
        item = lead()
        item["commit"] = "b" * 40
        with self.assertRaisesRegex(
            delivery.UnsupportedEnvironment, "revision mismatch"
        ):
            delivery.load_source(item)
        item = lead(packet(repo="other/repo"))
        with self.assertRaisesRegex(
            delivery.UnsupportedEnvironment, "repository mismatch"
        ):
            delivery.load_source(item)
        self.assertEqual(self.calls, [])

    def test_byte_budget_is_enforced_for_fetch_and_cache(self):
        self.raw = "#" + "é" * 50000
        with self.assertRaisesRegex(delivery.UnsupportedEnvironment, "100000"):
            delivery.load_source(lead())
        self.cache(self.raw)
        with self.assertRaisesRegex(delivery.UnsupportedEnvironment, "100000"):
            delivery.load_source(lead(), root=self.root)

    def test_python310_syntax_and_explicit_stdlib_target(self):
        for source in (
            "def broken(:\n",
            "try:\n pass\nexcept* Exception:\n pass\n",
            "import tomllib\n",
        ):
            self.raw = source
            with (
                self.subTest(source=source),
                self.assertRaises(delivery.UnsupportedEnvironment),
            ):
                delivery.load_source(lead())

    def test_unconditional_heavy_import_rejected_with_reason_and_path(self):
        for source in (
            "import torch\n",
            "from numpy import array\n",
            "class C:\n import requests\n",
            "__import__('torch')\n",
        ):
            self.raw = source
            with self.subTest(source=source):
                with self.assertRaises(delivery.UnsupportedEnvironment) as caught:
                    delivery.load_source(lead())
                self.assertEqual(caught.exception.path, PATH)
                self.assertIn("non-Python-3.10-stdlib import", caught.exception.reason)

    def test_optional_and_lazy_imports_are_unknown_not_rejected(self):
        self.raw = (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n import torch\n"
            "try:\n import numpy\nexcept ImportError:\n pass\n"
            "def run():\n import requests\n"
        )
        loaded = delivery.load_source(lead())
        self.assertEqual(loaded["dependency_modules"], ["numpy", "requests", "torch"])
        self.assertEqual(loaded["required_dependency_modules"], [])
        self.assertEqual(len(loaded["compatibility_notes"]), 3)
        self.assertTrue(
            all("unknown" in note for note in loaded["compatibility_notes"])
        )

    def test_dependency_opt_in_reports_modules_without_install_or_execution(self):
        self.raw = "import torch\nfrom numpy.linalg import norm\n"
        loaded = delivery.load_source(lead(), allow_dependencies=True)
        self.assertEqual(loaded["dependency_modules"], ["numpy", "torch"])
        self.assertEqual(loaded["required_dependency_modules"], ["numpy", "torch"])
        self.assertTrue(
            all(
                "dependency runtime required" in note
                for note in loaded["compatibility_notes"]
            )
        )

    def test_relative_imports_require_package_even_when_optional_or_opted_in(self):
        for source in (
            "from . import helper\n",
            "def run():\n from .helper import value\n",
        ):
            self.raw = source
            for allowed in (False, True):
                with self.assertRaisesRegex(
                    delivery.UnsupportedEnvironment, "package context"
                ):
                    delivery.load_source(lead(), allow_dependencies=allowed)


if __name__ == "__main__":
    unittest.main()
