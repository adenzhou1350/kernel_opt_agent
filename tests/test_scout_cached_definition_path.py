"""Bounded cached declaration routing is not semantic receiver resolution."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_requested_definition import cached_qualified_definition_path


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
