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
