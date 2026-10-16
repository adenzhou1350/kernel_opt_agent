"""Run the actual bounded query-scope renderer, without HTTP/model calls."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("node"), "Node required for actual renderer")
class RelatedWorkScopeTests(unittest.TestCase):
    def run_renderer(self, exercise):
        page = (Path(__file__).resolve().parents[1] / "scripts/kimi_scout_dashboard.html").read_text(encoding="utf-8")
        renderer = "function renderRelatedWorkScope" + page.split(
            "  function renderRelatedWorkScope", 1
        )[1].split("  function renderPacket", 1)[0]
        harness = r"""
const panel = {children:[], hidden:false, append(...v){this.children.push(...v)},
 replaceChildren(...v){this.children=v},set innerHTML(v){throw Error('Unsafe HTML')}};
function $(id){if(id!=='relatedWorkScope')throw Error(id);return panel;}
function node(tag,cls,value){return {tag,cls,textContent:value??'',children:[],
 append(...v){this.children.push(...v)},set innerHTML(v){throw Error('Unsafe HTML')}};}
function textOf(el){return [el.textContent||'',...(el.children||[]).map(textOf)].join('\n');}
function show(packet,analysis){renderRelatedWorkScope(packet,analysis);return {hidden:panel.hidden,text:textOf(panel),children:panel.children.length};}
"""
        result = subprocess.run(
            [shutil.which("node"), "-"], input=harness + renderer + exercise,
            text=True, encoding="utf-8", capture_output=True, timeout=10, check=True,
        )
        return json.loads(result.stdout)

    def test_changed_final_title_and_prior_query_are_visible_not_a_verdict(self):
        values = self.run_renderer(r"""
const packet={untrusted_prior_analysis:JSON.stringify({title:'echo logprobs'}),
 sources:[{search_query:'repo:public/project "logprobs"'},
          {search_query:'repo:public/project "logprobs"'}]};
process.stdout.write(JSON.stringify(show(packet,{decision:'lead',title:'token zero prompt'})));
""")
        self.assertFalse(values["hidden"])
        self.assertIn("本轮标题：token zero prompt", values["text"])
        self.assertIn("前一轮标题：echo logprobs", values["text"])
        self.assertEqual(values["text"].count('repo:public/project "logprobs"'), 1)
        self.assertIn("可能只是改写", values["text"])
        self.assertIn("不是完整查重", values["text"])
        self.assertIn("不新增查询或模型调用", values["text"])

    def test_same_title_is_not_novelty_or_query_coverage(self):
        values = self.run_renderer(r"""
process.stdout.write(JSON.stringify(show({untrusted_prior_analysis:'{"title":"same"}',
 sources:[{search_query:'q'}]},{decision:'lead',title:'same'})));
""")
        self.assertIn("文本相同也不证明", values["text"])
        self.assertNotIn("文本不同", values["text"])

    def test_clipped_missing_or_malformed_prior_and_query_metadata_are_unknown(self):
        values = self.run_renderer(r"""
const rows=[];
for(const prior of [undefined,'{"title":','legacy prose',[],{},'null','[]',
 JSON.stringify({title:[]}),'x'.repeat(2501)]) {
 rows.push(show({untrusted_prior_analysis:prior,sources:[null,{},
 {search_query:[]},{search_query:'  '}]},{decision:'lead',title:'new'}));
}
process.stdout.write(JSON.stringify(rows));
""")
        for row in values:
            self.assertIn("不推断假设相同或不同", row["text"])
            self.assertIn("不代表未搜索或没有重复项", row["text"])

    def test_scope_is_text_only_bounded_and_cleared_for_non_candidates(self):
        values = self.run_renderer(r"""
const sources=Array.from({length:70},(_,i)=>({search_query:i<64?'x'.repeat(800):'not-scanned'}));
sources[1]={search_query:'<script>alert(1)</script>'};
sources[2]={search_query:'second'};sources[3]={search_query:'third'};
sources[4]={search_query:'not-displayed'};
const observed=show({sources,untrusted_prior_analysis:JSON.stringify({title:'<b>old</b>'})},
 {decision:'lead',title:'<img src=x>'+ 'z'.repeat(300)});
const hidden=[];
for(const analysis of [null,[],{}, {decision:'no_lead'},{decision:'needs_context'}])
 hidden.push(show({sources},analysis));
for(const packet of [null,[],false,'bad']) hidden.push(show(packet,{decision:'lead'}));
process.stdout.write(JSON.stringify({observed,hidden}));
""")
        observed = values["observed"]["text"]
        self.assertIn("<script>alert(1)</script>", observed)
        self.assertIn("<b>old</b>", observed)
        self.assertIn("<img src=x>", observed)
        self.assertIn(" [truncated]", observed)
        self.assertNotIn("x" * 513, observed)
        self.assertNotIn("z" * 201, observed)
        self.assertNotIn("not-scanned", observed)
        self.assertNotIn("not-displayed", observed)
        for row in values["hidden"]:
            self.assertTrue(row["hidden"])
            self.assertEqual(row["children"], 0)

    def test_source_scan_and_query_count_caps_are_independent(self):
        values = self.run_renderer(r"""
const sources=Array.from({length:64},()=>({search_query:'same'}));
sources.push({search_query:'outside first64'});
process.stdout.write(JSON.stringify(show({sources},{decision:'lead',title:'case'})));
""")
        self.assertEqual(values["text"].count("same"), 1)
        self.assertNotIn("outside first64", values["text"])


if __name__ == "__main__":
    unittest.main()
