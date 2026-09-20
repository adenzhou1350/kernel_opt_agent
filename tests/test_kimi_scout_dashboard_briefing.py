"""Exercise the actual briefing renderer without a browser or model calls."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("node"), "Node needed for offline DOM checks")
class BriefingTests(unittest.TestCase):
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
