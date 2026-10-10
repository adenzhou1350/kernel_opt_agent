# Observe complete check evidence

GitHub's check-run endpoint defaults to 30 results per page. A passing first
page can hide a pending or failed check. Use a frozen PR head, explicit bounded
pagination and advertised-count reconciliation before describing its checks.

```python
from scripts.scout_github_checks import observe_pull_request

# json_get is your existing authenticated, read-only GitHub GET transport.
# It receives API paths without a leading slash; never print its credentials.
observation = observe_pull_request(json_get, "owner/repository", 123)
print(observation["state"], observation["fetched_count"])
```

The helper is standard-library-only and does not manage authentication, retry,
schedule, start jobs or mutate PRs. Missing pages, a page cap, changed counts,
duplicate IDs, wrong check heads or a moved PR head are incomplete evidence.
Malformed JSON shapes and transport errors propagate; they are not passes.
Empty checks, skipped/neutral checks and unknown outcomes are not all-success.

Even `ALL_OBSERVED_SUCCESS` only describes the returned **check runs**. It does
not inspect legacy commit statuses, required-check policies, reviews, merge
conflicts or workflows awaiting maintainer permission. It never authorizes
Ready or merge. Live pages are not an atomic historical snapshot; repeat a
fresh observation before acting, rather than treating a saved result as current.

Reference: [GitHub check runs API](https://docs.github.com/en/rest/checks/runs#list-check-runs-for-a-git-reference).
Tests: `python -B -m unittest tests.test_scout_github_checks`.
