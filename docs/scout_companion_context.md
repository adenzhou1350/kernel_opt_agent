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

## Declarative implementations are opt-in evidence text

Some repositories store implementations inside YAML, not Python files. An
operator may opt in a small directory using a repository's
`declarative_source_prefixes`, for example:

```json
{
  "source_prefixes": ["model/evaluators/"],
  "declarative_source_prefixes": ["model/evaluators/"]
}
```

Only `.yaml` and `.yml` within those explicit directories become source evidence;
the directories must also lie within the existing source prefixes. Other
repositories, excluded test/vendor/generated paths, byte/line/read budgets and
dedup keys retain their existing behavior. The same opt-in applies to issue
context and bounded adjacent-window follow-ups. A changed selection reopens a
completed empty sweep without resubmitting seen evidence.

Scout reads the files as inert UTF-8 text. It does not parse YAML tags, compile
embedded functions, execute examples, or acquire test qualification. A discovered
lead still needs an independent test through the target project's actual caller.
The motivating FutureAGI directory contained 88 YAML implementations and zero
default-eligible source files at `ea12cc3f4456fc568d9694a215c661b15be1cea2`;
restoring coverage does not establish new defects or improved PR yield.

```text
python -B -m unittest tests.test_scout_declarative_source
```

## Explicit implementation scopes

Directory source scopes skip Python `__init__.py` files by default. If a package
implements behavior in one (rather than just re-exporting names), explicitly
name its complete repository-relative path in `source_prefixes`, for example
`pyparsing/diagram/__init__.py`. This includes that file, not every initializer
under the directory; generated/vendor exclusions still apply. Selection only
supplies pinned source evidence and does not prove a defect or native execution.
