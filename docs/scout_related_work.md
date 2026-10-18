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

The same already-fetched page retains related **issues** when there is room
after PRs. If a valid same-report comment is present, one of the three slots is
reserved for the latest observed comment; the other two prefer PRs over issues.
Without a valid comment, three PRs can still take all three slots. An earlier
issue cannot displace a later PR. Each excerpt is at most 1,800 characters.
`is_pr` and the separate
observed issue/PR state fields keep report kinds distinct. A related roadmap or
closed issue is neither a PR nor maintainer approval. Original `focus_issue` and
candidate-chain ownership do not move to the related report.

The cache format is versioned because older compact caches discarded non-PR
events. A legacy record is refreshed once through the same bounded endpoint;
subsequent initial/follow-up reads share the new cache. No linked reports,
report-body links, other repositories or later pages are followed. Literal
comments embedded in this very timeline response use the reserved slot and then
any remaining slots, latest observed first. This intentionally omits a third
related-work body when necessary, rather than erasing every observed objection
or contributor offer. It is a text-budget tradeoff, not an authority ranking or
a claim that the selected commenter is a maintainer. They share
the same three-source and 1,800-character limits. Both ends of a long comment
survive explicit clipping, so a final offer to submit is not silently dropped.
The compact cache preserves those excerpts and their partial flags; older v2/v3
records refresh once. No separate comment GET is added by this lookup. A full
issue read may already fetch its existing last-comment sample; matching URLs
are not appended twice.
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

Keep raw search counts separate from accepted references. In the October 15
Pluggy #794 follow-up, `total_count=1` and `returned_items=1` survived into the
packet even though the explicit-reference filter accepted no PR. The model
incorrectly treated this as one PR referencing the report. The visible search
result was an unrelated dependency update. The lookup now also carries
`verified_reference_count` and explains what each count means; zero accepted
references still does not establish novelty. A focused regression preserves
the raw numeric hit while requiring zero accepted references. This removes an
ambiguous evidence field, not proof of better model accuracy or PR conversion.

An October 17 owner review of [TileLang #2973](https://github.com/tile-ai/tilelang/issues/2973)
found that a contributor had already volunteered to implement the fix in an
embedded comment, while the earlier compact lookup retained no references.
The owner contributed [scoped helper/IR validation](https://github.com/tile-ai/tilelang/issues/2973#issuecomment-6227272455)
and asked for coordination instead of opening a competing PR or starting a full
compiler build. This known case motivates retaining already-fetched comments;
offline tests establish delivery, budget, identity and cache behavior only.
Untrusted comment text is neither an instruction nor automatic ownership,
acceptance, fix coverage or novelty evidence. First-page sampling can miss a
later decision, and the latest observed comment may not address API intent.
Inspect the full
discussion before expensive work when that missing evidence matters. Do not
count this retrospective case as a prospective selector win or PR conversion.
