"""Bounded cached declaration routing is not semantic receiver resolution."""
from pathlib import Path
import hashlib
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_requested_definition import cached_definition_tail_request, cached_qualified_definition_path


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


if __name__ == '__main__':
    unittest.main()
