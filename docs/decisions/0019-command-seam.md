# ADR 0019: Case commands live behind a typer-free `run_x` seam in `sift/commands/`

**Status:** Accepted (implementation pending)
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
with the four ADR meanings, plus `is_failure(code)` shared by both adapters.
`run_x` returns `ExitCode`, so pyright rejects a command inventing a fifth
code.

**Parsing is pure and public.** `parse_filters` and `parse_moment` move to
`commands/parse.py`, returning typed values or raising `ValueError`. Adapters
parse *before* opening the store, preserving the fail-fast ordering
`cli.py:706` exists to guarantee, and `run_x` receives typed values.

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
logic tests to direct calls, leaving `CliRunner` for what is genuinely CLI:
flag wiring, exit-code propagation, help text, non-TTY stdout, sanitisation.

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
