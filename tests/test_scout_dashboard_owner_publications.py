"""Owner-recorded PRs remain visible without rewriting a negative model leaf."""
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import kimi_scout as scout
import kimi_scout_dashboard as dashboard
from scout_publication_context import owner_publication_note_path


class OwnerPublicationDashboardTests(unittest.TestCase):
    def note(self, repo="public/project", number=1, **kwargs):
        return dict(repo=repo, prior_hypothesis="Earlier source concern",
                    source_url=f"https://raw.githubusercontent.com/{repo}/{'a'*40}/module.py",
                    pr_url=f"https://github.com/{repo}/pull/{number}", **kwargs)

    def write(self, root, notes, repo="public/project"):
        path = owner_publication_note_path(root, repo)
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(notes), encoding="utf-8")
        return path

    def test_negative_leaf_without_delivery_is_visible_and_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            scout.initialize(root)
            identity = scout.enqueue(root, dict(name="prior analysis", repo="public/project",
                question="Check", sources=[{"url": "https://github.com/public/project/issues/1", "text": "x"}]))
            with closing(sqlite3.connect(root / "scout.sqlite")) as db:
                db.execute("UPDATE jobs SET state='NEEDS_CONTEXT' WHERE id=?", (identity,))
                db.commit()
            self.write(root, [self.note()])
            before = (root / "scout.sqlite").read_bytes()
            result = dashboard.Inbox(root).state()
            self.assertEqual(result["owner_publications"]["distinct_recorded_prs"], 1)
            self.assertEqual(result["jobs"][0]["state"], "NEEDS_CONTEXT")
            self.assertIsNone(result["delivery"])
            self.assertFalse((root / "delivery").exists())
            self.assertEqual((root / "scout.sqlite").read_bytes(), before)

    def test_links_deduplicate_and_reject_comments_cross_repo_and_extra_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = self.note()
            notes = [good, good, self.note("other/project"), self.note(extra="not allowed")]
            for suffix in ("#issuecomment-123", "/files"):
                notes.append({**good, "pr_url": good["pr_url"] + suffix})
            self.write(root, notes)
            result = dashboard.recorded_owner_publications(root, ["public/project"])
            self.assertEqual(result["distinct_recorded_prs"], 1)
            self.assertEqual(result["rows"][0]["url"], good["pr_url"])
            self.assertIn("do not add", result["claim_boundary"])

    def test_reader_and_display_are_bounded_without_scanning_unknown_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, [self.note(number=i) for i in range(1, 31)])
            self.write(root, [self.note("unknown/repo")], "unknown/repo")
            result = dashboard.recorded_owner_publications(root, ["public/project"])
            self.assertEqual(result["distinct_recorded_prs"], 24)
            self.assertEqual(len(result["rows"]), 20)
            self.assertEqual(result["repositories_checked"], 1)

    def test_malformed_optional_notes_do_not_break_dashboard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write(root, [])
            for value in ("invalid", "null", "[]", "x" * 65537):
                path.write_text(value)
                self.assertEqual(dashboard.recorded_owner_publications(root, ["public/project"])["rows"], [])

    @unittest.skipUnless(shutil.which("node"), "Node required for actual renderer")
    def test_renderer_is_safe_bounded_and_independent_of_delivery(self):
        script = (SCRIPTS / "kimi_scout_dashboard.html").read_text(encoding="utf-8").split("<script>", 1)[1].split("  function renderHistory() {", 1)[0]
        harness = """
const elements=new Map();
function el(){return {children:[],append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x},set innerHTML(x){throw Error('HTML sink')}}}
global.document={createElement:el,getElementById(id){if(!elements.has(id))elements.set(id,el());return elements.get(id)}};
"""
        exercise = """
state={delivery:null,owner_publications:{distinct_recorded_prs:2,rows:[
{repo:'public/project',url:'https://github.com/public/project/pull/1',prior_hypothesis:'<img src=x onerror=x>'},
{repo:'public/project',url:'javascript:alert(1)'},
{repo:'public/project',url:'https://github.com/other/project/pull/2'}]}};
renderOwnerPublications();
const item=$('ownerPublicationsRows').children[0];
const result={hidden:$('ownerPublicationsPanel').hidden,count:$('ownerPublicationsRows').children.length,
href:item.children[0].href,rel:item.children[0].rel,text:item.children[1].textContent};
state.owner_publications=null;renderOwnerPublications();result.cleared=$('ownerPublicationsRows').children.length;result.absentHidden=$('ownerPublicationsPanel').hidden;
process.stdout.write(JSON.stringify(result));})();
"""
        process = subprocess.run([shutil.which("node"), "-"], input=harness+script+exercise,
                                 capture_output=True, text=True, encoding="utf-8", timeout=10, check=True)
        result = json.loads(process.stdout)
        self.assertFalse(result["hidden"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["text"], "<img src=x onerror=x>")
        self.assertEqual(result["href"], "https://github.com/public/project/pull/1")
        self.assertEqual(result["rel"], "noopener noreferrer")
        self.assertTrue(result["absentHidden"])
        self.assertEqual(result["cleared"], 0)


if __name__ == "__main__":
    unittest.main()
