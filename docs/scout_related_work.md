# Related-work retrieval is not an activity feed

Scout's bounded duplicate search uses GitHub's default best-match ordering,
not `sort=updated`. Frequent comments and CI activity can otherwise crowd an
older exact fix out of the five supplied excerpts. Issue intake remains sorted
by recent activity: discovery and duplicate checking answer different questions.

The budget is unchanged: at most two queries and five excerpts, with the existing
fallback and repository-scope checks. Search remains partial, and an apparent
match is not proof of duplication or a merged fix. Compare the actual hunk and
current source before stopping or publishing; retain author ownership.

An October 9 owner audit reproduced SGLang's Pythonic quoted-bracket streaming
failure, then found open PR [#38869](https://github.com/sgl-project/sglang/pull/38869)
already covered it. The earlier activity-sorted packet omitted that PR. No new
community PR was opened. This motivates the retrieval change, not a measured
general improvement in recall, token cost, or PR conversion. Native reproduction
does not establish novelty, and closed/unmerged work must also be checked.

Initial issue triage now also uses the existing bounded issue-timeline lookup,
instead of waiting for a model lead and follow-up. It adds at most one cached
GET (first 50 events, three same-repository excerpts total, 15-minute TTL) without
re-fetching the report/comments. Follow-ups reuse that cache. The packet keeps
the lookup scope/status, including unavailable or empty partial observations;
no issue is automatically rejected because a PR was cross-referenced.

The same already-fetched page now retains related **issues** when there is room
after PRs. Three PRs still take all three slots; an earlier issue cannot displace
a later PR. Each excerpt is at most 1,800 characters. `is_pr` and the separate
observed issue/PR state fields keep report kinds distinct. A related roadmap or
closed issue is neither a PR nor maintainer approval. Original `focus_issue` and
candidate-chain ownership do not move to the related report.

The cache format is versioned because older compact caches discarded non-PR
events. A legacy record is refreshed once through the same bounded endpoint;
subsequent initial/follow-up reads share the new cache. No linked reports,
comments, report-body links, other repositories or later pages are followed.
For example, [JuiceFS #7681](https://github.com/juicedata/juicefs/issues/7681)
links retry roadmap [#7455](https://github.com/juicedata/juicefs/issues/7455),
which is related to the earlier [#7453](https://github.com/juicedata/juicefs/issues/7453).
This change does **not** automatically retrieve that entire chain or its
maintainer comments. Those remain explicit next-evidence questions before
proposing an independent design. Offline budget, kind, cache and queue tests
prove the retrieval mechanics, not improved decision accuracy or discovery yield.

An October 11 live lookup for urllib3 issue
[#3723](https://github.com/urllib3/urllib3/issues/3723) recovered existing PR
[#4953](https://github.com/urllib3/urllib3/pull/4953) from five timeline events.
Offline queue tests verify that linked work reaches the first model packet,
current-source evidence remains, and seen issues do not repeat the lookup.
This closes a delivery gap, not a measured token saving or recall/conversion
improvement. It spends an extra lookup at first triage; utility still needs a
prospective total-cost comparison. Later pages and cross-repository work remain
outside this bounded sample, and cached PR state is not live merge/CI evidence.
