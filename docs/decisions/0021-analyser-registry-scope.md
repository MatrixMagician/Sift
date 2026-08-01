# ADR 0021: the analyser registry describes the prompt path only

**Status:** Accepted
**Date:** 2026-08-01
**Answers:** SPEC.md §5.5 (hypothesis generation) / §7 (repository layout) —
should `pipeline/analysers.py` also describe the `mcm`/`perfmon`/`eustack`
bundle commands, so that one registry entry drives both the triage prompt's
fact block and the operator-facing bundle?
**Cross-refs:** ADR 0019 (the command seam) — the bundle commands live behind
it and are unaffected either way.

## Context

Each of the three domain analysers appears twice.

**The prompt path** is registered: `ANALYSERS` (`pipeline/analysers.py:155`)
gives each domain a name, its triage-template marker and slot, the event
`sources` it consumes, and a `build` function returning a fact block.
`hypothesise` iterates the tuple and never names a domain.

**The bundle path** is not. `commands/mcm.py`, `commands/perfmon.py` and
`commands/eustack.py` each derive a directory, query events scoped to a source
list, call the analyser, dispatch on `md`/`json`, call `write_bundle`, and echo
a summary plus the top diagnostic flag.

The source list is therefore written twice per domain —
`analysers.py:160` and `commands/mcm.py:45` both say `dsserrors` — and both
feed the same analyser function, so they cannot legitimately differ.

An architecture review proposed widening the `Analyser` entry to carry the
bundle surface (directory, report and CSV names, renderers, summary callback)
and collapsing the three bodies into one `run_bundle`. This ADR declines that,
on measurement rather than on taste.

## Decision

**The registry keeps describing the prompt path only.** Three findings, each
measured on 2026-08-01 rather than argued:

- **The duplicated `sources` is already enforced, in both directions.** Changing
  `commands/mcm.py`'s scope to `journald` turns `test_mcm_writes_bundle` red;
  dropping `dsserrors` from `commands/perfmon.py` — the source its trends are
  anchored on — turns `test_non_overlap_end_to_end` red. The premise that
  "nothing keeps the copies in step" was simply false.

- **`ANALYSERS` has exactly one consumer**, `hypothesise.py`. Putting report and
  CSV renderers in the registry drags `render/mcm_report.py` and its siblings
  into the prompt path's import graph, and puts per-domain *presentation*
  wording in the module that currently holds only prompt concerns. That is a
  worse coupling than the duplication it removes.

- **What is actually duplicated is small and mostly not templatable.**
  `commands/_bundle.py` already shares the write-and-unlink and the top-flag
  tail. What remains per command is roughly twenty lines: a directory
  derivation, a scoped read, an `md`/`json` dispatch and a `write_bundle` call.
  The analyse call differs materially (perfmon composes `analyse_perfmon` over
  `analyse_mcm`; eu-stack loads rules first), and the summary wording and flag
  loop differ per domain — episodes, spans, dumps-and-signatures. Those would
  become callbacks in the registry rather than disappear, so the saving is
  around thirty lines traded for a wider dataclass and an indirection.

**An analyser does not imply a bundle command.** The three that have one are
operator-facing forensics products; the registry does not require it and a
fourth analyser could contribute a fact block alone. `analysers.py`'s docstring
scoped its "one registry entry" cost to `hypothesise.py`, which is accurate, but
reads as a total-cost claim — it was read that way during the review, and now
says so explicitly.

**The invariant that spans both paths is pinned directly.**
`tests/test_analysers.py` asserts each bundle command scopes to exactly the
`sources` its registry entry declares, reading the literal out of the AST rather
than matching source text, so a reformat cannot fail it for a reason unrelated
to the invariant. A second test asserts the file's own command map has not
fallen behind `commands/`.

That test exists because of *how* the first finding holds. The bundle-content
tests enforce agreement **incidentally** — they assert on figures, and a
mis-scope happens to change the figures. Rewrite one of those fixtures and the
guarantee leaves with it, silently, and this ADR would go on citing protection
that no longer existed. A decision recorded as "already enforced" has to own the
enforcement, or it rots into a claim nobody rechecks.

## Consequences

- The three bundle command bodies stay as they are, with their literal source
  lists — self-documenting at the point of use, and now pinned against the
  registry by name.
- Adding a fourth analyser with a bundle command still costs a `commands/`
  module and a Typer command. That is accepted, not overlooked; revisit if a
  fifth arrives and the shape has genuinely converged.
- A future architecture review proposing this refactor should read the three
  findings first. Two of them are measurements that could change: if
  `_bundle.py` grows, or if the summaries converge on one shape, the arithmetic
  changes and so might the answer.
- Mutation-checked: a drift in the command turns the new test red, a drift in
  the registry entry turns the same test red, and a pure reformat of the command
  does not.
