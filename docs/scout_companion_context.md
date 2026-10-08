# Applicable test context before more model calls

A source packet paired `src/cron/store/read-only.ts` with
`src/channels/plugins/read-only.test.ts`: the basename matched, but the test
belonged to a sibling component. Including a test file does not establish a
runnable regression for the source.

The path-only `kimi_scout_research.companion_source_paths` function already ranks
exact test names, shared directories, and mirrored `src`/`test` structure. For
comparable paths under the same `src` root, it now excludes different first-level
components. A source audit still reads at most one companion test, or none; it
does not add fetches, models, code execution, dependencies, or dispatch roles.
The optional experimental-feature policy lookup remains unchanged.

These are lexical hints, **not** a semantic relevance classifier. Separate test
trees, distinct workspace roots, integration tests within a component, and
root-level files retain the existing fallback. Explicit caller/follow-up searches
are unaffected. A useful cross-component test might therefore be omitted from
automatic pairing; request it explicitly when source/import/caller evidence
supports the link. Remaining matches must still be inspected before counting
native coverage or running them.

```text
python -B -m unittest tests.test_scout_companion_components tests.test_kimi_scout_research
```

The regressions cover sibling false matches, genuine local tests, input-order
independence, mirrored layouts, generic tests, partial-name ranking, and actual
producer read counts/packet construction with fake source responses. The current
unmodified baseline fails two of the ten focused checks: false companion
selection and the resulting extra producer read. These establish selection
behavior, not PR yield or improved model accuracy. No community-code, GPU, or
whole-workload performance claim is made.
