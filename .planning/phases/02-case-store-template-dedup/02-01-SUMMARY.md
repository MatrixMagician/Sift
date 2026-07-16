---
phase: 02-case-store-template-dedup
plan: 01
subsystem: store-pipeline
tags: [sqlite, zstd, dedup, masking, clusters]

requires:
  - Phase 1 CaseStore (PRAGMA user_version migration runner, BEGIN IMMEDIATE transactions)
  - Phase 1 CLI (new/ingest/show, _sanitise, _case_store)
provides:
  - Schema v2: template_groups table + in-place zstd compression of oversized raw (migration 2)
  - Transparent zstd for raw > 4096 UTF-8 encoded bytes (_encode_raw/_decode_raw, 128 MiB bomb cap)
  - src/sift/pipeline/dedup.py — deterministic masking, MASK_VERSION, rebuild_template_groups
  - "`sift show <case> clusters` renders template groups; ingest prints `Template groups: N`"
affects: [02-02, 02-03, phase-03-embedding, phase-05-domain-adapters]

tech-stack:
  added: []
  patterns:
    - "Single compiled re.VERBOSE alternation with named groups, most-specific-first (ts->uuid->hex->path->num); m.lastgroup dispatch"
    - "Recompute-from-store dedup: rebuild_template_groups runs unconditionally after every ingest commit (idempotent, Pitfall 6)"
    - "_decode_raw is the SINGLE read path for raw; no other method selects raw (Pitfall 2)"
    - "Pipeline modules are typer-free, print-free, SQL-free — persistence exclusively through CaseStore methods"

key-files:
  created:
    - src/sift/pipeline/__init__.py
    - src/sift/pipeline/dedup.py
    - tests/test_dedup.py
  modified:
    - src/sift/store.py
    - src/sift/cli.py
    - tests/test_store.py
    - tests/test_cli.py

key-decisions:
  - "Mask placeholder vocabulary frozen: <TS> <UUID> <HEX> <PATH> <NUM>; 32-hex SIDs land in <HEX> until Phase 5 adds domain masks with a MASK_VERSION bump"
  - "EXEMPLAR_K = 5 exemplar event ids per group, first K in canonical store order"
  - "template_id = sha256(template)[:16], mirroring the frozen event_id idiom"
  - "zstd compressor uses constructor defaults (level 3, single-threaded, no threads=) for deterministic frames"
  - "severity_max via explicit rank dict fatal>error>warn>info>debug>unknown — never lexicographic"
  - "RED phase used importlib indirection + strict xfail so pyright/collection stayed green while sift.pipeline.dedup did not exist; task 3 normalised to direct imports"

patterns-established:
  - "New migrations are numbered functions in _MIGRATIONS run by the existing BEGIN IMMEDIATE runner; severity CHECK vocabulary reused for severity_max"
  - "_TEMPLATE_GROUP_COLUMNS module constant mirrors _EVENT_COLUMNS; all values ?-bound (T-02-04)"

requirements-completed: [STORE-02, CLUS-01, STORE-04]

metrics:
  duration: ~14min
  completed: 2026-07-16
  tasks: 3
  tests-before: 108
  tests-after: 132

status: complete
---

# Phase 2 Plan 01: Case Store v2 & Template Dedup Slice Summary

Deterministic hand-rolled masking collapses ingested logs into template_groups (schema v2 via migration 2, raw > 4 KB transparently zstd-compressed), inspectable with `sift show <case> clusters` — zero LLM dependency.

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | RED — failing tests (strict xfail) | 93b3db8 | tests/test_dedup.py (new), tests/test_store.py, tests/test_cli.py |
| 2 | Store v2 — migration 2, zstd, template groups | 4ade286 | src/sift/store.py, tests/test_store.py |
| 3 | Dedup pipeline + CLI wiring GREEN | e0f33d0 | src/sift/pipeline/*, src/sift/cli.py, tests/test_dedup.py, tests/test_cli.py |

## Contracts for plans 02-02 / 02-03

**New store API (src/sift/store.py):**

```python
_RAW_ZSTD_THRESHOLD = 4096            # UTF-8 encoded bytes (STORE-02)
_MAX_RAW_BYTES = 128 * 2**20          # zstd-bomb cap (T-02-01)
def _encode_raw(raw: str) -> str | bytes
def _decode_raw(value: str | bytes) -> str      # SINGLE raw read path
def _migration_2(conn: sqlite3.Connection) -> None   # _MIGRATIONS[2]

@dataclass(frozen=True)
class TemplateGroup:
    template_id: str; template: str; count: int
    first_ts: str | None; last_ts: str | None
    severity_max: str; exemplar_event_ids: list[str]

CaseStore.iter_event_summaries() -> Iterator[tuple[str, str | None, str, str]]
    # (event_id, ts, severity, message), canonical order, cursor-streamed, no raw
CaseStore.replace_template_groups(groups)   # caller owns the transaction
CaseStore.query_template_groups()           # ORDER BY count DESC, template ASC
```

**Dedup API (src/sift/pipeline/dedup.py):**

```python
MASK_VERSION = 1        # persisted to meta key "mask_version" on every rebuild
EXEMPLAR_K = 5
def mask(message: str) -> str          # placeholders: <TS> <UUID> <HEX> <PATH> <NUM>
def template_id(template: str) -> str  # sha256(template)[:16]
def rebuild_template_groups(store: CaseStore) -> int  # returns group count
```

**CLI stdout contracts:**

- ingest prints exactly `Template groups: {n}` on its own line, after `Total: N new events`.
- `show clusters` per group:
  `{template_id}  {count:>7}  {severity_max:<7}  {first_ts or '-'}  {last_ts or '-'}  {template}`
  (template through `_sanitise`, newlines flattened, truncated to 100 chars), followed by
  `    exemplars: {space-joined event ids}`. Empty table renders nothing, exit 0.

## Verification

- Full gate green: `uv run pytest` (132 passed, 0 xfailed/xpassed), `uv run ruff check`, `uv run pyright` (strict) all exit 0
- Reduction gate: seeded fixture (random.Random(42), 21 shapes x 200 lines) yields 21 groups / 4,200 events = 0.005 <= 0.10
- Migration gate: fresh store and v1-built store both reach `PRAGMA user_version` 2; 5,000-byte raw compressed in place (`typeof(raw) == 'blob'`) and round-trips
- Boundary: 0 / 4096 encoded bytes stay TEXT, 4097 becomes BLOB; multibyte string (2,500 chars, 5,000 bytes) compressed — threshold counts encoded bytes
- Accounting: sum of group counts equals events row count, severity='unknown' rows included
- ReDoS: 64 KiB pathological line masks in well under a second

## Deviations from Plan

None - plan executed exactly as written. (One mechanical adjustment: the Phase 1 test
`test_fresh_store_applies_migration_1` asserted `user_version == 1`, which migration 2
necessarily changes; the version assertion moved to `test_fresh_store_reaches_user_version_2`
and the old test now checks only the migration-1 tables.)

## Known Stubs

None. `show hypotheses`, `analyze`, `report`, `eval`, `doctor` remain Phase 1 arrival stubs by design (later phases).

## Threat Flags

None — all new surface was in the plan's threat model (T-02-01 zstd cap, T-02-02 sanitised rendering, T-02-03 linear regex, T-02-04 ?-bound SQL); no new network endpoints or trust boundaries.

## Self-Check: PASSED

All created files exist on disk; commits 93b3db8, 4ade286, e0f33d0 present in git log; full gate re-verified green (132 passed, ruff, pyright).
