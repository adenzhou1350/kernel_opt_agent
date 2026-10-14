"""Synthetic retrieval arithmetic/boundary checks, never useful-bug labels."""
import hashlib
import json
import math
import unittest
from unittest.mock import patch

from scripts.scout_bm25_source import bm25_choice, bm25_scores, tokens
from scripts.scout_shadow_comparison import make_view, observe, run_arm


def view_for(texts, query):
    assets={path:dict(text=text,sha256=hashlib.sha256(text.encode()).hexdigest()) for path,text in texts.items()}
    packet=dict(repo='o/r',sources=[dict(url='https://raw.githubusercontent.com/o/r/'+'a'*40+'/first.go',text='original snippet')],untrusted_prior_analysis=json.dumps(dict(hypothesis=query,next_check='')))
    return make_view(packet,repo='o/r',commit='a'*40,assets=assets),assets


class BM25Tests(unittest.TestCase):
    def test_formula_common_terms_and_binary_query_frequency(self):
        scores=bm25_scores(['rare'],[['rare'],['other']])
        self.assertAlmostEqual(scores[0],math.log(2))
        self.assertEqual(scores[1],0)
        self.assertEqual(scores,bm25_scores(['rare','rare'],[['rare'],['other']]))
        self.assertGreater(bm25_scores(['common'],[['common'],['common']])[0],0)

    def test_identifier_aware_tokenization_is_explicit(self):
        self.assertEqual(tokens('NewUUID state_id'),['newuuid','new','uuid','state_id','state','id'])

    def test_relevant_later_file_not_first_continuation_and_cost_retained(self):
        view,assets=view_for({'a.go':'unrelated\n','consumer.go':'func CheckOwner() {}\n'},'CheckOwner')
        selected=bm25_choice(view,assets)
        self.assertEqual(selected['path'],'consumer.go')
        self.assertEqual(selected['retrieval']['files_indexed'],2)
        self.assertEqual(selected['retrieval']['logical_index_bytes'],sum(len(a['text'].encode()) for a in assets.values()))
        self.assertEqual(observe(selected,assets)['status'],'ACQUIRED')

    def test_exact_range_survives_character_fit_without_gaps(self):
        text='x'*3000+'\n'+'y'*3000+'\nfunc RareTarget() {}\n'
        view,assets=view_for({'a.go':text},'RareTarget')
        selected=bm25_choice(view,assets)
        result=observe(selected,assets)
        self.assertEqual(result['status'],'ACQUIRED')
        self.assertIn('RareTarget',result['excerpts']['windows'][0]['text'])
        self.assertLessEqual(result['excerpts']['selected_chars'],4500)

    def test_oversized_line_does_not_hide_following_code(self):
        view,assets=view_for({'a.go':'x'*5000+'\nRareTarget\n'},'RareTarget')
        selected=bm25_choice(view,assets)
        self.assertEqual(selected['ranges'],[dict(start_line=2,line_count=1)])
        self.assertEqual(selected['retrieval']['skipped_windows'],1)

    def test_stable_tie_break_and_no_overlap_match_abstention(self):
        view,assets=view_for({'z.go':'match\n','a.go':'match\n'},'match')
        self.assertEqual(bm25_choice(view,assets)['path'],'a.go')
        view['catalog'].reverse()
        self.assertEqual(bm25_choice(view,assets)['path'],'a.go')
        view['packet']['untrusted_prior_analysis']=json.dumps(dict(hypothesis='UnobservedSymbol'))
        self.assertEqual(bm25_choice(view,assets)['status'],'ABSTAIN')

    def test_hash_line_count_foreign_repo_and_mixed_revision_rejected(self):
        mutations=[
            (lambda v,a:a['a.go'].update(sha256='0'*64),'ASSET_IDENTITY_MISMATCH'),
            (lambda v,a:v['catalog'][0].update(lines=True),'LINE_COUNT_MISMATCH'),
            (lambda v,a:v['catalog'][0].update(url=v['catalog'][0]['url'].replace('/o/r/','/other/r/')),'CATALOG_REPOSITORY_MISMATCH'),
            (lambda v,a:v['catalog'][1].update(url=v['catalog'][1]['url'].replace('a'*40,'b'*40)),'CATALOG_REVISION_MISMATCH'),
        ]
        for mutate,error in mutations:
            with self.subTest(error=error):
                view,assets=view_for({'a.go':'target','b.go':'second'},'target')
                mutate(view,assets)
                self.assertEqual(bm25_choice(view,assets)['error_kind'],error)

    def test_limits_and_invalid_queries_are_not_silent_fallbacks(self):
        for prior,error in [('[]','INVALID_PRIOR'),('bad json','INVALID_PRIOR'),(json.dumps(dict(hypothesis=[])),'INVALID_QUERY'),(json.dumps(dict(hypothesis='x'*8001)),'QUERY_LIMIT')]:
            view,assets=view_for({'a.go':'target'},'target')
            view['packet']['untrusted_prior_analysis']=prior
            self.assertEqual(bm25_choice(view,assets)['status'],'UNAVAILABLE')
            self.assertEqual(bm25_choice(view,assets)['error_kind'],error)
        view,assets=view_for({'a.go':'target'},'')
        self.assertEqual(bm25_choice(view,assets)['status'],'ABSTAIN')
        view['catalog']*=65
        self.assertEqual(bm25_choice(view,assets)['error_kind'],'CATALOG_LIMIT_OR_INVALID')

    def test_runner_keeps_two_calls_and_does_not_send_full_corpus(self):
        view,assets=view_for({'a.go':'target\n'+'\n'*85+'UNSELECTED_SECRET_SENTINEL\n'},'target')
        prompts=[]
        def invoke(provider,prompt,cap):
            prompts.append(prompt)
            value=dict(verdict='INSUFFICIENT',decisive_evidence=None,reason='no oracle',next_native_check=None)
            return dict(response=dict(ok=True,text=json.dumps(value)),normalized_total_tokens=2)
        result=run_arm(view,assets,('bm25','kimi','bm25','kimi'),invoke)
        self.assertEqual(len(prompts),2)
        self.assertTrue(result['protocol_valid'])
        self.assertIn('retrieval',result['selection'])
        self.assertTrue(all('UNSELECTED_SECRET_SENTINEL' not in p for p in prompts))

    def test_corpus_document_limits_retain_spent_index_cost(self):
        view,assets=view_for({'a.go':'target\n'*100},'target')
        with patch('scripts.scout_bm25_source.MAX_BYTES',10):
            selected=bm25_choice(view,assets)
        self.assertEqual(selected['error_kind'],'CORPUS_BYTE_LIMIT')
        self.assertEqual(selected['retrieval']['logical_index_bytes'],len(assets['a.go']['text'].encode()))
        with patch('scripts.scout_bm25_source.MAX_DOCUMENTS',1):
            selected=bm25_choice(view,assets)
        self.assertEqual(selected['error_kind'],'DOCUMENT_LIMIT')
        self.assertEqual(selected['retrieval']['documents'],1)

    def test_query_term_limit_rejects_before_corpus_read(self):
        view,assets=view_for({'a.go':'target'},' '.join('word'+str(i) for i in range(257)))
        selected=bm25_choice(view,assets)
        self.assertEqual(selected['error_kind'],'QUERY_TERM_LIMIT')
        self.assertEqual(selected['retrieval']['logical_index_bytes'],0)


if __name__=='__main__':
    unittest.main()
