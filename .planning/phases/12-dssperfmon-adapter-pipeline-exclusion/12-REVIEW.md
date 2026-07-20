---
phase: 12-dssperfmon-adapter-pipeline-exclusion
reviewed: 2026-07-20T00:00:00Z
depth: deep
files_reviewed: 9
files_reviewed_list:
  - src/sift/adapters/dssperfmon.py
  - src/sift/adapters/__init__.py
  - src/sift/adapters/dsserrors.py
  - src/sift/store.py
  - tests/test_dssperfmon.py
  - tests/test_adapters_detect.py
  - tests/test_cli.py
  - tests/test_cluster.py
  - tests/test_store.py
findings:
  critical: 0
  warning: 5
  info: 2
  total: 7
status: issues_found
---

# Phase 12: Code Review Report

**Reviewed:** 2026-07-20
**Depth:** deep (cross-file: store seam → dedup/cluster/hypothesise/eval/mcm/render)
**Files Reviewed:** 9
**Status:** issues_found

## Summary

The load-bearing parts of this phase are correct. I traced the four items the brief
flagged as highest-risk and all four hold up:

- **Citation integrity — correct.** `iter_event_summaries` (store.py:641) is the sole
  reader for every ranking stage: `dedup.py:102`, `cluster.py:113`, `hypothesise.py:191`,
  `eval/runner.py:63`. No ranking stage re-implements the query. Conversely
  `get_events_by_ids` (store.py:600, the only citation-hydration path,
  `render/markdown.py:197`) and `iter_event_rows` (store.py:672, `cli.py:614`) are
  unfiltered. The asymmetry is right in both directions, and because the LLM only ever
  sees summaries it can never emit a perfmon citation in the first place.
- **SQL construction — safe.** store.py:664-667 interpolates only `placeholders`, which is
  derived purely from `len(excluded)`; the values are `?`-bound from a module constant no
  caller can reach. The `# noqa: S608` is justified.
- **Determinism — holds.** `sorted(EXCLUDED_FROM_RANKING)` at store.py:659 is the only
  consumption site of the frozenset (grep-confirmed), so the ordering guard is complete.
  In the adapter, `offset += len(bline)` (dssperfmon.py:195) precedes every decode and
  every branch, so `event_id` is stable regardless of parse outcome.
- **Timezone — correct.** The `# noqa: DTZ007` at dssperfmon.py:221 is genuine, not
  papering: a PDH sample stamp carries no zone, and attaching one before `to_utc` would
  bypass the `--tz` override that ADR 0012 makes the single seam.

I also checked the blast radius the exclusion does *not* cover: `hypothesise.py:370` and
`cli.py:1037` still call the unfiltered `store.query_events()` into `analyse_mcm`. This is
**not** a bug — `detect_episodes` (mcm.py:815) and `attribute_window` (mcm.py:891) both
filter `source == "dsserrors"` before building their line streams, so interleaved perfmon
rows cannot perturb episode spans, lead-up windows or attribution indices. I verified none
of the MCM markers false-positive on perfmon message text either: the counter named
`Total MCM Denial` does not match `DENIAL_MARKER` ("IServer enters MCM denial state"),
and `Size(MB)=` does not match `SIZE_RE` (`\bSize=`).

The findings below are all in the adapter's malformed-input handling, where the module's
own stated guarantees (never-drop, nothing-disappears-silently) are not fully met.

## Warnings

### WR-01: `csv.Error` escapes the never-drop guarantee and aborts the whole file

**File:** `src/sift/adapters/dssperfmon.py:202`
**Issue:** `next(csv.reader([text]))` is unguarded. `csv` raises `_csv.Error` — which is
*not* a `ValueError` — when a field exceeds `csv.field_size_limit()` (131,072 chars by
default; confirmed by probe). Because `byte_lines` splits on `b"\n"` only, a PDH CSV
written with CR-only line endings, or one concatenated/truncated by a bundling script,
delivers the entire file as a single "line" and trips this immediately. `next()` raising
`StopIteration` inside a generator would likewise become a `RuntimeError` under PEP 479.

Neither path reaches `_fallback_event`, so the row does not degrade to
`severity="unknown"` — it propagates to `cli.py:348`, which records the file as failed and
sets `coverage: 0.0, event_count: 0`. Every row already parsed in that file is discarded
from the coverage record. The module docstring's claim that "no caller returns, raises or
continues past emission" (line 95) is false for this path.

**Fix:**
```python
try:
    row = next(csv.reader([text]))
except (csv.Error, StopIteration):
    # A row csv cannot tokenise still costs exactly one Event (PERF-02).
    stats.event_count += 1
    stats.unknown_fallback_bytes += len(bline)
    yield _fallback_event(
        relpath=relpath, case_id=case_id, line_offset=line_offset,
        line_no=line_no, host=header[0] if header else "", ts=None,
        ts_confidence="missing",
        attrs={"byte_offset": str(line_offset), "byte_len": str(len(bline))},
        text=text,
    )
    continue
```

### WR-02: Per-row drift notes are unbounded — stdout flood and `case.db` meta bloat

**File:** `src/sift/adapters/dssperfmon.py:246-250`
**Issue:** `_DRIFT_NOTE` is appended to `stats.notes` **once per drifted row**. `cli.py:383`
persists the full note list into the `parse_coverage` meta JSON and `cli.py:390-391` prints
every note to stdout. A single systematic defect — a header row whose width does not match
the body (trailing-comma variance is common in PDH exports) — makes every one of the
Hartford file's 13,596 rows drift, producing 13,596 printed lines and roughly a megabyte of
notes in one `meta` row. Every other adapter emits a bounded, file-level note set.
**Fix:** Cap the disclosure. Emit at most N line-specific notes, then one aggregate:
```python
_DRIFT_CAP = 20
if drifted:
    stats.drift_count += 1          # or a local counter
    if stats.drift_count <= _DRIFT_CAP:
        stats.notes.append(_DRIFT_NOTE.format(...))
    elif stats.drift_count == _DRIFT_CAP + 1:
        stats.notes.append("further column-drift notes suppressed; see event attrs.")
```
(pair with WR-05 so the per-event marker carries the detail the suppressed notes lose).

### WR-03: Counter short-name collisions silently drop columns

**File:** `src/sift/adapters/dssperfmon.py:76`, `227`
**Issue:** `_short_counter_name` keeps only the final backslash segment, discarding the
object/instance segment — so `\\host\Process(MSTRSvr)\% CPU time` and
`\\host\Process(other)\% CPU time` both reduce to `% CPU time`. `dict(zip(...))` at line 227
keeps the **last** one; the earlier column vanishes from `attrs` and from `message`, is not
listed in `unparsed_columns`, and does not set `drifted`. The row is emitted as
`severity="info"` — a clean event that has silently lost a counter. This contradicts
"nothing disappears silently" and would leave Phase 13's correlator reading the wrong
series with no signal that anything happened.

Not triggered by the Hartford fixture (all 22 short names are unique — verified), but
per-instance counters are the norm in PDH exports, so this is a latent data-loss path in
real customer data, not a theoretical one.
**Fix:** Detect the collision in `_parse_header` and disambiguate rather than collapse —
e.g. fall back to the last *two* segments (`Process(MSTRSvr)\% CPU time`) for any short
name that is not unique, and add a note recording the requalification.

### WR-04: Counter names can clobber reserved provenance keys in `attrs`

**File:** `src/sift/adapters/dssperfmon.py:228-239`
**Issue:** `attrs.update(values)` runs **after** `byte_offset`, `byte_len`, `host`,
`pdh_version`, `tz_name` and `tz_offset_min` are set, so a counter whose final path segment
is literally `byte_offset` (or `host`, or `tz_offset_min`) overwrites the provenance value.
The module docstring itself states at line 12 that counter names are attacker-influenceable
(T-12-01), and `byte_offset` is the value the determinism contract is written against — a
report or a Phase 13 consumer reading `attrs["byte_offset"]` would get an attacker-supplied
string. `unparsed_columns` (line 255) is exposed to the same overwrite.
**Fix:** Namespace the counter values so the two key spaces cannot intersect:
```python
attrs.update({f"counter.{k}": v for k, v in values.items()})
```
or, if the flat keys are wanted downstream, build `attrs` as `{**values, **reserved}` so
the reserved keys always win.

### WR-05: Drifted rows carry no per-event reason for the `severity="unknown"` degrade

**File:** `src/sift/adapters/dssperfmon.py:244-256`
**Issue:** A row degraded for bad cells records *why* on the event itself
(`attrs["unparsed_columns"]`, line 255). A row degraded for column drift records the reason
only in the file-level `stats.notes`. An analyst running `sift show events` on a drifted row
sees `severity="unknown"` with no explanation on the event, and has to cross-reference the
`parse_coverage` meta blob by line number. The two degrade paths should be symmetric,
particularly once WR-02's cap suppresses most of the notes.
**Fix:** Mirror the `unparsed_columns` idiom:
```python
if drifted:
    attrs["column_drift"] = f"{len(row)}/{header_width}"
```

## Info

### IN-01: `float()` validity probe accepts values PDH never emits

**File:** `src/sift/adapters/dssperfmon.py:126`
**Issue:** `float()` accepts `nan`, `inf`, `-inf`, PEP 515 underscores (`float("1_0") == 10.0`)
and hex-float literals. A cell of `1_0` therefore passes the probe and is stored verbatim as
the string `"1_0"`; any downstream consumer re-running `float()` reads `10.0`, so the stored
text and the interpreted value disagree. Harmless against real PDH output, worth tightening
before Phase 13 consumes these numerically.
**Fix:** Reject non-finite and underscore forms explicitly, e.g.
`if "_" in value or not math.isfinite(float(value)): bad.append(name)`.

### IN-02: An empty `EXCLUDED_FROM_RANKING` would build invalid SQL

**File:** `src/sift/store.py:659-666`
**Issue:** If the frozenset is ever emptied (a plausible future edit — "exclusion is now
config-driven"), `placeholders` becomes `""` and the query is `WHERE source NOT IN ()`,
which SQLite rejects with a syntax error rather than degrading to "exclude nothing". A
silent trap for the next editor.
**Fix:** Guard the branch, matching the `if not ids: return {}` idiom already used in
`get_events_by_ids` (store.py:611):
```python
if not EXCLUDED_FROM_RANKING:
    where = ""
    params: tuple[str, ...] = ()
else:
    ...
```

---

_Reviewed: 2026-07-20_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
