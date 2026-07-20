---
phase: 13-episode-correlation-hazard-flags-sift-perfmon-report-csv
fixed_at: 2026-07-20T00:00:00Z
review_path: .planning/phases/13-episode-correlation-hazard-flags-sift-perfmon-report-csv/13-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 7
skipped: 1
status: partial
---

# Phase 13: Code Review Fix Report

**Fixed at:** 2026-07-20
**Source review:** .planning/phases/13-episode-correlation-hazard-flags-sift-perfmon-report-csv/13-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope (Critical + Warning): 8
- Fixed: 7
- Skipped: 1

Each fix landed as a strict TDD pair (a RED test commit proving the current code
fails, then the GREEN fix commit). The full gate — `uv run ruff check`,
`uv run pyright`, `uv run pytest` — is clean after every fix and green overall
(636 passed, 0 ruff errors, 0 pyright errors). All work was done in an isolated
git worktree on branch `gsd-reviewfix/13-*` and fast-forwarded onto the phase
branch.

## Fixed Issues

### CR-01: 3+ identical counter paths collide again after qualification

**Files modified:** `src/sift/adapters/dssperfmon.py`, `tests/test_dssperfmon.py`
**Commits:** `2717b76` (RED), `ebf9eff` (GREEN)
**Applied fix:** Rewrote `_qualify_counter_names` so collisions are no longer
resolved positionally against a list being mutated. It now computes the
still-ambiguous key set once, promotes every member of an ambiguous group to its
full path, then indexes exact-duplicate header columns with a disclosed `#n`
suffix so `dict(zip(...))` drops nothing. Reproduced the bug empirically first
(`[p, p, p]` → 2 keys of 3); the regression test asserts three distinct keys and
a disclosed note. Also resolves IN-01/IN-04's inconsistent-key-format root cause.

### CR-02: trend CSV bypasses `sanitise`

**Files modified:** `src/sift/render/perfmon_report.py`, `tests/test_perfmon_report.py`
**Commits:** `74f89c0` (RED), `8f1fb0a` (GREEN)
**Applied fix:** Composed `render._util.sanitise` into `_csv_safe` — sanitise
first (strip C1/bidi terminal-driving bytes), then apply the formula-injection
quote. The CSV is no longer the odd artefact out: a counter name carrying U+202E
or a single-byte CSI (0x9B) no longer reaches `perfmon_trend.csv` verbatim,
closing the T-13-MDESC/T-13-JSONESC gap for the third artefact.

### WR-01: spans with no counters produce zero CSV rows

**Files modified:** `src/sift/render/perfmon_report.py`, `tests/test_perfmon_report.py`
**Commits:** `43a524d` (RED), `f7c5358` (GREEN)
**Applied fix:** `write_perfmon_trend_csv` now emits one figure-less row per
counter-less `TrendGroup` (`for t in g.counters or (None,)`), so an unresolved
span or the critical zero-in-span non-overlap hazard is visible in the CSV
instead of contributing nothing. Honours D-06's "loud flag, never an empty table"
in the export as in Markdown. Kept minimal — a dedicated `hazards` CSV column was
deliberately not added (would change the header schema for every row); the
figure-less row is sufficient to make the span visible.

### WR-02: at-denial, slope and peak depend on caller-supplied order

**Files modified:** `src/sift/pipeline/perfmon.py`, `tests/test_perfmon.py`
**Commits:** `8769c57` (RED), `c5aa5ee` (GREEN)
**Applied fix:** `_in_span` and `_file_scope_groups`' `placeable` now sort on
`(ts, event_id)` — the same explicit key `_placeable_samples` already used —
rather than trusting input order. A scrambled sample list no longer yields a
wrong at-denial reading or a negative `elapsed` that inverts the slope. Regression
test feeds a deliberately scrambled list and asserts the chronologically-last
value is the at-denial figure.
**Note (logic change):** this alters correlation ordering semantics. The full
suite (including the D-21 byte-identity goldens) stays green, but a human should
confirm the sort-by-`(ts, event_id)` tie-break matches the intended determinism
contract.

### WR-04: `PerfmonHazard.severity` / `TrendGroup.scope` were unconstrained `str`

**Files modified:** `src/sift/pipeline/perfmon.py`, `tests/test_perfmon.py`, `tests/test_perfmon_report.py`
**Commits:** `e0ac2f9` (RED), `4cfb995` (GREEN), `fd243de` (gate follow-up)
**Applied fix:** Constrained `severity` to `Literal["info", "warn", "critical"]`
and `scope` to `Literal["episode", "file"]`. Pydantic now rejects a typo'd value
at construction (so a mistyped `"criticla"` can no longer rank below `info` in the
stdout summary) and pyright catches it at the call site. `dimension` was left an
open `str` — its vocabulary is genuinely open-ended (the `HAZARD_*` constants) and
the review only prescribed severity/scope. The follow-up commit types the
`_group` renderer-test helper's `scope` param as the same Literal (pyright gate).

### WR-05: `_csv_safe` missed a trigger behind leading whitespace

**Files modified:** `src/sift/render/perfmon_report.py`, `tests/test_perfmon_report.py`
**Commits:** `55f64fa` (RED), `afd9d22` (GREEN)
**Applied fix:** `_csv_safe` now tests the first *significant* character
(`value.lstrip(" \t\r\n")`) against the trigger set, and the trigger set was
re-derived down to the four printable triggers `("=", "+", "-", "@")` — tab/CR are
handled by the whitespace strip, in one place, rather than smuggled into the
trigger tuple where a first-character check still missed `" =cmd"`. Test rewritten
to cover leading-space and leading-tab-before-trigger cases and to confirm a
whitespace-then-ordinary name is left unquoted.

### WR-06: a CSV write failure leaves a half-written bundle

**Files modified:** `src/sift/cli.py`, `tests/test_cli_perfmon.py`
**Commits:** `129b634` (RED), `d96190a` (GREEN)
**Applied fix:** The `OSError` handler in `sift perfmon` now unlinks both the
report and the CSV (`unlink(missing_ok=True)`) before exiting 1, so an ENOSPC
mid-CSV can no longer leave a valid-looking `perfmon_report.md` next to a
truncated `perfmon_trend.csv`. Applied the identical guard to the sibling
`sift mcm` command the finding named. The new test patches
`write_perfmon_trend_csv` (which goes through `path.open`, the real WR-06 path —
the previous test only patched `write_text`, closing IN-02's coverage gap too).

## Skipped Issues

### WR-03: perfmon samples that lost their timestamp vanish with no hazard

**File:** `src/sift/pipeline/perfmon.py:519-524`, `236`
**Reason:** skipped — the requested change reverses a deliberately-frozen design
decision and its intended attribution is under-specified. `_file_scope_groups`
skipping an all-untimestamped file is frozen as *intended* behaviour by
`tests/test_cli_perfmon.py:118` (`test_no_episodes_untimestamped_file_yields_no_group`)
and is backed by the phase's locked decision that "missing/unresolvable
timestamps get a hazard flag rather than a guessed span, treated as expected
behavior." The review's fix ("a hazard naming the number of unplaceable perfmon
samples for that file/span") is well-defined for file scope but leaves the
episode-scope case undefined — an untimestamped sample has no `ts` and so cannot
be attributed to any time-bounded span. Reversing a frozen design decision and
choosing an episode-span attribution rule is a design judgement that needs human
sign-off, not an automated fix. Recommend routing to a scoped gap-closure/design
decision if the disclosure is wanted.

**Original issue:** `_in_span` requires `e.ts is not None` and
`_file_scope_groups` filters to `placeable`, so a degraded `severity="unknown"`
sample with a broken stamp is excluded from `sample_count`, the trends and every
hazard; a file whose samples are all untimestamped never appears in the report —
against "nothing disappears silently".

## Info findings (out of scope)

IN-01..IN-04 were Info-tier and outside the `critical_warning` fix scope. Note
that CR-01's rewrite also resolves the root cause of IN-04 (inconsistent
colliding-key formats), and WR-06's new test closes IN-02's untested CSV
write-failure branch as a side effect. IN-01 (duplicated `PerfmonFormat`/`_sev_rank`)
and IN-03 (`_find_counter_key` early return) remain open for a future pass.

---

_Fixed: 2026-07-20_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
