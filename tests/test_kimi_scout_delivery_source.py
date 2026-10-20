"""Offline source-admission tests: no credentials, model calls or upstream execution."""

import hashlib
import json
import sqlite3
import stat
import sys
import tempfile
import unittest
from contextlib import closing
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
        else [{"url": RAW.replace(REPO, repo), "text": "1: pass"}],
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

    def add(self, job_id, value=None, state="REVIEW", finished=1, hypothesis=None, evidence=None):
        analysis = {"hypothesis": hypothesis or job_id, "title": job_id}
        if evidence is not None:
            analysis["evidence"] = evidence
        self.db.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,?)",
            (
                job_id,
                state,
                json.dumps(value or packet()),
                json.dumps({"analysis": analysis}),
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

    def test_failed_followup_preserves_parent_for_owner_only_inspection(self):
        for index, state in enumerate(
            ("FAILED", "PENDING", "RUNNING", "NO_LEAD", "NEEDS_CONTEXT")
        ):
            self.add(f"parent{index}")
            self.add(f"child{index}", packet(parent=f"parent{index}"), state=state)
        before = (self.root / "scout.sqlite").read_bytes()
        self.assertEqual(delivery.select_leads(self.root), [])
        rows = delivery.select_leads(self.root, owner_review=True)
        self.assertEqual([r["id"] for r in rows], ["parent0"])
        self.assertEqual(rows[0]["owner_failed_followups"], {"count": 1, "job_ids": ["child0"]})
        self.assertEqual(rows[0]["verification_route"], "OWNER_REVIEW_ONLY")
        self.assertEqual(before, (self.root / "scout.sqlite").read_bytes())

    def test_nearest_review_ancestor_survives_failed_followup(self):
        self.add("root")
        self.add("middle", packet(parent="root"))
        for i in range(7):
            self.add(f"failed{i}", packet(parent="middle"), state="FAILED", finished=i)
        rows = delivery.select_leads(self.root, owner_review=True)
        self.assertEqual([r["id"] for r in rows], ["middle"])
        self.assertEqual(rows[0]["owner_failed_followups"], {
            "count": 7, "job_ids": ["failed6", "failed5", "failed4", "failed3"]})
        self.add("active", packet(parent="middle"), state="PENDING")
        self.assertEqual(delivery.select_leads(self.root, owner_review=True,
                                             source_ids=["middle"]), [])

    def test_failed_followup_owner_recovery_keeps_filters_and_language_scope(self):
        self.add("parent", packet(sources=[{"url": RAW.replace(".py", ".go")}]))
        self.add("failed", packet(parent="parent"), state="FAILED")
        for options in ({"owner_review": True}, {"native_cpu": True}, {"owner_language": "go"}):
            with self.subTest(options=options):
                rows = delivery.select_leads(self.root, source_ids=["parent"], **options)
                self.assertEqual([r["id"] for r in rows], ["parent"])
                self.assertEqual(rows[0]["verification_route"], "OWNER_REVIEW_ONLY")
                self.assertEqual(delivery.select_leads(self.root, exclude_repos=[REPO], **options), [])
                self.assertEqual(delivery.select_leads(self.root, exclude_source_ids=["parent"], **options), [])
                self.assertEqual(delivery.select_leads(self.root, exclude_keys=[rows[0]["canonical_key"]], **options), [])

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
            [
                row["id"]
                for row in delivery.select_leads(
                    self.root,
                    1,
                    exclude_source_ids={"staged"},
                    exclude_keys={first[0]["canonical_key"]},
                )
            ],
            ["fresh"],
        )

    def test_attached_delivery_filter_runs_before_bounded_source_scan(self):
        self.add("staged", finished=2)
        self.add("fresh", finished=1)
        delivery_root = self.root / "delivery"
        delivery_root.mkdir()
        db = sqlite3.connect(delivery_root / "delivery.sqlite")
        try:
            db.execute("CREATE TABLE delivery (source_job_id TEXT UNIQUE)")
            db.execute("INSERT INTO delivery VALUES ('staged')")
            db.commit()
        finally:
            db.close()
        self.assertEqual(
            [row["id"] for row in delivery.select_leads(self.root, 1, scan_limit=1)],
            ["fresh"],
        )

    def test_other_languages_remain_unstaged_and_do_not_starve_python(self):
        cpp_raw = RAW.replace("src/check.py", "src/check.cpp")
        self.add(
            "cpp",
            packet(
                sources=["invalid source", {"url": cpp_raw, "text": "1: int main() {}"}]
            ),
            finished=2,
        )
        self.add("python", finished=1)
        before = (self.root / "scout.sqlite").read_bytes()
        selected = delivery.select_leads(self.root, 1, scan_limit=1)
        self.assertEqual([row["id"] for row in selected], ["python"])
        self.assertEqual(before, (self.root / "scout.sqlite").read_bytes())

    def test_owner_review_selects_native_sources_without_changing_default(self):
        for index, extension in enumerate(("go", "rs", "cpp", "ts")):
            self.add(
                extension,
                packet(sources=[{
                    "url": RAW.replace("check.py", "check." + extension),
                    "text": "untrusted source, never executed",
                }]),
                finished=10 + index,
            )
        self.add("python", finished=1)
        before = (self.root / "scout.sqlite").read_bytes()
        self.assertEqual(
            [row["id"] for row in delivery.select_leads(self.root)], ["python"]
        )
        rows = delivery.select_leads(self.root, owner_review=True)
        self.assertEqual({row["id"] for row in rows}, {"go", "rs", "cpp", "ts", "python"})
        self.assertTrue(all(row["commit"] == COMMIT for row in rows))
        self.assertTrue(all(row["verification_route"] == "OWNER_REVIEW_ONLY" for row in rows))
        self.assertEqual(before, (self.root / "scout.sqlite").read_bytes())

    def test_owner_review_keeps_immutable_source_and_parent_admission(self):
        self.add("mutable", packet(sources=[{
            "url": RAW.replace(COMMIT, "main").replace(".py", ".go"),
        }]), finished=30)
        self.add("other-repo", packet(sources=[{
            "url": RAW.replace(REPO, "other/project").replace(".py", ".rs"),
        }]), finished=20)
        self.add("parent", packet(sources=[{"url": RAW.replace(".py", ".cpp")}]))
        self.add("child", packet(parent="parent"), state="NEEDS_CONTEXT")
        self.add("valid", packet(sources=[{"url": RAW.replace(".py", ".ts")}]))
        rows = delivery.select_leads(self.root, owner_review=True)
        self.assertEqual([row["id"] for row in rows], ["valid"])

    def test_owner_review_commit_belongs_to_primary_non_python_source(self):
        self.add("mixed", packet(sources=[
            {"url": RAW.replace(".py", ".rs")},
            {"url": RAW.replace(COMMIT, "b" * 40)},
        ]))
        owner = delivery.select_leads(self.root, owner_review=True)[0]
        self.assertEqual(owner["commit"], COMMIT)
        self.assertEqual(delivery.select_leads(self.root), [])

    def test_unique_cited_source_controls_language_revision_and_dedup(self):
        rust = RAW.replace("check.py", "check.rs")
        python = RAW.replace(COMMIT, "b" * 40)
        mixed = packet(sources=[{"url": rust}, {"url": python}])
        self.add("mixed", mixed, evidence=[{"url": python}], hypothesis="same", finished=2)
        self.add("single", packet(sources=[{"url": python}]), hypothesis="same", finished=1)
        before = (self.root / "scout.sqlite").read_bytes()
        selected = delivery.select_leads(self.root, scan_limit=1)
        self.assertEqual([row["id"] for row in selected], ["mixed"])
        self.assertEqual(selected[0]["commit"], "b" * 40)
        self.assertEqual(len(delivery.select_leads(self.root)), 1)
        self.assertEqual(before, (self.root / "scout.sqlite").read_bytes())

    def test_owner_summary_marks_multi_revision_fallback_as_unresolved(self):
        current = RAW.replace(COMMIT, "b" * 40)
        self.add("comparison", packet(sources=[{"url": RAW}, {"url": current}]),
                 evidence=[{"url": RAW}, {"url": current}], finished=3)
        self.add("resolved", packet(sources=[{"url": current}]),
                 evidence=[{"url": current}], hypothesis="distinct", finished=2)
        self.add("legacy", hypothesis="legacy", finished=1)
        before = (self.root / "scout.sqlite").read_bytes()
        rows = {row["id"]: row for row in delivery.select_leads(self.root, owner_language="python")}
        self.assertEqual(rows["comparison"]["commit"], COMMIT)  # Visibility only; do not rewrite old packets.
        selection = rows["comparison"]["source_selection"]
        self.assertEqual(selection["status"], "UNRESOLVED")
        self.assertIn("visibility fallback", selection["boundary"])
        self.assertIn("multiple cited", selection["reason"])
        self.assertEqual(rows["resolved"]["source_selection"]["status"], "RESOLVED_CITATION")
        self.assertEqual(rows["legacy"]["source_selection"]["status"], "LEGACY_FIRST_SOURCE")
        with patch.object(delivery.scout, "fetch") as fetch:
            with self.assertRaises(delivery.SourceEvidenceRequired):
                delivery.load_source(rows["comparison"])
        fetch.assert_not_called()
        self.assertEqual(before, (self.root / "scout.sqlite").read_bytes())

    def test_owner_language_filters_before_scan_limit_and_stays_unclaimable(self):
        import kimi_scout_delivery as intake

        suffixes = {"go": ".go", "rust": ".rs", "typescript": ".tsx",
                    "javascript": ".mjs", "cpp": ".hpp", "python": ".py"}
        for index, (language, suffix) in enumerate(suffixes.items()):
            self.add(language, packet(sources=[{"url": RAW.replace(".py", suffix)}]), finished=index)
        self.add("cuda", packet(sources=[{"url": RAW.replace(".py", ".cu")}]), finished=100)
        before = (self.root / "scout.sqlite").read_bytes()
        folder = self.root / "delivery"
        intake.initialize(folder)
        for language in suffixes:
            with self.subTest(language=language):
                rows = delivery.select_leads(self.root, owner_language=language, scan_limit=1)
                self.assertEqual([row["id"] for row in rows], [language])
                self.assertEqual(rows[0]["verification_route"], "OWNER_REVIEW_ONLY")
                with self.assertRaisesRegex(ValueError, "owner_review=True"):
                    intake.stage(folder, rows)
                self.assertEqual(intake.stage(folder, rows, owner_review=True), 1)
                self.assertIsNone(intake.claim(folder))
        self.assertEqual(before, (self.root / "scout.sqlite").read_bytes())
        self.assertEqual(list((folder / "jobs").iterdir()), [])

    def test_native_cpu_and_repository_exclusion_precede_scan_limit(self):
        self.add("python", finished=30)
        self.add("busy", packet(repo="busy/repo", sources=[{
            "url": RAW.replace(REPO, "busy/repo").replace(".py", ".go"),
        }]), finished=20)
        self.add("rust", packet(sources=[{"url": RAW.replace(".py", ".rs")}]), finished=10)
        rows = delivery.select_leads(self.root, native_cpu=True, exclude_repos=["busy/repo"], scan_limit=1)
        self.assertEqual([row["id"] for row in rows], ["rust"])
        self.assertEqual(rows[0]["verification_route"], "OWNER_REVIEW_ONLY")

    def test_owner_repository_withdrawal_precedes_history_scan(self):
        self.add("withdrawn", packet(repo="Withdrawn/Project"), finished=30)
        self.add("eligible", finished=10)
        before = (self.root / "scout.sqlite").read_bytes()
        for mode in ({"owner_review": True}, {"owner_language": "python"}):
            with self.subTest(mode=mode):
                rows = delivery.select_leads(
                    self.root, limit=1, scan_limit=1,
                    exclude_repos=["withdrawn/project"], **mode,
                )
                self.assertEqual([row["id"] for row in rows], ["eligible"])
                self.assertEqual(rows[0]["verification_route"], "OWNER_REVIEW_ONLY")
        self.assertEqual(before, (self.root / "scout.sqlite").read_bytes())

    def test_invalid_immutable_url_does_not_consume_scan_limit(self):
        for index, url in enumerate((RAW + "?download=1", RAW.replace("/src/", "/../"),
                                     RAW.replace(REPO, "other/project"), RAW.replace(COMMIT, "main"))):
            self.add("invalid" + str(index), packet(sources=[{"url": url}]), finished=20 + index)
        self.add("valid", finished=1)
        self.assertEqual([row["id"] for row in delivery.select_leads(self.root, scan_limit=1)], ["valid"])

    def test_cited_native_target_not_python_companion_before_limit(self):
        native = RAW.replace(".py", ".go")
        self.add("mixed", packet(sources=[{"url": RAW}, {"url": native}]),
                 evidence=[{"url": native}], finished=2)
        self.add("python", finished=1)
        self.assertEqual([row["id"] for row in delivery.select_leads(self.root, scan_limit=1)], ["python"])
        self.assertEqual([row["id"] for row in delivery.select_leads(
            self.root, owner_language="go", scan_limit=1)], ["mixed"])

    def test_invalid_analysis_does_not_consume_scan_limit(self):
        self.add("malformed", finished=3)
        self.db.execute("UPDATE jobs SET result=? WHERE id='malformed'", (json.dumps({"analysis": "bad"}),))
        self.db.commit()
        self.add("fresh", finished=1)
        self.assertEqual([row["id"] for row in delivery.select_leads(self.root, scan_limit=1)], ["fresh"])

    def test_explicit_exclusions_do_not_consume_scan_limit(self):
        self.add("excluded", finished=2)
        self.add("fresh", finished=1)
        self.assertEqual([row["id"] for row in delivery.select_leads(
            self.root, exclude_source_ids=["excluded"], scan_limit=1)], ["fresh"])

    def test_unresolved_issue_only_lead_remains_visible_without_source_fetch(self):
        issue = f"https://github.com/{REPO}/issues/1"
        self.add("issue", packet(sources=[{"url": RAW}, {"url": issue}]), evidence=[{"url": issue}])
        rows = delivery.select_leads(self.root)
        self.assertEqual([row["id"] for row in rows], ["issue"])
        with patch.object(delivery.scout, "fetch") as fetch:
            with self.assertRaises(delivery.SourceEvidenceRequired):
                delivery.load_source(rows[0])
        fetch.assert_not_called()

    def test_owner_modes_validate_before_io(self):
        for options in ({"native_cpu": 1}, {"owner_language": "cuda"},
                        {"owner_language": "go", "native_cpu": True},
                        {"owner_language": "go", "owner_review": True},
                        {"native_cpu": True, "owner_review": True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                delivery.select_leads(self.root / "missing", **options)

    def test_owner_review_exact_ids_do_not_bypass_existing_delivery(self):
        self.add("staged", packet(sources=[{"url": RAW.replace(".py", ".go")}]))
        self.add("failed-staged-followup", packet(parent="staged"), state="FAILED")
        self.add("fresh", packet(sources=[{"url": RAW.replace(".py", ".rs")}]))
        folder = self.root / "delivery"
        folder.mkdir()
        with closing(sqlite3.connect(folder / "delivery.sqlite")) as db, db:
            db.execute("CREATE TABLE delivery (source_job_id TEXT UNIQUE)")
            db.execute("INSERT INTO delivery VALUES ('staged')")
        rows = delivery.select_leads(
            self.root, owner_review=True, source_ids=["staged", "fresh"], scan_limit=2
        )
        self.assertEqual([row["id"] for row in rows], ["fresh"])
        self.assertEqual(
            delivery.select_leads(self.root, owner_review=True, source_ids=["staged"]), []
        )

    def test_owner_review_selection_cannot_schedule_native_work(self):
        import kimi_scout_delivery as intake

        self.add("go", packet(sources=[{"url": RAW.replace(".py", ".go")}]))
        self.add("failed", packet(parent="go"), state="FAILED")
        leads = delivery.select_leads(self.root, owner_review=True)
        self.assertEqual([r["id"] for r in leads], ["go"])
        self.assertEqual(leads[0]["owner_failed_followups"]["job_ids"], ["failed"])
        folder = self.root / "delivery"
        intake.initialize(folder)
        with self.assertRaisesRegex(ValueError, "owner_review=True"):
            intake.stage(folder, leads)
        with intake.database(folder) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM delivery").fetchone()[0], 0)
        self.assertEqual(intake.stage(folder, leads, owner_review=True), 1)
        self.assertIsNone(intake.claim(folder))
        self.assertEqual(list((folder / "jobs").iterdir()), [])

    def test_owner_deferral_advice_preserves_lead_and_original_evidence(self):
        from scout_publication_context import owner_source_note_path

        self.add("fresh", hypothesis="distinct failure in the same file")
        path = owner_source_note_path(self.root, REPO)
        path.parent.mkdir()
        notes = [{
            "repo": REPO,
            "prior_hypothesis": "old hypothesis, not this new failure",
            "source_url": RAW.replace(COMMIT, "b" * 40),
            "reason": "An older caller already handled the old case.",
            "reopen_when": "A distinct supported failure or changed caller.",
            "evidence_url": f"https://github.com/{REPO}/blob/{'b' * 40}/{PATH}",
        }]
        path.write_text(json.dumps(notes), encoding="utf-8")
        db_before = (self.root / "scout.sqlite").read_bytes()
        notes_before = path.read_bytes()
        automatic, = delivery.select_leads(self.root)
        owner, = delivery.select_leads(self.root, owner_review=True)
        self.assertNotIn("owner_deferrals", automatic)
        self.assertEqual(owner["id"], automatic["id"])
        self.assertEqual(owner["analysis"], automatic["analysis"])
        self.assertEqual(owner["packet"], automatic["packet"])
        self.assertEqual(owner["canonical_key"], automatic["canonical_key"])
        self.assertIn("owner_deferrals", owner)
        context = owner["owner_deferrals"]
        self.assertIn("Never reject a lead from this memory alone", context["caution"])
        self.assertEqual(context["items"][0]["reopen_when"], notes[0]["reopen_when"])
        self.assertEqual(context["items"][0]["evidence_url"], notes[0]["evidence_url"])
        self.assertEqual((self.root / "scout.sqlite").read_bytes(), db_before)
        self.assertEqual(path.read_bytes(), notes_before)

    def test_owner_advice_is_read_only_for_final_selected_leads(self):
        for i in range(3):
            self.add(f"lead{i}", finished=i)
        with patch.object(delivery, "owner_deferral_context", return_value=None) as read:
            rows = delivery.select_leads(self.root, limit=1, owner_review=True)
        self.assertEqual([row["id"] for row in rows], ["lead2"])
        read.assert_called_once_with(
            self.root, REPO, rows[0]["packet"]["sources"],
            prior_analysis=delivery.scout.dumps({"title": rows[0]["analysis"]["title"]}),
        )
        self.assertNotIn("owner_deferrals", rows[0])
        with patch.object(delivery, "owner_deferral_context") as read:
            delivery.select_leads(self.root, limit=1)
        read.assert_not_called()

    def test_long_analysis_still_focuses_owner_advice_by_title_only(self):
        from scout_publication_context import owner_source_note_path

        self.add("fresh", hypothesis="OtherClass " * 400)
        result = {
            "analysis": {
                "title": "restore_state failure",
                "hypothesis": "OtherClass " * 400,
            }
        }
        self.db.execute("UPDATE jobs SET result=?", (json.dumps(result),))
        self.db.commit()
        path = owner_source_note_path(self.root, REPO)
        path.parent.mkdir()
        notes = [
            {
                "repo": REPO,
                "prior_hypothesis": title,
                "source_url": RAW,
                "reason": "Prior native control for " + title,
                "reopen_when": "A distinct supported failure",
                "evidence_url": f"https://github.com/{REPO}/blob/{COMMIT}/{PATH}",
            }
            for title in ("restore_state refuted", "OtherClass newer", "ThirdClass latest")
        ]
        path.write_text(json.dumps(notes), encoding="utf-8")
        before = (self.root / "scout.sqlite").read_bytes()
        owner, = delivery.select_leads(self.root, owner_review=True)
        self.assertEqual(
            owner["owner_deferrals"]["items"][0]["prior_hypothesis"],
            "restore_state refuted",
        )
        self.assertEqual(owner["analysis"], result["analysis"])
        self.assertEqual((self.root / "scout.sqlite").read_bytes(), before)

    def test_corrupt_owner_advice_does_not_hide_a_candidate(self):
        from scout_publication_context import owner_source_note_path

        self.add("fresh")
        path = owner_source_note_path(self.root, REPO)
        path.parent.mkdir()
        path.write_text("not json", encoding="utf-8")
        rows = delivery.select_leads(self.root, owner_review=True)
        self.assertEqual([row["id"] for row in rows], ["fresh"])
        self.assertNotIn("owner_deferrals", rows[0])

    def test_owner_review_requires_explicit_boolean(self):
        for value in (1, "false", None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "boolean"):
                delivery.select_leads(self.root, owner_review=value)

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

    def test_loads_unique_cited_module_not_first_companion(self):
        companion = RAW.replace("check.py", "companion.py")
        value = lead(packet(sources=[{"url": companion}, {"url": RAW}]))
        value["analysis"] = {"evidence": [{"url": RAW}]}
        self.assertEqual(delivery.load_source(value)["url"], RAW)
        self.assertEqual([call[0] for call in self.calls], [API, RAW])

    def test_unresolved_or_unobserved_citations_never_fetch(self):
        issue = f"https://github.com/{REPO}/issues/1"
        other = RAW.replace("check.py", "other.py")
        mutable = RAW.replace(COMMIT, "main")
        foreign = RAW.replace(REPO, "other/project")
        sources = [{"url": url} for url in (RAW, other, issue, mutable, foreign)]
        for evidence in ([], [{"url": issue}], [{"url": RAW}, {"url": other}],
                         [{"url": RAW + "?not-supplied"}], [{"url": mutable}],
                         [{"url": foreign}], ["not a citation"], "not a list"):
            value = lead(packet(sources=sources))
            value["analysis"] = {"evidence": evidence}
            with self.subTest(evidence=evidence), self.assertRaises(delivery.SourceEvidenceRequired):
                delivery.load_source(value)
        self.assertEqual(self.calls, [])

    def test_issue_and_one_supplied_code_citation_resolve(self):
        issue = f"https://github.com/{REPO}/issues/1"
        value = lead(packet(sources=[{"url": RAW}]))
        value["packet"]["related_open_items_sample"] = [{"url": issue}]
        value["analysis"] = {"evidence": [{"url": issue}, {"url": RAW}, {"url": RAW}]}
        self.assertEqual(delivery.load_source(value)["url"], RAW)

    def test_native_primary_is_not_recast_as_python_companion(self):
        value = lead(packet(sources=[{"url": RAW.replace(".py", ".cu")}, {"url": RAW}]))
        with self.assertRaises(delivery.UnsupportedEnvironment):
            delivery.load_source(value)
        self.assertEqual(self.calls, [])

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

    def test_legacy_first_code_source_not_model_suggested_url(self):
        value = packet(
            sources=[
                {"url": RAW.replace(".py", ".md"), "text": "x"},
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
