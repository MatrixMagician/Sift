---
phase: 01-skeleton-event-contract-genericlog-adapter
plan: 02
subsystem: ingest
tags: [event-schema, adapter-protocol, sqlite, genericlog, walking-skeleton]

requires:
  - 01-01 (scaffold, quality gates, RED walking-skeleton e2e test)
provides:
  - Frozen Event dataclass (SPEC §5.1 verbatim, 16 fields) + canonical event_id() with pinned golden value f7fdcb4b3de90265
  - Frozen Adapter Protocol (SPEC §5.2 verbatim) + open_bytes decompression seam (gzip/zstd magic bytes) + ParseStats
  - Adapter registry (REGISTRY/get/detect-v0) — adapter #5 = new module + one line
  - CaseStore: PRAGMA user_version migrations, INSERT OR IGNORE idempotency, deterministic query_events, transaction()
  - genericlog v0: ISO 8601 byte-offset streaming parse, continuation grouping (D-06), to_utc confidence (D-05)
  - Working new/ingest/show events CLI bodies — walking skeleton GREEN
affects: [01-03, 01-04, 01-05, phase-2, phase-5]

tech-stack:
  added: []
  patterns:
    - "Per-run adapter configuration travels on the instance (input_root, tz_overrides, last_stats) — Protocol signature is frozen"
    - "store.py is the single SQL owner; parameterised ? placeholders only"
    - "Timestamps stored as ISO 8601 strings (sqlite3 datetime adapter deprecated on 3.12+)"
    - "Byte offsets computed on raw decompressed bytes, decode errors-replace only after offsets fixed"

key-files:
  created:
    - src/sift/models.py
    - src/sift/config.py
    - src/sift/store.py
    - src/sift/adapters/__init__.py
    - src/sift/adapters/base.py
    - src/sift/adapters/genericlog.py
    - tests/test_models.py
    - tests/test_store.py
  modified:
    - src/sift/cli.py
    - tests/test_cli.py

key-decisions:
  - "event_id serialisation frozen: sha256(source_file + NUL + str(byte_offset))[:16]; golden value f7fdcb4b3de90265 pinned by test"
  - "CaseStore opens sqlite3 in autocommit (isolation_level=None); all transactionality explicit via BEGIN IMMEDIATE in transaction() and the migration runner"
  - "cli ingest narrows detect()'s Adapter to GenericLogAdapter via assert isinstance (v0-only; plan 01-04 generalises configuration with the sniff algorithm)"
  - "TDD_MODE off per orchestrator: tests and implementation land together in one commit per task (no separate RED/GREEN commits)"

patterns-established:
  - "Coverage formula: 1 - unknown_fallback_bytes/total_bytes; empty file = 1.0 (cannot trivially read 100%)"
  - "show output sanitised: control characters stripped so hostile log content cannot drive the terminal"

requirements-completed: [INGST-01, INGST-02]

coverage:
  - id: D1
    description: "event_id('app.log', 12345) == 'f7fdcb4b3de90265'; 16 lowercase hex; NUL disambiguation; Event frozen"
    requirement: "INGST-01"
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_models.py (9 passed)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Fresh case.db: PRAGMA user_version == 1; insert twice -> N then 0; deterministic ordering; case-name allowlist"
    requirement: "INGST-02"
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_store.py (16 passed, incl. test_reingest_idempotent)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Walking skeleton GREEN: new -> ingest (coverage % printed) -> show events (three 16-hex IDs)"
    requirement: "INGST-01"
    verification:
      - kind: e2e
        ref: "uv run pytest tests/test_cli.py::test_walking_skeleton_happy_path (exit 0)"
        status: pass
      - kind: manual_procedural
        ref: "uv run sift new/ingest/show smoke against a scratch log dir — per-file coverage line and event row printed"
        status: pass
    human_judgment: false
  - id: D4
    description: "Second ingest prints '0 new' and row count unchanged"
    requirement: "INGST-02"
    verification:
      - kind: e2e
        ref: "uv run pytest tests/test_cli.py::test_reingest_adds_zero_events"
        status: pass
    human_judgment: false
  - id: D5
    description: "Full quality gates green"
    verification:
      - kind: other
        ref: "uv run pytest (27 passed); uv run ruff check; uv run pyright — all exit 0"
        status: pass
    human_judgment: false

duration: 15min
completed: 2026-07-16
status: complete
---

# Phase 01 Plan 02: Event Contract, Case Store & genericlog v0 Summary

**Frozen Event schema + Adapter protocol with pinned golden event_id, per-case SQLite store with user_version migrations and idempotent INSERT OR IGNORE, genericlog v0 byte-offset ISO parser, and real new/ingest/show bodies — the walking skeleton stands GREEN**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-07-16T16:11:40Z
- **Completed:** 2026-07-16T16:26:00Z
- **Tasks:** 3 (all auto)
- **Files modified:** 10

## Accomplishments

- Both permanent contracts frozen: `Event` (16 fields, SPEC §5.1 verbatim) and `Adapter` Protocol (SPEC §5.2 verbatim); golden value `event_id("app.log", 12345) == "f7fdcb4b3de90265"` pinned by test
- Decompression seam: `open_bytes` detects gzip (`1f 8b`) and zstd (`28 b5 2f fd`, `read_across_frames=True`) by magic bytes; `read_head` sniffs decompressed content only
- `CaseStore`: migration 1 creates events/meta/idx_events_ts under `PRAGMA user_version = 1`; `insert_events` returns the newly-inserted count via total_changes delta; `query_events` ordered by ts (NULLs last), source_file, line_start; `transaction()` makes a whole ingest run atomic (proven by rollback test)
- genericlog v0: streaming byte-level line split with running offset counter (never `.tell()`, never decoded-text offsets), anchored ISO 8601 candidate fed to `fromisoformat`, continuation grouping and leading-unknown-region handling per D-06, `to_utc` confidence per D-05, severity token scan that never fabricates
- CLI walking skeleton complete: `sift new` (validates case name, records input_dir/created_at), `sift ingest` (sorted rglob walk, per-file coverage line, loud per-file errors with exit 1, single transaction incl. `parse_coverage` meta), `sift show <case> events` (sanitised output)
- e2e test `test_walking_skeleton_happy_path` GREEN; re-ingest prints "0 new" with unchanged row count

## Task Commits

Each task was committed atomically:

1. **Task 1: Freeze the contracts (Event, event_id, Adapter, decompression seam)** — `24286b7` (feat)
2. **Task 2: CaseStore — migrations, idempotent inserts, deterministic queries** — `eafbe15` (feat)
3. **Task 3: genericlog v0 + CLI wiring — walking skeleton GREEN** — `93bd475` (feat)

## Files Created/Modified

- `src/sift/models.py` — frozen `Event` dataclass + canonical `event_id()` (FROZEN, docstring records the contract)
- `src/sift/adapters/base.py` — `Adapter` Protocol, `ParseStats` (+coverage property), `open_bytes`, `read_head`, magic-byte constants
- `src/sift/adapters/__init__.py` — `REGISTRY`, `get()` with helpful KeyError, v0 `detect()` (signature stable for 01-04)
- `src/sift/adapters/genericlog.py` — `GenericLogAdapter` v0 with instance config attrs (`input_root`, `tz_overrides`, `last_stats`), `to_utc()`
- `src/sift/store.py` — `CaseStore`, `validate_case_name`, `case_db_path`, migration runner, STORE-02 pointer comment
- `src/sift/config.py` — `SiftConfig` (data_dir only this plan) + `load_config` (defaults → SIFT_DATA_DIR → flag overrides)
- `src/sift/cli.py` — real new/ingest/show bodies; later-phase stubs unchanged
- `tests/test_models.py` — golden value, hex shape, NUL disambiguation, frozen Event, gzip/zstd round-trips, coverage formula
- `tests/test_store.py` — migration, idempotency, ordering, ts round-trip, meta, rollback, case-name validation
- `tests/test_cli.py` — added `test_reingest_adds_zero_events`; walking-skeleton test now GREEN

## Decisions Made

- `CaseStore` uses sqlite3 autocommit mode (`isolation_level=None`) so all transaction boundaries are explicit — the migration runner and `transaction()` issue `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK` themselves
- `ingest` narrows the detected adapter with `assert isinstance(adapter, GenericLogAdapter)` — the frozen Protocol has no configuration attributes, and v0 `detect` only ever returns genericlog; plan 01-04 replaces this when the sniff algorithm lands
- TDD gates: orchestrator declared TDD_MODE off, so each task landed tests + implementation in one atomic commit instead of separate RED/GREEN commits

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] genericlog.py placeholder stub created in Task 1**
- **Found during:** Task 1 (adapter registry)
- **Issue:** The plan has Task 1 register "one GenericLogAdapter instance" in `adapters/__init__.py`, but `genericlog.py` is a Task 3 file — the registry could not import
- **Fix:** Minimal `GenericLogAdapter` stub (name + no-op sniff/parse) committed in Task 1; Task 3 replaced it with the real parser
- **Files modified:** src/sift/adapters/genericlog.py
- **Verification:** Task 1 gates green; Task 3 replaces the stub entirely
- **Committed in:** 24286b7 (stub), 93bd475 (real implementation)

**2. [Rule 2 - Missing critical] Terminal-escape sanitisation in `sift show`**
- **Found during:** Task 3 (show body)
- **Issue:** Log bytes are fully untrusted (plan trust boundary "log file bytes -> parser/store"); echoing raw message text lets hostile logs inject ANSI/control sequences into the operator's terminal (research Security Domain row)
- **Fix:** `_printable()` strips control characters (except tab) from rendered messages
- **Files modified:** src/sift/cli.py
- **Verification:** covered by full suite; one-line pure function
- **Committed in:** 93bd475

**3. [Rule 3 - Blocking] pyright-strict adjustments**
- **Found during:** Tasks 1 and 2
- **Issue:** `field(default_factory=list)` infers `list[Unknown]`; `@contextmanager` with `-> Iterator[None]` is flagged deprecated by pyright 1.1.411
- **Fix:** `default_factory=list[str]`; `transaction() -> Generator[None]`
- **Files modified:** src/sift/adapters/base.py, src/sift/store.py, src/sift/adapters/genericlog.py
- **Committed in:** 24286b7, eafbe15

---

**Total deviations:** 3 auto-fixed (2 × Rule 3 blocking, 1 × Rule 2 security). No scope creep; no architectural changes.

## Known Stubs

All intentional, each owned by a named future plan:

| Stub | File | Resolved by |
|------|------|-------------|
| `detect()` returns genericlog unconditionally | src/sift/adapters/__init__.py | plan 01-04 (INGST-03 sniff algorithm) |
| `SiftConfig` has only `data_dir`; no config.toml layer yet | src/sift/config.py | plan 01-04 (D-08 full precedence) |
| genericlog: ISO 8601 only; no syslog/epoch ladder, encodings, or per-event caps | src/sift/adapters/genericlog.py | plan 01-03 |
| `ingest` passes empty `tz_overrides`/`overrides` | src/sift/cli.py | plan 01-04 (config wiring) |
| analyze/report/eval/doctor exit 1 with arrival message | src/sift/cli.py | Phases 3-7 |

## Threat Flags

None — no new security surface beyond the plan's threat model. T-02-01 (case-name allowlist + path containment), T-02-02 (single SQL owner, `?` placeholders only) and T-02-03 (streaming parse, no slurp) all mitigated as specified; terminal-escape sanitisation added as an extra mitigation (deviation 2).

## Issues Encountered

None beyond the auto-fixed items above. All gates were green at each task boundary.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 01-03 (fixtures/hardening) can extend genericlog directly: the parse loop, ParseStats and D-06 grouping seams are in place
- Plan 01-04 replaces `detect()` v0 and extends `SiftConfig` — both signatures already match what it needs
- Contracts are frozen: any change to `Event`, `event_id` or the `Adapter` Protocol now requires a recorded decision + migration

## Self-Check: PASSED

All created files exist on disk; all three task commits (24286b7, eafbe15, 93bd475) present in git log.

---
*Phase: 01-skeleton-event-contract-genericlog-adapter*
*Completed: 2026-07-16*
