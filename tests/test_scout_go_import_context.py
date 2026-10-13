"""Offline same-module cached Go acquisition hints, not an import resolver."""
import sys
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_import_context import import_requests
from scout_go_context import go_declaration_anchor
import kimi_scout as scout
import kimi_scout_context as context
import kimi_scout_research as research

PIN = "a" * 40
REPO = "owner/repo"
MOD = "example.org/actual/project"


class GoImportContextTests(unittest.TestCase):
    def request(self, *, raw=None, request="definition(mem.SetUID)",
                module="module " + MOD + "\n", helpers=None,
                path="caller.go", extras=(), sources=(), limit=2):
        raw = raw if raw is not None else 'package p\nimport "' + MOD + '/mem"\n'
        helpers = helpers if helpers is not None else {
            "mem/file.go": "package mem\nfunc SetUID() {}\nfunc SetGID() {}\n",
        }
        module_file = path.rpartition("/")[0] + "/go.mod" if "/" in path else "go.mod"
        texts = {path: raw, module_file: module, **helpers}
        cache = Mock(side_effect=lambda repo, pin, p: texts.get(p))
        url = f"https://raw.githubusercontent.com/{REPO}/{PIN}/{path}"
        packet = dict(repo=REPO, sources=[dict(url=url, text="partial caller"), *sources])
        snapshot = dict(commit=PIN, files=[*texts, *extras])
        actual = import_requests(packet, snapshot, dict(next_check=request), cache, limit=limit)
        self.assertTrue(all(call.args[:2] == (REPO, PIN) for call in cache.call_args_list))
        self.assertLessEqual(len(actual), limit)
        for read in actual:
            if "start" in read:
                self.assertIn("Not a bound caller", read["go_import_hint"]["scope"])
        return [{k: v for k, v in read.items() if k != "go_import_hint"} for read in actual], cache, packet, snapshot

    def test_default_package_name_comes_from_cached_source_not_repository_or_directory(self):
        actual, _, _, _ = self.request(raw='package p\nimport "' + MOD + '/different-name"\n',
            helpers={"different-name/file.go": "package mem\nfunc SetUID() {}\n"})
        self.assertEqual(actual, [dict(path="different-name/file.go", start=2, max_lines=80)])

    def test_explicit_alias_grouped_import_and_comments(self):
        actual, _, _, _ = self.request(
            raw='// header\npackage p\nimport (\n// note\n m "' + MOD + '/mem"\n_ "os"\n. "fmt"\n)\n',
            request="definition(m.SetUID)")
        self.assertEqual(actual, [dict(path="mem/file.go", start=2, max_lines=80)])

    def test_raw_import_path_and_two_functions_share_the_original_two_read_cap(self):
        actual, _, _, _ = self.request(raw='package p\nimport `' + MOD + '/mem`\n',
            request="definition(mem.SetUID) definition(mem.SetGID)")
        self.assertEqual(actual, [dict(path="mem/file.go", start=2, max_lines=80),
                                  dict(path="mem/file.go", start=3, max_lines=80)])
        actual, _, _, _ = self.request(request="definition(mem.SetUID) definition(mem.SetGID)", limit=1)
        self.assertEqual(len(actual), 1)

    def test_missing_cached_observed_module_requests_metadata_before_assuming_a_module_path(self):
        actual, cache, _, _ = self.request(module=None)
        self.assertEqual(actual, [dict(path="go.mod", hints="module directive", max_lines=80)])
        self.assertEqual([call.args[2] for call in cache.call_args_list], ["caller.go", "go.mod"])

    def test_closest_nested_module_uses_its_own_directive(self):
        actual, _, _, _ = self.request(path="nested/caller.go", extras=("go.mod",),
            helpers={"nested/mem/file.go": "package mem\nfunc SetUID() {}\n"})
        self.assertEqual(actual, [dict(path="nested/mem/file.go", start=2, max_lines=80)])

    def test_nested_module_at_import_target_is_not_part_of_the_callers_module(self):
        actual, _, _, _ = self.request(extras=("mem/go.mod",))
        self.assertEqual(actual, [])

    def test_external_dependency_dot_blank_wrong_alias_and_method_only_abstain(self):
        for raw, helpers in (
            ('package p\nimport "external.example/mem"\n', None),
            ('package p\nimport . "' + MOD + '/mem"\n', None),
            ('package p\nimport _ "' + MOD + '/mem"\n', None),
            ('package p\nimport other "' + MOD + '/mem"\n', None),
            ('package p\nimport "' + MOD + '/mem"\n',
             {"mem/file.go": "package mem\nfunc (mem) SetUID() {}\n"}),
        ):
            with self.subTest(raw=raw, helpers=helpers):
                self.assertEqual(self.request(raw=raw, helpers=helpers)[0], [])
        self.assertIsNone(go_declaration_anchor(
            'package mem\nfunc (mem) SetUID() {}\n', 'definition(mem.SetUID)', free_only=True))

    def test_comments_and_raw_strings_do_not_invent_an_import(self):
        for raw in (
            'package p\n// import "' + MOD + '/mem"\n',
            'package p\nvar text = `\nimport "' + MOD + '/mem"\n`\n',
            'package p\n/* import "' + MOD + '/mem" */\n',
        ):
            self.assertEqual(self.request(raw=raw)[0], [])

    def test_competing_cached_files_default_bindings_and_explicit_aliases_abstain(self):
        for raw, helpers in (
            (None, {"mem/one.go": "package mem\nfunc SetUID() {}\n",
                    "mem/two.go": "package mem\nfunc SetUID() {}\n"}),
            ('package p\nimport ("' + MOD + '/one"; "' + MOD + '/two")\n',
             {"one/file.go": "package mem\nfunc SetUID() {}\n",
              "two/file.go": "package mem\nfunc Other() {}\n"}),
            ('package p\nimport (mem "' + MOD + '/one"; mem "external.example/two")\n',
             {"one/file.go": "package mem\nfunc SetUID() {}\n"}),
        ):
            self.assertEqual(self.request(raw=raw, helpers=helpers)[0], [])

    def test_unread_cached_package_files_are_unknown_not_missing_definitions(self):
        actual, _, _, _ = self.request(extras=("mem/other_os.go",))
        # One observed cached declaration is useful advice, not a claim that
        # this unread/build-dependent file contains no competing declaration.
        self.assertEqual(actual, [dict(path="mem/file.go", start=2, max_lines=80)])
        self.assertEqual(self.request(helpers={"mem/file.go": None})[0], [])

    def test_test_files_and_already_supplied_windows_do_not_consume_reads(self):
        actual, _, _, _ = self.request(helpers={
            "mem/file.go": "package mem\nfunc SetUID() {}\n",
            "mem/file_test.go": "package mem\nfunc SetUID() {}\n",
        }, sources=[dict(url=f"https://raw.githubusercontent.com/{REPO}/{PIN}/mem/file.go",
                         start_line=1, end_line=2, text="whole file")])
        self.assertEqual(actual, [])

    def test_package_scan_and_byte_limits_do_not_add_acquisitions(self):
        actual, cache, _, _ = self.request(extras=tuple(f"mem/extra{i}.go" for i in range(16)))
        self.assertEqual(actual, [])
        self.assertEqual([c.args[2] for c in cache.call_args_list], ["caller.go", "go.mod"])
        large = "package mem\n" + " " * 131000
        actual, cache, _, _ = self.request(helpers={f"mem/file{i}.go": large for i in range(9)})
        self.assertEqual(actual, [])
        self.assertLessEqual(len(cache.call_args_list), 11)

    def test_malformed_requests_module_identity_and_escaped_paths_abstain(self):
        for request in ("Inspect mem.SetUID", "definition(SetUID)",
                        "definition(mem.SetUID, other)", "definition(mem.SetUID) definition(SetGID)",
                        "definition(mem.SetUID) definition(mem.SetGID) definition(mem.Other)"):
            self.assertEqual(self.request(request=request)[0], [])
        for module in ('module ../escape\n', 'module "' + MOD + '"\n',
                       'module ' + MOD + '\nmodule other\n', 'go 1.26\n'):
            self.assertEqual(self.request(module=module)[0], [])
        for imported in (MOD + '/mem/../mem', MOD + r'/m\x65m'):
            self.assertEqual(self.request(raw='package p\nimport "' + imported + '"\n')[0], [])

    def test_real_followup_import_hop_keeps_two_reads_pin_and_hint_scope(self):
        texts = {
            "caller.go": 'package p\nimport "' + MOD + '/mem"\nfunc Caller() { mem.SetUID() }\n',
            "go.mod": "module " + MOD + "\n",
            "mem/file.go": 'package mem\n' + '\n' * 200 + 'func SetUID() {\n panic("NOT_EXECUTED")\n}\n',
        }

        class Reader(context.PublicContext):
            def snapshot(self, repo, ref="main"):
                return dict(commit=PIN, files=list(texts), blobs={p: "b" * 40 for p in texts})

            def cached_source_text(self, repo, commit, path):
                return texts.get(path)

            def _source_text(self, repo, blob, url):
                return texts[url.split(PIN + "/", 1)[1]], "injected"

            def duplicate_sources(self, *args):
                return []

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scout.initialize(root)
            config = root / "config.json"
            config.write_text(json.dumps(dict(objective="Go helper acquisition",
                queue_target=4, repos=[dict(repo=REPO, source_prefixes=["caller.go", "mem/"],
                    question="Check actual helpers", followup_import_context=True)])), encoding="utf-8")
            reader = Reader(root)
            with patch.object(research, "lesson_suggestions", return_value={"status": "NO_MATCH"}):
                producer = research.ResearchProducer(root, config, context=reader)
                producer.lessons = []
                spec = producer.config["repos"][0]
                producer.emit("initial", spec, [dict(
                    url=f"https://raw.githubusercontent.com/{REPO}/{PIN}/caller.go",
                    text="3: func Caller() { mem.SetUID() }")], "source_audit")
                with scout.connect(root) as db:
                    db.execute("UPDATE jobs SET state='NEEDS_CONTEXT',finished=?,result=?", (
                        time.time(), scout.dumps(dict(analysis=dict(title="caller.go helper",
                        hypothesis="Unverified missing lock", decision="needs_context",
                        next_check="definition(mem.SetUID)", evidence=[])))))
                with patch.object(reader, "source", wraps=reader.source) as reads:
                    self.assertTrue(producer.followup(spec, {}))
                self.assertLessEqual(reads.call_count, 2)
                with scout.connect(root) as db:
                    packets = [json.loads(row[0]) for row in db.execute("SELECT packet FROM jobs")]
                emitted = next(p for p in packets if "untrusted_prior_analysis" in p)
                helper = next(s for s in emitted["sources"] if s["url"].endswith("/mem/file.go"))
                self.assertEqual(helper["start_line"], 202)
                self.assertIn('panic("NOT_EXECUTED")', helper["text"])
                self.assertIn("Not a bound caller", helper["go_import_hint"]["scope"])
                self.assertNotIn("requested_definition_complete", helper)
                self.assertTrue(all(PIN in s["url"] for s in emitted["sources"]))
                self.assertLessEqual(len((scout.SYSTEM + scout.dumps(emitted)).encode()), scout.MAX_INPUT_BYTES)


if __name__ == "__main__":
    unittest.main()
