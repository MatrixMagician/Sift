---
phase: 02-case-store-template-dedup
plan: 04
subsystem: case-store
tags: [gap-closure, savepoint, sanitisation, masking, sqlite, security]
requires:
  - phase: 02-case-store-template-dedup
    plan: 01
    provides: template dedup pipeline, _MASK alternation, rebuild_template_groups
  - phase: 02-case-store-template-dedup
    plan: 02
    provides: batched streaming ingest, single BEGIN IMMEDIATE event transaction
  - phase: 02-case-store-template-dedup
    plan: 03
    provides: allowlisted --filter parsing, streaming show events
provides:
  - CaseStore.savepoint() contextmanager (per-file ingest atomicity, CR-01)
  - template_groups_stale meta-key contract (crash-between-commit-and-rebuild detection)
  - whole-line _sanitise on both show render paths (WR-01, T-02-11)
  - non-list exemplar_event_ids JSON guard in query_template_groups
  - duplicate --filter key rejection (exit 2, WR-05)
  - graceful show failure on corrupt case.db + stderr migration notice (WR-02)
  - MASK_VERSION 2 letter-required bare-hex mask (WR-04)
affects: [03-embeddings, 04-analysis]
tech-stack:
  added: []
  patterns:
    - "SQL identifier interpolation only from module constants (savepoint name mirrors PRAGMA user_version precedent)"
    - "render-time whole-line sanitisation instead of per-field coverage"
key-files:
  created: []
  modified:
    - src/sift/store.py
    - src/sift/cli.py
    - src/sift/pipeline/dedup.py
    - tests/test_cli.py
    - tests/test_store.py
    - tests/test_dedup.py
    - .planning/REQUIREMENTS.md
key-decisions:
  - "Savepoint name is the code constant _SAVEPOINT_INGEST_FILE, interpolated into SQL text under the PRAGMA user_version never-user-data convention (T-02-13)"
  - "template_groups_stale contract: ingest sets '1' inside the event transaction, rebuild_template_groups clears '0' inside the rebuild transaction, show clusters reads and warns on stderr"
  - "MASK_VERSION 2: bare hex requires at least one hex letter; pure-decimal 8+ digit runs are <NUM> — groups recompute from store on next ingest, no migration"
  - "Migration notices print on stderr for every applied migration, including fresh case creation (v0->v1->v2) — stdout contract untouched"
duration: 13min
completed: 2026-07-16
status: complete
---

# Phase 2 Plan 04: Gap Closure (CR-01, WR-01..WR-05) Summary

Per-file SAVEPOINT makes failed-file accounting exactly zero rows, whole-line _sanitise closes every DB-sourced render field, duplicate --filter keys fail loudly, and the traceability record now states Phase 2's true partial scope.

## What was built

### Task 1 — CR-01 per-file savepoint (+ WR-03, IN-03, IN-04)

- **`CaseStore.savepoint()`** (`src/sift/store.py`): `SAVEPOINT ingest_file` → yield → `RELEASE` on success, `ROLLBACK TO` + `RELEASE` on any exception. The name comes only from the module constant `_SAVEPOINT_INGEST_FILE` — never user data. SQLite savepoints nest natively inside the outer `BEGIN IMMEDIATE` ingest transaction, so a mid-stream parse failure (e.g. truncated .gz raising EOFError after two 5000-event insert batches) rolls that file back to zero rows while earlier files' inserts survive.
- **cli.py `_ingest`**: the per-file body (detect → parse → batched insert) now runs inside `with store.savepoint():`; the outer `except Exception` branch keeps its exact shape — its `event_count: 0` record is now TRUE.
- **`template_groups_stale` meta-key contract (WR-03)**: ingest sets `"1"` inside the event transaction (beside the parse_coverage write); `rebuild_template_groups` clears to `"0"` inside the rebuild transaction (beside the mask_version write); `show clusters` reads it and warns on stderr (`"template groups are stale ... re-run 'sift ingest'"`) while still rendering groups on stdout.
- **IN-03**: the bare `ROLLBACK` statements in `_migrate` and `transaction()` — and the savepoint's rollback pair — are wrapped in `try/except sqlite3.OperationalError: pass` so a dead transaction never masks the original error.
- **IN-04**: the sizes pass is a per-file `stat()` loop recording 0 on OSError — a vanished file fails loudly in the per-file loop, not with a run-aborting traceback.
- **Pinning test**: `test_ingest_truncated_gz_mid_stream_contributes_zero_rows` proves the fixture is mid-stream (>5000 yields before EOFError, asserted 10000+ on RED), then asserts zero rows from the failed file and the three-way identity `sum(template_groups.count) == count(events) == sum(parse_coverage event_counts)`.

### Task 2 — WR-01 whole-line sanitisation, WR-05 duplicate keys, WR-02 graceful open

- **Both show render paths** wrap the complete rendered f-string in `_sanitise(...)`: event_id, ts, severity, template_id, count, severity_max, first_ts, last_ts and every exemplar id are covered in one move. Store-level hostile-bytes fixture (ESC/CSI in first_ts, ESC + U+202E in exemplar ids, ESC in event_id/ts/message) verifies no raw ESC or bidi override ever reaches the terminal.
- **Non-list exemplar guard** (`store.query_template_groups`): tampered non-array JSON is wrapped as a single-element list and all elements coerced via `str()` while the value is still typed `Any` (a `cast("list[object]", ...)` satisfies pyright strict) — tampering stays visible, `' '.join` never crashes.
- **WR-05**: `_parse_filters` raises `ValueError("duplicate filter key ...")` immediately after the allowlist check; the existing show error path converts it to a sanitised exit 2.
- **WR-02**: `_case_store` catches `sqlite3.Error` → `Error: cannot open case {case!r}: {sanitised exc}`, exit 1, no traceback. `_migrate` prints `note: migrating case.db to schema v{N}` on stderr for every migration it applies (including fresh creation v0→v1→v2); reopening at head is silent, and existing stdout-contract tests stay untouched.

### Task 3 — WR-04 decimal-safe hex mask + traceability notes

- **`MASK_VERSION = 2`** in `src/sift/pipeline/dedup.py`. The bare-hex alternative is now `\b(?=[0-9a-fA-F]{8,}\b)(?=[0-9]*[a-fA-F])[0-9a-fA-F]+`: two `\b`-anchored bounded linear lookaheads gate length/charset and require at least one hex LETTER. Pure-decimal 8+ digit runs (epoch seconds/millis, large ids) fall through to `<NUM>` — templates no longer shatter by numeric magnitude. `0x`-prefixed and 32-hex SID runs still mask to `<HEX>`; the ReDoS test and all SID fixtures pass unchanged.
- **Rationale for no migration**: groups recompute from store on next ingest; `rebuild_template_groups` already records mask_version in meta.
- **REQUIREMENTS.md notes confirmed at all four locations**: STORE-04 checkbox line, CLI-03 checkbox line, STORE-04 traceability row, CLI-03 traceability row (`grep -c "partial scope"` returns 4).

## Deviations from Plan

None - plan executed exactly as written. (Minor implementation detail: pyright strict required a `cast("list[object]", ...)` for the exemplar guard rather than a plain annotated ternary; behaviour identical to the plan's sketch.)

## Verification

- `uv run pytest -q`: 174 passed (perf marker excluded per addopts), including 8 new tests
- `uv run ruff check`: clean
- `uv run pyright`: 0 errors
- `grep -c "partial scope" .planning/REQUIREMENTS.md` = 4
- Prohibitions intact: stored raw/message stay verbatim (all changes are render-time or write-path atomicity); no new imports beyond stdlib `sys`/`sqlite3`/`typing.cast`; no network egress

## TDD Gate Compliance

All three tasks followed RED→GREEN with gate commits:

| Task | RED commit | GREEN commit |
|------|-----------|--------------|
| 1 (CR-01/WR-03) | a78ac6f | 47a39e6 |
| 2 (WR-01/WR-02/WR-05) | 2d52d1d | d74a400 |
| 3 (WR-04/traceability) | 9e465f1 | 7d80a07 |

## Deferred ride-alongs (from plan, unchanged)

IN-01 (severity vocabulary), IN-02 (migration 2 fetchall), IN-05 (dir-symlink silence), IN-06 (ZstdError context) — reasons recorded in 02-04-PLAN.md. Human-verification items (TTY progress, idle-machine perf re-run, migration-concurrency/interrupted-ingest backstops, prohibition sign-off) proceed to end-of-phase UAT.
