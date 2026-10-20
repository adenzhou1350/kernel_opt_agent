"""Bounded cached declaration routing is not semantic receiver resolution."""
from pathlib import Path
import hashlib
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_requested_definition import (
    cached_definition_pair_requests,
    cached_definition_tail_request,
    cached_qualified_definition_path,
)


class CachedDefinitionTailTests(unittest.TestCase):
    def setUp(self):
        self.old, self.new = "a" * 40, "b" * 40
        self.path = "src/policy.py"
        self.raw = "def select_backend():\n" + "    # implementation detail\n" * 150 + "    return 'selected'\n"
        body = self.raw.encode()
        blob = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
        self.snapshot = dict(commit=self.new, files=[self.path], blobs={self.path: blob})
        self.source = dict(url=f"https://raw.githubusercontent.com/a/b/{self.old}/{self.path}",
                           start_line=1, end_line=65, total_lines=152, truncated=True,
                           requested_definition_complete=False,
                           requested_definition=dict(name="select_backend", start_line=1, end_line=152))
        self.packet = dict(repo="a/b", sources=[self.source])
        self.analysis = dict(next_check="definition(select_backend) lines 80-152")
        self.calls = []

    def read(self, *identity):
        self.calls.append(identity)
        return self.raw

    def select(self):
        return cached_definition_tail_request(self.packet, self.snapshot, self.analysis, self.read)

    def test_same_blob_cross_revision_continues_after_delivered_prefix(self):
        self.assertEqual(self.select(), dict(path=self.path, start=66, max_lines=87))
        self.assertEqual(self.calls, [("a/b", self.old, self.path)])

    def test_changed_blob_missing_cache_and_ambiguous_target_abstain(self):
        original = self.snapshot['blobs'][self.path]
        self.snapshot['blobs'][self.path] = "c" * 40
        self.assertIsNone(self.select())
        self.snapshot['blobs'][self.path] = original
        for request in ("references(select_backend)", "definition(select_backend) references(other)",
                        "definition(other)", "definition(select_backend) definition(other)"):
            self.analysis['next_check'] = request
            self.assertIsNone(self.select())
        self.assertIsNone(cached_definition_tail_request(self.packet, self.snapshot, self.analysis, None))
        self.analysis['next_check'] = 'definition(select_backend)'
        self.assertIsNone(cached_definition_tail_request(
            self.packet, self.snapshot, self.analysis, lambda *args: None
        ))

    def test_complete_invalid_metadata_and_other_file_cannot_select_a_tail(self):
        for changes in ({'requested_definition_complete': True}, {'truncated': False}, {'end_line': True},
                        {'end_line': 152}, {'total_lines': 153},
                        {'requested_definition': dict(name='select_backend', start_line=1, end_line=153)},
                        {'url': self.source['url'].replace('policy.py', 'missing.py')}):
            with self.subTest(changes=changes):
                self.packet['sources'] = [{**self.source, **changes}]
                self.assertIsNone(self.select())

    def test_explicit_other_file_is_not_overridden(self):
        self.analysis['next_check'] = 'definition(select_backend) in src/other.py'
        self.assertIsNone(self.select())

    def test_explicit_head_or_outside_range_is_not_reinterpreted_as_tail(self):
        for request in ('definition(select_backend) before line 66',
                        'definition(select_backend) 获取10-65行',
                        'definition(select_backend) lines 60-200',
                        'definition(select_backend) lines 152-80'):
            with self.subTest(request=request):
                self.analysis['next_check'] = request
                self.assertIsNone(self.select())

    def test_furthest_fragment_of_same_target_reuses_one_cached_read(self):
        self.packet['sources'].append({**self.source, 'start_line': 60, 'end_line': 120})
        self.assertEqual(self.select(), dict(path=self.path, start=121, max_lines=32))
        self.assertEqual(len(self.calls), 1)


class CachedDefinitionPathTests(unittest.TestCase):
    def setUp(self):
        self.repo = "public/project"
        self.commit = "a" * 40
        self.host = "src/pool/mha.py"
        self.adapter = "src/adapters/mha.py"
        self.snapshot = dict(commit=self.commit, files=[self.host, self.adapter])
        self.packet = dict(repo=self.repo, sources=[dict(url=f"https://raw.githubusercontent.com/{self.repo}/{self.commit}/{p}") for p in [self.adapter,self.host]])
        self.analysis = dict(next_check="definition(HostPool.__init__) in mha.py")
        self.cache = {self.adapter:"class Adapter:\n    pass\n", self.host:"class HostPool:\n    def __init__(self):\n        self.value = 1\n"}
        self.calls = []

    def read(self, repo, commit, path):
        self.calls.append((repo,commit,path))
        return self.cache.get(path)

    def select(self):
        return cached_qualified_definition_path(self.packet,self.snapshot,self.analysis,self.read)

    def test_unique_cached_owner_resolves_same_basename(self):
        self.assertEqual(self.select(),self.host)
        self.assertEqual(len(self.calls),2)
        self.assertTrue(all(c[:2]==(self.repo,self.commit) for c in self.calls))

    def test_missing_or_malformed_cache_does_not_trigger_acquisition(self):
        self.cache[self.host]=None
        self.assertIsNone(self.select())
        self.cache[self.host]="class HostPool: invalid python..."
        self.assertIsNone(self.select())

    def test_multiple_file_or_same_file_owners_abstain(self):
        self.cache[self.adapter]=self.cache[self.host]
        self.assertIsNone(self.select())
        self.cache[self.adapter]=""
        self.cache[self.host]+=self.cache[self.host]
        self.assertIsNone(self.select())

    def anchor_primary_owner(self):
        self.cache[self.adapter] = (
            "class HostPool:\n"
            "    def load(self):\n        return self.mapping()\n"
            "    def __init__(self):\n        self.value = 'adapter'\n"
        )
        body = self.cache[self.adapter].encode()
        self.snapshot['blobs'] = {self.adapter: hashlib.sha1(
            b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()}
        self.packet['sources'][0].update(
            start_line=2, end_line=3,
            python_definition_context=dict(definitions=[dict(
                qualified_name='HostPool.load', start_line=2, end_line=3)]),
        )

    def test_same_named_backend_keeps_verified_primary_lexical_owner(self):
        self.anchor_primary_owner()
        self.assertEqual(self.select(), self.adapter)
        self.assertEqual(len(self.calls), 2)  # No new cache reads or fetches.

    def test_primary_owner_hint_does_not_override_explicit_other_path(self):
        self.anchor_primary_owner()
        self.analysis['next_check'] = 'definition(HostPool.__init__) in ' + self.host
        self.assertEqual(self.select(), self.host)

    def test_primary_owner_hint_does_not_guess_unobserved_other_file(self):
        self.anchor_primary_owner()
        self.analysis['next_check'] = 'definition(HostPool.__init__) in src/foreign.py'
        self.assertIsNone(self.select())

    def test_unverified_or_unrelated_anchor_keeps_ambiguity(self):
        for change in ('blob', 'range', 'owner', 'stale', 'duplicate'):
            with self.subTest(change=change):
                self.anchor_primary_owner()
                source = self.packet['sources'][0]
                anchor = source['python_definition_context']['definitions'][0]
                if change == 'blob':
                    self.snapshot['blobs'][self.adapter] = 'f' * 40
                elif change == 'range':
                    source['start_line'], source['end_line'] = 4, 5
                elif change == 'owner':
                    anchor['qualified_name'] = 'OtherPool.load'
                elif change == 'stale':
                    anchor['end_line'] = 4
                else:
                    self.cache[self.adapter] += '    def load(self):\n        pass\n'
                    body = self.cache[self.adapter].encode()
                    self.snapshot['blobs'][self.adapter] = hashlib.sha1(
                        b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()
                self.assertIsNone(self.select())

    def test_explicit_other_full_path_is_not_overridden(self):
        self.analysis['next_check']+=' '+self.adapter
        self.assertIsNone(self.select())

    def test_multiple_unqualified_or_reference_requests_abstain(self):
        for request in ('definition(__init__)', 'Inspect HostPool.__init__',
                        'definition(HostPool.__init__) definition(Other.method)',
                        'references(field)'):
            with self.subTest(request=request):
                self.analysis['next_check']=request
                self.calls=[]
                self.assertIsNone(self.select())
                self.assertEqual(self.calls,[])

    def test_following_reference_prose_does_not_hide_the_explicit_definition(self):
        self.analysis['next_check'] += '; then use references(field)'
        self.assertEqual(self.select(), self.host)

    def test_only_supplied_pinned_tree_members_are_considered(self):
        self.packet['sources'][1]['url']=self.packet['sources'][1]['url'].replace(self.commit,'b'*40)
        self.assertIsNone(self.select())
        self.assertEqual(len(self.calls),1)

    def test_missing_cache_callback_abstains(self):
        self.assertIsNone(cached_qualified_definition_path(self.packet,self.snapshot,self.analysis,None))

    def test_oversize_or_io_failure_abstains(self):
        self.cache[self.host] = " " * 1_000_001
        self.assertIsNone(self.select())
        def unavailable(*args):
            raise OSError("cached file unavailable")
        self.assertIsNone(cached_qualified_definition_path(
            self.packet, self.snapshot, self.analysis, unavailable
        ))

    def test_duplicate_sources_and_eight_item_cap(self):
        self.packet['sources']=[self.packet['sources'][0]]*8+[self.packet['sources'][1]]
        self.assertIsNone(self.select())
        self.assertEqual(len(self.calls),1)


class CachedDefinitionPairTests(unittest.TestCase):
    def setUp(self):
        self.path = "src/session/server.py"
        self.pin = "a" * 40
        self.raw = (
            "class ServerRole:\n"
            "    def resolve(self):\n        return self.pending\n"
            "    def finalize(self):\n        self.pending.clear()\n"
        )
        body = self.raw.encode()
        blob = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
        self.snapshot = dict(commit=self.pin, files=[self.path], blobs={self.path: blob})
        self.packet = dict(repo="a/b", sources=[dict(
            url=f"https://raw.githubusercontent.com/a/b/{self.pin}/{self.path}",
        )])
        self.analysis = dict(next_check="definition(ServerRole.resolve) and definition(ServerRole.finalize)")
        self.calls = []

    def read(self, *identity):
        self.calls.append(identity)
        return self.raw

    def select(self):
        return cached_definition_pair_requests(self.packet, self.snapshot, self.analysis, self.read)

    def test_two_same_owner_methods_reuse_one_verified_cache_read(self):
        requests = self.select()
        self.assertEqual(requests, [
            dict(path=self.path, max_lines=80, request_hints="definition(ServerRole.resolve)"),
            dict(path=self.path, max_lines=80, request_hints="definition(ServerRole.finalize)"),
        ])
        self.assertEqual(self.calls, [("a/b", self.pin, self.path)])

    def test_invalid_mixed_repeated_and_extra_requests_leave_fallback(self):
        for request in (
            "definition(ServerRole.resolve)",
            "definition(ServerRole.resolve) definition(ServerRole.resolve)",
            "definition(ServerRole.resolve) definition(OtherRole.finalize)",
            "definition(ServerRole.resolve) definition(finalize)",
            "definition(ServerRole.resolve) references(ServerRole.finalize)",
            "definition(ServerRole.resolve) definition(ServerRole.finalize) references(extra)",
            "definition(ServerRole.resolve) definition(ServerRole.finalize",
        ):
            with self.subTest(request=request):
                self.analysis["next_check"] = request
                self.calls.clear()
                self.assertEqual(self.select(), [])
                self.assertEqual(self.calls, [])

    def test_cold_corrupt_oversized_or_missing_snapshot_evidence_abstains(self):
        original = self.raw
        for raw in (None, original + "# changed\n", "x" * 1_000_001):
            self.raw = raw
            self.assertEqual(self.select(), [])
        self.raw = original
        self.snapshot["blobs"] = {}
        self.assertEqual(self.select(), [])

    def test_other_pin_missing_method_or_duplicate_owner_does_not_guess(self):
        self.packet["sources"][0]["url"] = self.packet["sources"][0]["url"].replace(self.pin, "b" * 40)
        self.assertEqual(self.select(), [])
        self.packet["sources"][0]["url"] = self.packet["sources"][0]["url"].replace("b" * 40, self.pin)
        for raw in (self.raw.replace("def finalize", "def unrelated"), self.raw * 2):
            body = raw.encode()
            self.snapshot["blobs"][self.path] = hashlib.sha1(
                b"blob " + str(len(body)).encode() + b"\0" + body
            ).hexdigest()
            self.raw = raw
            self.assertEqual(self.select(), [])

    def test_eight_observed_sources_bound_all_cache_access(self):
        self.packet["sources"] = self.packet["sources"] * 9
        self.assertEqual(len(self.select()), 2)
        self.assertEqual(len(self.calls), 1)

    def test_ninth_distinct_source_is_not_used_or_fetched(self):
        paths = [f"src/other{i}.py" for i in range(8)]
        self.snapshot["files"] += paths
        self.packet["sources"] = [dict(
            url=f"https://raw.githubusercontent.com/a/b/{self.pin}/{p}"
        ) for p in paths] + self.packet["sources"]
        self.assertEqual(self.select(), [])
        self.assertEqual(len(self.calls), 8)
        self.assertNotIn(self.path, [call[2] for call in self.calls])

    def test_two_same_named_owner_files_are_ambiguous(self):
        other = "src/other/server.py"
        self.snapshot["files"].append(other)
        self.snapshot["blobs"][other] = self.snapshot["blobs"][self.path]
        self.packet["sources"].append(dict(
            url=f"https://raw.githubusercontent.com/a/b/{self.pin}/{other}"
        ))
        self.assertEqual(self.select(), [])
        self.assertEqual(len(self.calls), 2)


if __name__ == '__main__':
    unittest.main()
