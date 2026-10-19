"""Exercise the actual briefing renderer without a browser or model calls."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("node"), "Node needed for offline DOM checks")
class BriefingTests(unittest.TestCase):
    def test_provider_recovery_is_not_hidden_by_an_empty_queue(self):
        page = (Path(__file__).resolve().parents[1] / "scripts/kimi_scout_dashboard.html").read_text(encoding="utf-8")
        renderer = page.split("<script>", 1)[1].split("  function renderHistory() {", 1)[0]
        harness = """
const elements = new Map();
function element() { return {children:[],firstElementChild:{},
  append(...v) {this.children.push(...v);},
  replaceChildren(...v) {this.children=v;},addEventListener() {},
  set innerHTML(v) {throw Error('Unsafe HTML rendering');}}; }
global.document = {createElement:element,getElementById(id) {
  if (!elements.has(id)) elements.set(id,element());return elements.get(id);
}};
"""
        exercise = """
  function renderHistory() {}
  const rows = [
    {provider_error_cycles:1,recovery_probe:true,admission_limit:1},
    {provider_error_cycles:1,recovery_probe:false,admission_limit:1},
    {provider_error_cycles:0,recovery_probe:false},
    {provider_error_cycles:1,state:'COOLDOWN',cooldown_until:1100},
    {provider_error_cycles:1,stale:true},
    {provider_error_cycles:1,alive:false},
    {},
    {provider_error_cycles:'1'},
    {provider_error_cycles:1,heartbeat_at:1},
  ].map(value => {
    state={now:1000,summary:{counts:{}},jobs:[],research:{phase:'WAITING_FOR_NEW_EVIDENCE'},
      runtime:{alive:true,state:'RUNNING',concurrency:4,heartbeat_at:999,...value},
      snapshot:{stale:value.stale === true,served_at:1000}};
    renderOverview();
    return {label:$('runtimeLabel').textContent,flow:$('flowStatus').textContent,
      badge:$('runtimeBadge').className,dot:$('runtimeBadge').firstElementChild.className,
      meta:$('runtimeMeta').textContent};
  });
  process.stdout.write(JSON.stringify(rows));
})();
"""
        result = subprocess.run([shutil.which("node"), "-"], input=harness + renderer + exercise,
                                capture_output=True, text=True, encoding="utf-8", timeout=10, check=True)
        rows = json.loads(result.stdout)
        for row in rows[:2]:
            self.assertEqual(row["label"], "服务恢复待确认")
            self.assertIn("上次服务调用失败", row["flow"])
            self.assertIn("准入上限 1", row["meta"])
            self.assertEqual(row["badge"], "badge cooldown")
            self.assertEqual(row["dot"], "dot")
        self.assertEqual(rows[2]["label"], "运行中 · 等待新材料")
        self.assertIn("等待新材料", rows[2]["flow"])
        self.assertEqual(rows[2]["badge"], "badge running")
        self.assertEqual(rows[2]["dot"], "dot live")
        self.assertIn("服务退避中", rows[3]["flow"])
        self.assertIn("快照已过期", rows[4]["label"])
        self.assertIn("保存快照已过期", rows[4]["flow"])
        self.assertEqual(rows[5]["label"], "守护进程未运行")
        self.assertIn("离线", rows[5]["flow"])
        for row in rows[6:8]:
            self.assertEqual(row["label"], "运行中 · 等待新材料")
            self.assertNotIn("服务调用失败", row["flow"])
        self.assertIn("心跳待确认", rows[8]["flow"])
        self.assertNotEqual(rows[8]["label"], "服务恢复待确认")

    def test_refill_details_render_wait_reasons_and_clear_legacy_state(self):
        page = (Path(__file__).resolve().parents[1] / "scripts/kimi_scout_dashboard.html").read_text(encoding="utf-8")
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        renderer = script.split("  function renderDelivery() {", 1)[0]
        harness = """
const elements = new Map();
function element() {
  return {children:[], replaceChildren(...v) {this.children=v;},
    set innerHTML(v) {throw Error('Unsafe HTML rendering');}};
}
global.document = {createElement:element, getElementById(id) {
  if (!elements.has(id)) elements.set(id,element());
  return elements.get(id);
}};
"""
        exercise = """
  state={research:{phase:'REFILLING',refill_health:[
    {repo:'a/<script>x</script>',state:'FETCHING',elapsed_seconds:9},
    {repo:'b/error',state:'ERROR_BACKOFF',retry_in_seconds:36,
      last_outcome:'ERROR',last_duration_seconds:20,error_code:'TimeoutError'},
    {repo:'c/empty',state:'RETRY_WAIT',retry_in_seconds:3,
      last_outcome:'NO_NEW_EVIDENCE',last_duration_seconds:1},
    {repo:'d/ready',state:'ELIGIBLE'}]}};
  renderResearch();
  const current={hidden:$('refillDetails').hidden,
    rows:$('refillHealth').children.map(c=>c.textContent)};
  state.research={phase:'READY'};renderResearch();
  const legacy={hidden:$('refillDetails').hidden,count:$('refillHealth').children.length};
  process.stdout.write(JSON.stringify({current,legacy}));
})();
"""
        result = subprocess.run([shutil.which("node"), "-"], input=harness + renderer + exercise,
                                capture_output=True, text=True, encoding="utf-8", timeout=10, check=True)
        value = json.loads(result.stdout)
        self.assertFalse(value["current"]["hidden"])
        self.assertIn("a/<script>x</script> · 正在取材 9s", value["current"]["rows"][0])
        self.assertIn("请求失败后退避 · 36s 后重查", value["current"]["rows"][1])
        self.assertIn("TimeoutError", value["current"]["rows"][1])
        self.assertIn("本轮未入队新证据", value["current"]["rows"][2])
        self.assertIn("可再次取材", value["current"]["rows"][3])
        self.assertEqual(value["legacy"], {"hidden": True, "count": 0})

    def test_live_stale_missing_activity_and_repo_filter(self):
        page = (
            Path(__file__).resolve().parents[1] / "scripts/kimi_scout_dashboard.html"
        ).read_text(encoding="utf-8")
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        renderer = script.split("  function renderResearch() {", 1)[0]
        harness = """
const elements = new Map();
function element() {
  return {
    children: [], events: {},
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    addEventListener(name, fn) { this.events[name] = fn; },
    scrollIntoView() {},
  };
}
global.document = {
  createElement: element,
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  },
};
"""
        exercise = """
  function renderHistory() {}
  state = {
    now:1000, runtime:{alive:true,state:'RUNNING',heartbeat_at:999,concurrency:16},
    summary:{counts:{RUNNING:8,PENDING:0}}, research:{phase:'REFILLING'},
    activity:{completed:300,completed_per_minute:20,review_leaves:7,
      reproduction_leaves:3,failed:2,observed_seconds:900,
      average_elapsed_seconds:18,last_completion:995,
      repos:[{repo:'org/<script>not-html</script>',total:10,running:1,
        pending:0,completed:9,failed:2,review_leaves:2,reproduction_leaves:1,
        reported_tokens:1000}]},
  };
  renderBriefing();
  const live = {
    completed: $('recentCompleted').textContent,
    leaves: $('leafReviews').textContent,
    plans: $('plannedReviews').textContent,
    capacity: $('capacityValue').textContent,
    meter: $('capacityMeter').value,
    flow: $('flowStatus').textContent,
    cards: $('repoCards').children.length,
  };
  $('repoCards').children[0].events.click();
  live.search = $('search').value;
  state.runtime.heartbeat_at = 1;
  renderBriefing();
  const stale = {meter:$('capacityMeter').value,flow:$('flowStatus').textContent};
  state.runtime.alive = false;
  delete state.activity;
  renderBriefing();
  const missing = {
    leaves:$('leafReviews').textContent,completed:$('recentCompleted').textContent,
    flow:$('flowStatus').textContent,
  };
  process.stdout.write(JSON.stringify({live,stale,missing}));
})();
"""
        result = subprocess.run(
            [shutil.which("node"), "-"],
            input=harness + renderer + exercise,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=True,
        )
        values = json.loads(result.stdout)
        self.assertEqual(values["live"]["completed"], "300")
        self.assertEqual(values["live"]["leaves"], "7")
        self.assertEqual(values["live"]["plans"], "3")
        self.assertEqual(values["live"]["capacity"], "50%")
        self.assertEqual(values["live"]["meter"], 8)
        self.assertEqual(values["live"]["cards"], 1)
        self.assertEqual(values["live"]["search"], "org/<script>not-html</script>")
        self.assertIn("空槽不代表模型限流", values["live"]["flow"])
        self.assertEqual(values["stale"]["meter"], 0)
        self.assertIn("心跳待确认", values["stale"]["flow"])
        self.assertEqual(values["missing"]["leaves"], "—")
        self.assertEqual(values["missing"]["completed"], "—")
        self.assertIn("离线", values["missing"]["flow"])


if __name__ == "__main__":
    unittest.main()
