# ADR 0001: Typer over argparse for the CLI

**Status:** Accepted
**Date:** 2026-07-16 (research date; recorded during Phase 1 per D-02)
**Answers:** SPEC.md §10 open question 1 — "Typer vs argparse for CLI (weigh dependency cost vs ergonomics)"

## Context

Sift's CLI surface is non-trivial: seven flat subcommands (`new`, `ingest`,
`analyze`, `report`, `show`, `eval`, `doctor`), repeated `--adapter glob=name`
options, and per-command flags such as `--data-dir`. SPEC.md §9 sanctions both
Typer and argparse as boring technology; the question is dependency cost
versus ergonomics.

Research (STACK.md, 2026-07-16) found Typer 0.27.0 released 2026-07-15 —
an actively maintained project. The standard `typer` package pulls `click`,
`typing-extensions`, `rich` and `shellingham` (roughly four packages);
`typer-slim` exists if that budget ever needs trimming.

## Decision

Use Typer 0.27.x. Typed parameters are checked by pyright in strict mode,
subcommands are plain decorated functions, and help text plus shell
completion come for free. `typer.testing.CliRunner` gives in-process
end-to-end tests with zero subprocess overhead, which the acceptance suite
relies on.

## Consequences

- One dependency tree (~4 packages) beyond stdlib; acceptable against the
  ergonomic gain for a seven-command surface.
- CLI parameter types are part of the pyright gate — a mistyped option is a
  type error, not a runtime surprise.
- If the dependency budget ever becomes absolute, `typer-slim` (drops
  rich/shellingham) is the first fallback; argparse remains SPEC-sanctioned
  as the last resort.
