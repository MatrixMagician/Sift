<!-- generated-by: gsd-doc-writer -->
# Contributing to Sift

Thanks for considering a contribution. This document covers *process*: what a
change has to satisfy before it can land. The technical how-to lives elsewhere —
see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the development environment
and [docs/TESTING.md](docs/TESTING.md) for the test suite and the `sift eval`
golden-case harness.

## Getting set up

`uv sync` from a checkout is the whole of it — see
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for prerequisites, the local
inference backend, and everything beyond the one-liner.

## Definition of done

A change is done when all three of these are clean. There are no exceptions and
no "I'll fix the types in a follow-up":

```bash
uv run ruff check
uv run pyright
uv run pytest
```

`pyright` runs in strict mode over `src/` and `tests/` — zero errors, not "zero
new errors". The default `pytest` run excludes the `perf`, `live`, and
`packaging` markers; if your change touches those paths, run them explicitly
(e.g. `uv run pytest -m perf`) and say so in the pull request.

Tests come first. The repository is built test-first throughout: a failing test
that pins the new behaviour, then the implementation that makes it pass. A
change that adds behaviour without a test that fails before it is not done.

## Commit messages

Conventional Commits, as practised here:

```
type(scope): subject
```

- **type** — one of `feat`, `fix`, `test`, `docs`, `chore`.
- **scope** — the area the change touches. In this repository the scope is
  usually the phase or plan number the work belongs to (`feat(11-02)`,
  `test(04)`, `docs(11-03)`); for contributions outside that workflow use the
  module or component instead (`fix(adapters)`, `feat(store)`).
- **subject** — lower-case, imperative, no trailing full stop.

Keep commits atomic: one logical change each. A test-first pair lands as two
commits (the failing test, then the implementation), not one squashed blob.

British English in commit subjects, docs, and user-facing strings — the whole
repository uses it, including CLI output and report text.

## Architecture decision records

Changes that settle a design question get an ADR in
[docs/decisions/](docs/decisions/). Write one when your change:

- answers an open question from SPEC.md §10;
- picks one option where a reasonable engineer would have picked another
  (a dependency choice, a storage layout, an exit-code scheme);
- deliberately accepts a limitation or some debt that a later reader would
  otherwise mistake for an oversight.

Routine bug fixes and behaviour that SPEC.md already prescribes do not need one.

To add one: take the next free four-digit number, name the file
`NNNN-kebab-case-title.md`, and follow the existing shape (see
[0009-kb-index-per-case.md](docs/decisions/0009-kb-index-per-case.md) for a
representative example):

```markdown
# ADR NNNN: One-line statement of the decision

**Status:** Accepted
**Date:** YYYY-MM-DD
**Answers:** which SPEC section or open question this closes

## Context
## Decision
## Consequences
```

State the decision in the present tense, and record what you rejected and why —
the rejected option is usually the more useful half for whoever reads it next.

## Invariants a change must not break

These are load-bearing. A contribution that weakens any of them will be asked to
change, however good the rest of it is.

- **Citation validation.** Every hypothesis's `supporting_event_ids` must exist
  in the case store, and `cited ⊆ prompted ⊆ store` must hold. Invalid citations
  trigger one regeneration attempt, then get flagged in the report. Nothing may
  become citable that is not case evidence — knowledge-base text in particular
  is structurally non-citable, and it stays that way.
- **Determinism.** `event_id = sha256(source_file, byte_offset)[:16]`, which
  makes re-ingestion idempotent. Identical case, configuration, model, and seed
  must produce byte-identical JSON, modulo timestamps.
- **Nothing disappears silently.** Unparseable regions become events with
  `severity="unknown"`; adapters emit per-file parse-coverage metrics. A
  multi-line record (a stack trace, an MCM block) is one event, not many.
- **The LLM output contract.** JSON schema enforced by constrained decoding
  where the server supports it, then Pydantic validation, then one repair
  round-trip, then graceful degradation with the raw output persisted. It never
  crashes on model output.
- **Zero network egress at runtime**, except the configured local inference
  endpoint. Non-loopback and non-RFC1918 endpoints are refused unless the user
  passes `--i-know-what-im-doing`.
- **Zero network in tests.** The LLM client is injectable; tests use `respx` or a
  small fake OpenAI-compatible server. A test that reaches the network will not
  be merged.

## Dependencies

Boring technology, deliberately. The current set is stdlib plus httpx, Pydantic,
sqlite-vec, scikit-learn, Typer, and zstandard, with `markdown` and WeasyPrint
behind the optional `pdf` extra.

Adding a dependency requires justification in the pull request: what it does,
why a few lines of stdlib will not, and what it costs (transitive packages,
compiled extensions, system libraries). Some existing entries in
`pyproject.toml` carry an inline comment explaining why they are there — a
useful habit to follow for anything non-obvious.
Vendor SDKs are out: the OpenAI-compatible HTTP surface is hand-rolled on
purpose, because Sift needs precise control of the request shape.

## Pull requests

- Branch from `main`.
- Keep the change focused — one concern per pull request.
- Make sure `ruff check`, `pyright`, and `pytest` are all clean before opening it.
- Describe what changed and why, and link the SPEC section or ADR it relates to.
- If you ran the marker-gated suites (`perf`, `live`, `packaging`), say which.

## Reporting bugs

Open an issue at <https://github.com/MatrixMagician/Sift/issues>. For triage
bugs, the useful things to include are:

- what you ran (the exact `sift` command and any relevant configuration);
- what you expected and what actually happened;
- the adapter and artefact type involved;
- your Python version, operating system, and inference backend.

Please do not attach real customer diagnostics — Sift exists precisely because
that data should not leave your machine. A redacted or synthetic reproduction is
worth far more than a log you had to think twice about pasting.

## Licence

Sift is Apache-2.0. By contributing, you agree that your contributions are
licensed under the same terms. See [LICENSE](LICENSE).
