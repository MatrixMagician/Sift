---
phase: 13-episode-correlation-hazard-flags-sift-perfmon-report-csv
reviewed: 2026-07-20T00:00:00Z
depth: deep
files_reviewed: 9
files_reviewed_list:
  - src/sift/adapters/dssperfmon.py
  - src/sift/cli.py
  - src/sift/pipeline/perfmon.py
  - src/sift/render/perfmon_report.py
  - tests/_perfmon_fixtures.py
  - tests/test_cli_perfmon.py
  - tests/test_dssperfmon.py
  - tests/test_perfmon.py
  - tests/test_perfmon_report.py
findings:
  critical: 2
  warning: 6
  info: 4
  total: 12
status: issues_found
---

# Phase 13: Code Review Report

**Reviewed:** 2026-07-20
**Depth:** deep
**Files Reviewed:** 9
**Status:** issues_found

## Summary

The correlation module is unusually well-defended — round-at-source rounding, no
`set` iteration, `dict.fromkeys` everywhere, guards before every index and
divide, and hazards for structural conditions rather than silent absences. The
determinism contract (D-21) holds on the shipped path and I could not break it.

Two real defects survive, and both sit on load-bearing invariants the phase
claims to have closed:

1. `_qualify_counter_names` still silently drops a column when three or more
   header columns carry identical counter paths — while emitting a note that
   explicitly asserts "none is dropped". Reproduced below.
2. The trend CSV is the only one of the three shipped artefacts that does not
   run untrusted counter names through `sanitise`, so the terminal-injection
   threat closed for Markdown (T-13-MDESC) and JSON (T-13-JSONESC) is still open
   for `perfmon_trend.csv`.

Beyond those, the CSV export drops whole spans that have no counters (exactly
the spans carrying the *critical* non-overlap hazard), and the correlator's
headline figures silently depend on caller-supplied chronological ordering that
the public signature does not require.

## Critical Issues

### CR-01: 3+ identical counter paths collide again after qualification — one column silently dropped

**File:** `src/sift/adapters/dssperfmon.py:155-165`
**Issue:** The last-resort loop mutates `keys` while testing `keys.count(key)`
in the same pass. With three identical full counter paths the third element sees
a count of 1 and keeps its two-segment key, but the first two are *both*
rewritten to the identical full path — producing a duplicate key. `values =
dict(zip(counter_names, row[1:], strict=False))` at line 364 then drops one
column, which is precisely the WR-03 failure this function exists to prevent.
The docstring claims "the full path is the last resort that cannot [collide]"
and `_COLLISION_NOTE` tells the operator "so none is dropped (WR-03)" — a false
disclosure, which is worse than a silent drop under the "nothing disappears
silently" invariant.

Reproduced:

```
>>> p = "\\\\hostA\\Process(MSTRSvr)\\Size(MB)"
>>> _qualify_counter_names([p, p, p])[0]
['\\\\hostA\\Process(MSTRSvr)\\Size(MB)',      # <- duplicate
 '\\\\hostA\\Process(MSTRSvr)\\Size(MB)',      # <- duplicate
 'Process(MSTRSvr)\\Size(MB)']
```

**Fix:** Do not resolve collisions positionally against a mutating list.
Disambiguate deterministically and verify uniqueness before returning:

```python
    keys = [
        two_segment[i] if short in colliding else short
        for i, short in enumerate(shorts)
    ]
    # Promote every member of a group that is still ambiguous, not just the
    # ones a mutating count() happens to catch.
    ambiguous = {k for k in keys if keys.count(k) > 1}
    keys = [
        counter_paths[i] if k in ambiguous else k for i, k in enumerate(keys)
    ]
    # Exact-duplicate header columns cannot be told apart by any path; index
    # them so the column survives with a disclosed suffix rather than vanishing.
    seen: dict[str, int] = {}
    for i, k in enumerate(keys):
        seen[k] = seen.get(k, 0) + 1
        if seen[k] > 1:
            keys[i] = f"{k}#{seen[k]}"
```

Add a regression test asserting `len(set(keys)) == len(counter_paths)` for
`[p, p, p]` and that all three values reach `attrs`.

### CR-02: trend CSV bypasses `sanitise` — raw C1/bidi bytes from counter names reach the operator

**File:** `src/sift/render/perfmon_report.py:199-259`
**Issue:** `render_perfmon_markdown` routes every dynamic cell through `_field`
(which is `_escape(sanitise(...))`) and `render_perfmon_json` uses
`ensure_ascii=True`, both documented as security controls against
terminal-driving bytes in attacker-influenceable counter names. `write_perfmon_trend_csv`
applies only `_csv_safe`, which does nothing about control characters — its own
docstring concedes "``render._util.sanitise`` cannot serve as the guard either",
which is true but was taken as licence to omit it rather than to add it
*alongside*. A counter name carrying a single-byte CSI (0x9B) or U+202E lands
verbatim in `perfmon_trend.csv`; an operator who `cat`s or `less`es the bundle
(the natural thing to do with a two-file bundle) is exposed to exactly the
threat T-13-MDESC/T-13-JSONESC were raised for. The threat register's 27/27
closed claim does not hold for this artefact.

**Fix:** Compose both guards — sanitise first (strip the control bytes), then
neutralise the formula trigger:

```python
from sift.render._util import sanitise

def _csv_safe(value: str) -> str:
    cleaned = sanitise(value)
    return f"'{cleaned}" if cleaned.startswith(_FORMULA_TRIGGERS) else cleaned
```

Note the ordering matters: sanitising after the quote-prefix would leave a
stripped-to-empty trigger behind the quote. Add a test mirroring
`test_markdown_cells_pass_through_field` that asserts `_BIDI_OVERRIDE not in
path.read_text()`.

## Warnings

### WR-01: spans with no counters produce zero CSV rows — the loudest hazards are invisible in the export

**File:** `src/sift/render/perfmon_report.py:241-259`
**Issue:** The writer iterates `for t in g.counters`, so any `TrendGroup` with
`counters=()` contributes nothing at all. That is exactly the shape produced by
an unresolved span (`perfmon.py:580-601`, `counters=()`) and by the zero-in-span
case whose `_hazard_non_overlap` is graded **critical**. A consumer reading only
`perfmon_trend.csv` sees no evidence the episode was ever analysed, and hazards
never appear in the CSV under any circumstances. D-06's "loud flag, never an
empty table" is honoured in Markdown and dropped in the export.

**Fix:** Emit one figure-less row per counter-less group so the span is present,
and/or add a `hazards` column carrying `";".join(f"{h.dimension}:{h.severity}"
for h in g.hazards)` to every row:

```python
            rows = g.counters or (None,)
            for t in rows:
                writer.writerow((... if t is None else ...))
```

### WR-02: at-denial, slope and peak silently depend on caller-supplied chronological order

**File:** `src/sift/pipeline/perfmon.py:220-318`, `548`
**Issue:** `_counter_trends` takes `accepted[-1]` as the at-denial value,
`accepted[0]` as the slope origin, and relies on `max()`'s first-maximal
behaviour for "earliest sample on a tie" — all three are order-dependent, and
`_in_span` explicitly preserves input order rather than sorting. Yet
`_placeable_samples` (line 328) *does* sort, with the stated reason that
"``analyse_perfmon`` accepts a plain list, which a caller may have assembled in
any order". The module therefore acknowledges the hazard for the cosmetic
non-overlap message and ignores it for the three headline figures. An unordered
list yields a wrong at-denial reading, a wrong peak tie-break, and a *negative*
`elapsed` producing an inverted slope — all silently, with valid-looking
citations. `elapsed == 0.0` is guarded; `elapsed < 0.0` is not.

**Fix:** Sort once inside `_in_span` (and `_file_scope_groups`' `placeable`) on
the same explicit key `_placeable_samples` already uses, rather than documenting
a precondition the signature cannot enforce:

```python
    return sorted(
        (e for e in events if e.source == "dssperfmon" and e.ts is not None
         and start.ts <= e.ts <= end.ts),
        key=lambda e: (e.ts, e.event_id),
    )
```

### WR-03: perfmon samples that lost their timestamp vanish from the report with no hazard

**File:** `src/sift/pipeline/perfmon.py:519-524`, `236`
**Issue:** `_in_span` requires `e.ts is not None` and `_file_scope_groups` filters
to `placeable`, so a degraded `severity="unknown"` sample with a broken stamp is
excluded from `sample_count`, from the trends, and from every hazard. Worse, a
file whose samples are *all* untimestamped is `continue`d at line 524 and never
appears in the report at all — `test_no_episodes_untimestamped_file_yields_no_group`
freezes that as intended. The adapter went to real trouble to keep those rows
(`_fallback_event`, coverage accounting) and the correlator discards them
without a word, against "nothing disappears silently".

**Fix:** Count and disclose. Add an `info`-severity hazard per group naming the
number of unplaceable perfmon samples for that file/span, citing up to
`_CITE_CAP` of them, and emit a group for an all-untimestamped file carrying only
that hazard.

### WR-04: `PerfmonHazard.severity` / `scope` / `dimension` are unconstrained `str`

**File:** `src/sift/pipeline/perfmon.py:101-105`, `142-143`
**Issue:** The docstrings fix the vocabularies (`"info" | "warn" | "critical"`,
`"episode" | "file"`) but the types are bare `str` with `extra="forbid"` giving
no help. A typo'd severity passes validation, then `cli.py:1155`'s
`_sev_rank.get(h.severity, 3)` ranks it *below* `info`, so a mistyped
`"criticla"` hazard would be the least likely to be surfaced in the stdout
summary. `_group_section` (`perfmon_report.py:153`) has the same weakness: any
scope that is not `"episode"` renders as "File".

**Fix:** `from typing import Literal` and constrain them —
`severity: Literal["info", "warn", "critical"]`, `scope: Literal["episode",
"file"]`. Pydantic then rejects the typo at construction and pyright catches it
at the call site.

### WR-05: `_csv_safe` misses a trigger behind leading whitespace

**File:** `src/sift/render/perfmon_report.py:224`
**Issue:** The docstring's own reasoning ("leading whitespace is stripped before
the first significant character is examined") is why `\t` and `\r` are in
`_FORMULA_TRIGGERS` — but the check is a single `startswith` on the first
character, so `" =cmd|'/c calc'!A0"` (leading *space*) and `"\t =..."` both pass
the guard untouched while still being whitespace-stripped by the spreadsheet.

**Fix:** Test the first significant character, not the first character:

```python
    return f"'{value}" if value.lstrip(" \t\r\n").startswith(_FORMULA_TRIGGERS) else value
```

(If CR-02's `sanitise` composition lands, `\t`/`\r` handling shifts — re-derive
the trigger set once, in one place.)

### WR-06: a CSV write failure leaves a half-written bundle behind

**File:** `src/sift/cli.py:1133-1145`
**Issue:** The report is written first, then the CSV. If
`write_perfmon_trend_csv` fails mid-write (ENOSPC after the header), the command
exits 1 having left a valid-looking `perfmon_report.md` next to a truncated
`perfmon_trend.csv` on disk. Nothing tells a later reader the CSV is partial,
and the same failure mode exists in `sift mcm`.

**Fix:** Render both artefacts to strings/bytes in memory, then write, and unlink
partial output on failure — or write to `*.tmp` and `os.replace` both files only
once both have been produced.

## Info

### IN-01: `PerfmonFormat` and `_sev_rank` are verbatim copies of the `mcm` versions

**File:** `src/sift/cli.py:1074-1081`, `1153`, cf. `995-1001`, `1060`
**Issue:** `PerfmonFormat` is byte-identical to `McmFormat` (both `md`/`json`
with a near-identical docstring) and `_sev_rank` is defined twice in the same
module. A future third bundle command copies it again.
**Fix:** One module-level `_SEV_RANK` and one `BundleFormat` StrEnum shared by
both commands.

### IN-02: the CSV write-failure path is untested

**File:** `tests/test_cli_perfmon.py:217-231`
**Issue:** `test_write_failure_exit_one` monkeypatches `Path.write_text`, which
only the report uses — `write_perfmon_trend_csv` goes through `path.open`. The
CSV branch of the OSError handler has no coverage, which is what let WR-06 sit
unnoticed.
**Fix:** Add a case patching `pathlib.Path.open` (or `csv.writer`) and assert
exit 1 plus the sanitised message.

### IN-03: `_find_counter_key`'s early return makes the anti-evasion scan unreachable in its stated case

**File:** `src/sift/pipeline/perfmon.py:407-411`
**Issue:** The docstring justifies returning a tuple by T-13-EVADE ("checking
only one would let a genuinely non-zero instance be masked"), but the first
branch returns the bare name alone and skips the qualified scan entirely. It
happens to be safe because `_qualify_counter_names` qualifies *all* members of a
colliding group, so bare and qualified spellings cannot co-exist in one event's
attrs — but that is a non-local invariant the comment does not name.
**Fix:** Drop the early return and let the single sorted comprehension handle
both spellings (`key == MCM_DENIAL_COUNTER or key.rsplit("\\", 1)[-1] == ...`),
or state the cross-module invariant the shortcut relies on.

### IN-04: colliding-group members end up with inconsistent key formats

**File:** `src/sift/adapters/dssperfmon.py:155-157`
**Issue:** Same root cause as CR-01: because `keys.count()` is evaluated against
a list being mutated, the last member of a two-segment-colliding group keeps its
two-segment key while its siblings are promoted to full paths. The keys are
unique (for n=2) but the format for one logical counter varies by column
position, and the `_COLLISION_NOTE` presents the mixture as if it were uniform.
**Fix:** Covered by CR-01's rewrite — promote the whole ambiguous group or none
of it.

---

_Reviewed: 2026-07-20_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
