---
phase: 01-skeleton-event-contract-genericlog-adapter
fixed_at: 2026-07-16T17:22:26Z
review_path: .planning/phases/01-skeleton-event-contract-genericlog-adapter/01-REVIEW.md
iteration: 1
findings_in_scope: 9
fixed: 9
skipped: 0
status: all_fixed
---

# Phase 01: Code Review Fix Report

**Fixed at:** 2026-07-16T17:22:26Z
**Source review:** .planning/phases/01-skeleton-event-contract-genericlog-adapter/01-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 9 (2 Critical, 7 Warning; fix_scope=critical_warning, 6 Info findings out of scope)
- Fixed: 9
- Skipped: 0

Every fix was gated on `uv run pytest -q && uv run ruff check && uv run pyright`
before its commit (98 -> 108 tests, all green throughout; ruff and pyright clean
after every commit). Frozen contracts untouched: the Event dataclass and the
Adapter protocol are byte-identical, and the golden
`event_id("app.log", 12345) == "f7fdcb4b3de90265"` still holds (covered by the
suite). Zero-network autouse guard unchanged.

## Fixed Issues

### CR-01: Corrupt/unreadable compressed file crashes the whole ingest during adapter detection

**Files modified:** `src/sift/cli.py`, `tests/test_cli.py`
**Commit:** 88d82e3
**Applied fix:** Moved `adapters.detect(...)` and the per-run adapter
configuration inside the per-file `try` in the ingest loop, so decompression
errors raised during sniffing hit the same loud `ERROR <file>` path as parse
failures instead of aborting the run and rolling back good files. Regression
test `test_ingest_corrupt_compressed_file_fails_loudly_but_continues` uses a
truncated `.gz` next to a good log: exit 1, `ERROR truncated.log.gz` printed,
and the good file's 3 events survive and are shown.

### CR-02: Terminal escape injection via hostile filenames — T-04-01 bypass in `ingest` and `show`

**Files modified:** `src/sift/cli.py`, `tests/test_cli.py`
**Commit:** d7ca979
**Applied fix:** `_sanitise` is now applied to `relpath` in both ingest print
sites, to `str(exc)` in the error line, and to `e.source_file` in `show`.
Regression test `test_hostile_filename_escapes_never_reach_terminal` creates a
file literally named `\x1b[31mEVIL\x1b[0m.log` and asserts no raw `\x1b`
reaches stdout from either `ingest` or `show` (the review's repro).

### WR-01: `--adapter` flag does not beat `config.adapters` when globs differ (D-08)

**Files modified:** `src/sift/cli.py`, `tests/test_cli.py`
**Commit:** 0e342c3
**Applied fix:** Override merge reordered to
`dict(flag_overrides) | {g: n for g, n in config.adapters.items() if g not in flag_overrides}`
so flag globs come first in insertion order and win `detect`'s first-match
rule. Test `test_adapter_flag_beats_overlapping_config_glob` registers a
recording fake adapter, sets config `"*.log" = "genericlog"` plus flag
`app.log=recording`, and asserts the fake adapter parsed the file.

### WR-02: Symlinks inside the untrusted bundle pull in files from outside it

**Files modified:** `src/sift/cli.py`, `tests/test_cli.py`
**Commit:** f2883d9
**Applied fix:** The ingest loop skips symlinks with a loud
`SKIP <file>: symlink (not followed)` line and records
`{"skipped": ..., "event_count": 0, "coverage": 0.0}` in the persisted
`parse_coverage` meta so nothing vanishes silently. Test
`test_ingest_skips_symlinks_loudly_never_follows` symlinks a file outside the
bundle and asserts its content never reaches the case DB while the skip lands
in the meta.

### WR-03: `sift new` over an existing case silently repoints it

**Files modified:** `src/sift/cli.py`, `tests/test_cli.py`
**Commit:** dddba2f
**Applied fix:** `new` exits 1 with
`Error: case '<name>' already exists at <dir>` when the case DB already
exists, preventing mixed-snapshot corruption. Test
`test_new_refuses_to_overwrite_existing_case` runs `new` twice with different
input directories.

### WR-04: Failed files silently absent from the persisted `parse_coverage` record

**Files modified:** `src/sift/cli.py`, `tests/test_cli.py`
**Commit:** dd84afa
**Applied fix:** The per-file failure path now writes
`{"error": str(exc), "event_count": 0, "coverage": 0.0}` into the coverage
meta before continuing. Test `test_failed_file_recorded_in_parse_coverage_meta`
asserts the truncated archive appears in the persisted record alongside the
good file.

### WR-05: Config typos silently ignored (pydantic `extra` defaults to ignore)

**Files modified:** `src/sift/config.py`, `tests/test_config.py`
**Commit:** 9c9f9b5
**Applied fix:** `SiftConfig` gains `model_config = ConfigDict(extra="forbid")`
(T-04-02: a typo'd key must fail loudly). Tests assert `data_dirr = ...` and a
`[timezone]` section typo both raise `ValidationError` naming the offending
key.

### WR-06: `_sanitise` passes Unicode bidi/zero-width controls

**Files modified:** `src/sift/cli.py`, `tests/test_cli.py`
**Commit:** e858ae9
**Applied fix:** `_sanitise` additionally drops any character whose Unicode
category is `Cf` (bidi overrides such as U+202E, zero-width characters,
U+FEFF), with the docstring updated. Test
`test_show_strips_bidi_and_zero_width_characters` feeds U+202E/U+202C/U+200B/
U+FEFF through log content and asserts none reach `show` output (escape
sequences, not raw bytes, live in the test source).

### WR-07: UTF-16 newline byte-scan can match across character boundaries

**Files modified:** `src/sift/adapters/genericlog.py`, `tests/test_genericlog.py`
**Commit:** 9f7d48a
**Applied fix:** `_byte_lines` gains a `unit` parameter (the encoding's
code-unit width; `parse` passes `unit=len(nl)`) and tracks bytes consumed so a
newline `find` hit only counts at a unit-aligned offset from the stream start.
The force-split `ponytail:` comment now also notes that the even
`MAX_EVENT_BYTES` cap preserves alignment. Test
`test_encoding_utf16le_fake_newline_across_char_boundary_not_split` uses the
review's exact byte pattern (U+0A41 then U+0100 -> `... 41 0A 00 01 ...`);
verified to FAIL against the pre-fix code and pass with the fix. The frozen
Adapter protocol is unaffected (`_byte_lines` is a module-private helper).

## Skipped Issues

None — all in-scope findings were fixed. The 6 Info findings (IN-01..IN-06)
were out of scope for `fix_scope=critical_warning` and remain open in
01-REVIEW.md.

---

_Fixed: 2026-07-16T17:22:26Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
