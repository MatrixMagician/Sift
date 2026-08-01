# ADR 0019: Case commands live behind a typer-free `run_x` seam in `sift/commands/`

**Status:** Accepted (implemented — pass 1 moved the bodies, pass 2 migrated
the show/analyze/parsing tests, pass 3 the four suites pass 2 left behind)
**Date:** 2026-07-31
**Answers:** SPEC.md §5.8 (CLI) / §7 (repository layout) — where does a case
command's implementation live, given that Sift now has three callers for it
(the Typer CLI, the Textual TUI, and the eval harness)?
**Cross-refs:** ADR 0005 (`analyze` exit codes), ADR 0007 (`report` exit codes),
ADR 0010 (`eval` exit codes) — this ADR changes where those codes are
*produced*, never what they *mean*.

## Context

Twelve of `sift`'s fourteen Typer commands keep their implementation inline in
the command body — roughly 637 lines, with `doctor` at 133 and `show` at 111.
Only `analyze` and `report` have an extracted body (`run_analyze`,
`run_report`), and both already take injected output sinks and return an exit
code rather than raising `typer.Exit`.

Three consequences follow from having no seam for the other twelve:

- **The CLI is the only test surface.** 3845 lines of `CliRunner`-driven tests
  cover the command surface; no test calls `run_analyze` or `run_report`
  directly despite both being designed for it. Reaching `run_analyze`'s
  branches needs ~90 lines of `MockTransport` scaffolding that a direct call
  would not require. `_resolve_generation_ctx` is the sole helper with direct
  tests, and its docstring names exactly this friction: *"The warning is
  RETURNED rather than printed so the whole decision is unit-testable without a
  `CliRunner`."*
- **The TUI re-implements or skips what it cannot reach.** It calls three
  command bodies and re-implements four surfaces in `tui/screens/`. It opens
  `CaseStore` raw at three sites, bypassing `_case_store`'s validation, so a
  corrupt `case.db` surfaces as an unsanitised exception string. It passes
  three of `run_analyze`'s twelve parameters, leaving nine operator knobs
  unreachable. It re-encodes the CLI-04 success set as its own `(0, 3)` tuple.
- **`sift.cli` and `sift.tui` form an import cycle.** `cli` imports the TUI
  package; `tui/app.py` works around this with a deferred `from sift import
  cli` at three call sites.

Exit codes exist as 46 integer literals with no constant. Their meanings are
consistent across commands (0 success, 1 error, 2 usage, 3 degraded-but-
persisted); the per-command contracts differ only by using a subset — ADR 0007
records that `report`'s contract is "deliberately narrower than ADR 0005's (no
code 3)".

## Decision

Case-command implementations move behind a seam in a new `src/sift/commands/`
package, which imports neither `sift.cli` nor `sift.tui`.

**Interface.** Every command body becomes:

```python
def run_x(
    store: CaseStore,
    config: SiftConfig,
    *,
    <typed arguments>,
    echo: Callable[[str], None] = print,
    echo_err: Callable[[str], None] = _echo_stderr,
) -> ExitCode: ...
```

`announce` is carried by `run_analyze` alone, so a command's ability to emit
progress is visible in its type. The seam is **typer-free**, matching the
discipline the nine `pipeline/` modules already document.

**Scope.** The seven commands that operate on an open case store: `show`,
`analyze`, `report`, `validate`, `mcm`, `perfmon`, `eustack`. `show` splits
into one function per target (`hypotheses`, `clusters`, `templates`, `events`),
mirroring the TUI's existing screen-per-target structure. Out of scope:
`doctor`, `eval`, `new`, `list`, `delete` (different interface shapes),
`ingest` (already seamed in `pipeline/ingest.py`) and the `tui` launcher.

**Failures return, never raise.** A failing command echoes through its injected
sink and returns a code; nothing raises across the seam. `cli.py` translates
the code to `typer.Exit`, the TUI reads it directly.

**Exit codes become a vocabulary.** `ExitCode(IntEnum)` in `commands/_exit.py`
with the four ADR meanings. `run_x` returns `ExitCode`, so pyright rejects a
command inventing a fifth code.

`is_failure(code)` serves the adapters that keep running and must decide what
to show — in practice the TUI, replacing its hand-rolled `(0, 3)` tuple. The
CLI deliberately does not use it: a process exit status must carry every
non-zero code to the shell, `DEGRADED` included, so `cli.py` branches on
`if code:`. The two rules differ because the questions differ — "is there
something to show?" versus "what status did this run finish with?" — and an
earlier draft of this ADR wrongly called it one shared rule.

**Flag parsing is pure and public.** `parse_filters` and `parse_moment` move to
`commands/parse.py`, returning typed values or raising `ValueError`. Adapters
parse *before* opening the store, preserving the fail-fast ordering
`cli.py:706` exists to guarantee, and `run_x` receives typed values.

The clause is scoped to *flag* parsing on purpose. `commands/parse.py` owns the
shapes that exist only because a CLI encodes arguments as text — `key=value`,
an ISO string in `--since`. It does **not** own `verdicts.parse_target`, which
turns `hypothesis:0` into a `TargetSpec`: that is a domain identifier, which is
why `record_validation` accepts either the raw string or an already-parsed
spec, why its failure has its own `TargetSpecError`, and why it stays in
`verdicts.py`. Moving it would invert the dependency — `commands` imports
`verdicts`, never the reverse. See CONTEXT.md, *Flag parsing / domain-identifier
parsing*.

**Opening a case moves to the store.** `store.py` already owns
`validate_case_name` and `case_db_path`; it gains `open_case` raising
`CaseNotFound` / `CaseUnreadable` (pre-sanitised). Each adapter maps those to
its own presentation. Opening happens before the seam, not across it, so this
does not contradict the return-code rule.

**Client bring-up moves to `llm/`.** `make_http_client` and `build_client` move
to `llm/bringup.py` — the module that, per CLAUDE.md, is the only one that
talks HTTP, and that already owns the `Endpoint` dataclasses. This gives all
three callers one canonical bring-up.

**Sequencing is two passes.** Pass 1 moves the bodies with the test suite
untouched; a green suite is the proof behaviour was preserved. Pass 2 migrates
logic tests to direct calls under the rule below.

**Where a case-command test goes.** Default to calling `run_x` directly. Reach
for `CliRunner` only where the CLI can be *independently* wrong — where the
failure would live in the translation layer (Typer parsing, `typer.Exit`,
Click's output path) rather than in the body it delegates to. Examples: flag
wiring, exit-code propagation, `--help`, non-TTY stdout, and the
terminal-escape checks that prove a sanitised line survives to a real terminal.
Sanitisation is deliberately tested on both sides: the *stripping* is the
body's, the *survival to a terminal* is the CLI's.

**Migration is earned, not owed.** A test already on `CliRunner` moves only
when the move buys reachability — a branch that is awkward or expensive to
reach through the CLI. Purity is not a reason.

An earlier draft of this ADR gave a five-item list instead of a rule, and the
list did not survive contact: sanitisation happens *inside* `run_show_*` and so
is not a CLI property at all, while the `--kb` tests sit outside all five
categories without being misplaced. A rule with examples states what the list
was reaching for.

"Untouched" means no assertion changes. Pass 1 did edit eleven test lines,
all forced by the seam moving rather than by behaviour changing: ten
`monkeypatch.setattr` string paths, and one import. New code that is not moved
code — `ExitCode`, `is_failure`, `open_case` — carries its own direct tests in
`tests/test_commands_seam.py`, since the moved-bodies argument does not cover
it.

Pass 2 migrated the `show`, `analyze` and parsing suites, which is where the
`CliRunner` tax was actually being paid:

- `tests/test_commands_parse.py` — `parse_filters` / `parse_moment` / `to_utc`.
  Every filter-key allowlist, severity-vocabulary and duplicate-key assertion
  used to cost a case directory and an `ingest` run to make.
- `tests/test_commands_show.py` — the four `run_show_*` bodies against a
  directly seeded store.
- `tests/test_commands_analyze.py` — rewritten onto `run_analyze` with list sinks; the
  `resolve_generation_ctx` unit tests moved here from `tests/test_cli.py` to
  sit beside the branch they resolve.

What stayed in `tests/test_cli.py` is the CLI's own surface: the
new/ingest/show slice, target dispatch, the exit-2 filter and `--since`
boundaries, exit-1 case opening, `--help`, non-TTY stdout, and the
terminal-escape checks that prove hostile bytes never reach a real terminal.
The analyze block there now fakes `run_analyze` rather than running the
pipeline, which turns the twelve-flag mapping into one assertion — nine of
those parameters previously had no CLI-level test, because reaching them meant
driving the whole pipeline — and pins the code-3 propagation that the
`is_failure` asymmetry above exists to protect.

Faking the body costs one thing, and it is paid for explicitly.
`test_analyze_end_to_end_through_the_cli` is the single test that still drives
the assembled CLI path for real — `--since` parsing, config resolution,
`open_case`, the call, `store.close()`, the `typer.Exit` translation — because
every other analyze test in that file would stay green with any joint between
those broken. It asserts the WAL sidecars are gone afterwards, so an unclosed
store fails it. Other suites do run analyze through the CLI, but incidentally,
as setup for something else; the follow-up below migrates them, which would
take the last real CLI→pipeline path with it were this test not there.

Line coverage of `sift/commands/` and `sift/cli.py` was measured before and
after and is unchanged bar one line gained — but that measurement is a floor,
not a proof. `sanitise()` and the render-time truncation slice sit on every
rendered line, so an assertion about them can be dropped without moving the
number at all. Three were, and the review caught them: the hypotheses-title
sanitise, the message flatten-and-truncate, and the empty-clusters view. Each
has an explicit test now. The lesson is the general one about a move like this:
line coverage cannot tell you an assertion was relocated rather than deleted,
so the removed tests have to be read against the new ones by hand.

The remaining `CliRunner` suites split three ways, and an earlier draft of this
paragraph wrongly gave one blanket reason for all five:

- **`test_cli_{mcm,perfmon,eustack}.py` stay, under *migration is earned*.**
  What they assert is a bundle written to `<case>/<command>/` by
  `write_bundle`, plus an exit code and a `--help` line. Those bodies take no
  injected client and already run against a real seeded store, so a direct call
  reaches nothing the CLI does not. Moving them would be churn.
- **`test_cli_{validate,report}.py` are mixed files.** `run_validate` writes a
  DB row and `run_report` writes to an arbitrary `--out` path, so the bundle
  argument never applied to either. In `test_cli_validate.py` the exit-2
  branches are genuinely the CLI's (the "exactly one verdict flag" check lives
  at `cli.py:618`, and `parse_target` runs before the store opens) while the
  exit-1 branches — unknown target, locked database — are `run_validate`'s. In
  `test_cli_report.py` the `--format` enum is Typer's and the unwritable-`--out`
  exit 1 is `run_report`'s. Their seam-side halves moved in pass 3.
- **`test_kb_analyze.py` (4 tests) and `test_mcm_analyze.py` (2) were
  mis-shelved.** They drove `run_analyze` through `CliRunner` — a degraded
  citation, an exit code on an empty `--kb` directory, `analyser_settings`
  threading. None of that is about Typer. Pass 2 did not touch them and this
  ADR was, until pass 3, silent about them, which would have let a reader
  conclude the analyze suite was fully migrated.

Pass 3 (issue #3) finished those three bullets' second and third items. It was
tracked as an issue rather than left as a note here, because a deferral
recorded only in a decision document is a to-do nobody works; its precondition
was the end-to-end smoke test above.

- `test_kb_analyze.py` and `test_mcm_analyze.py` call `run_analyze` directly.
  Both files keep their names: `test_commands_*` means "calls the seam", but
  the converse was never claimed — these are KB and MCM slices that happen to
  need the whole pipeline, and their fixtures (the golden no-KB prompt hash,
  the Hartford deny slice) belong with the assertions that read them.
- `test_cli_validate.py` split, with the case builder both halves need
  extracted to `tests/_validate_fixtures.py` so the split did not fork it.
  `tests/test_commands_validate.py` takes the unknown-target, locked-database
  and append-only-history branches; the exit-2 flag checks, the malformed-spec
  ordering and the absent-case exit 1 stay on `CliRunner`.

  Two `validate` tests fall outside that split and stay on `CliRunner` under
  *migration is earned*: each verdict flag's mapping to its stored state is
  flag wiring by definition, and the `--confirm --note` success path is the
  only test proving `run_validate`'s single `echo` line survives Click's output
  path to real stdout — the report/analyze equivalent of
  `test_analyze_end_to_end_through_the_cli`.
- `tests/test_commands_report.py` takes the unwritable-`--out` branch; the
  `--format` enum stays.

Two things the issue's own plan got wrong, both worth the next reader's
attention:

- **The `--kb` failure path was not the only uncovered branch in
  `commands/analyze.py`.** The generation-failure path (`outcome.failed` →
  exit 1, the branch that distinguishes "produced nothing" from the exit 3 of
  "produced something unvalidatable") was uncovered too. Both are now tested
  at the seam and the module is at 100% line and branch coverage.
- **Migrating a test off `CliRunner` can delete CLI coverage the test was
  providing incidentally** — the mirror image of pass 2's lesson. Moving
  validate's exit-1 branches to the seam left nothing exercising
  `cli.py`'s `if code: raise typer.Exit(code)` for that command, because the
  only remaining CLI tests all ended in 0 or 2. The replacement
  (`test_validate_body_failure_code_reaches_the_shell`) fakes `run_validate`
  and asserts the status alone, which is the translation-layer half the seam
  test cannot reach. Check the *caller's* coverage after a migration, not just
  the callee's.

Every test that moved was mutation-checked rather than trusted: the behaviour
each one names was broken in `src/` and the test watched to go red.

## Consequences

- Two real adapters sit at the seam — Typer and Textual — with the eval
  harness as a third caller. The seam is justified by variation that exists,
  not variation that might.
- The `cli` ↔ `tui` import cycle is broken structurally; `tui/app.py`'s three
  deferred imports become ordinary top-level ones.
- The TUI routes through `open_case`, so a corrupt or missing case produces the
  same sanitised message as the CLI. The nine `analyze` knobs become reachable
  in code; exposing them in the UI is separate work with its own design
  decisions.
- Exit-code knowledge stops being 46 literals plus a copy in `tui/app.py`.
- `eval/runner.py` can call `run_analyze` rather than re-implementing the
  orchestration — the drift recorded separately (it omits `analyser_settings`,
  so `hypothesise` silently falls back to default thresholds) becomes fixable
  by deletion rather than by patch.
- Eight test files monkeypatch `"sift.cli._make_http_client"` by string path
  and must be repointed at `"sift.llm.bringup.make_http_client"`.
- Two seams must survive the move intact: `analysers.py:144` resolves
  `eustack.load_rules` off the module attribute specifically to keep the eval
  monkeypatch working — `run_eustack` must not convert it to a from-import —
  and the parse-before-open ordering above.
- `cli.py` keeps `doctor`'s 133 inline lines and `eval`'s 46. The codebase
  carries two conventions until those are addressed; this ADR does not claim
  otherwise.
