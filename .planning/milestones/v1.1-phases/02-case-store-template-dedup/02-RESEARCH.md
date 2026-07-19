# Phase 2: Case Store & Template Dedup - Research

**Researched:** 2026-07-16
**Domain:** SQLite schema evolution, deterministic template mining (regex masking), zstd storage compression, CLI progress/inspection — zero LLM dependency
**Confidence:** HIGH

## Summary

Phase 2 extends what already exists rather than building anew. Phase 1 shipped a working `CaseStore` with a `PRAGMA user_version` migration runner, explicit `BEGIN IMMEDIATE` transactions, `INSERT OR IGNORE` idempotency, and a CLI whose `show clusters` path is a deliberate stub. This phase adds exactly: migration 2 (a `template_groups` table + zstd compression of `raw` > 4 KB), a hand-rolled masking function in `pipeline/dedup.py` (locked by ADR 0003 — drain3 was explicitly rejected), streaming/batched ingest with progress feedback, `sift show clusters` and `--filter`, and a deterministic 100 MB synthetic-log generator with a perf acceptance test.

**No new dependencies are required.** `zstandard` 0.25.0 is already a core dependency (used for decompressing inputs in `adapters/base.py`); `rich` 15.0.0 is already installed transitively via Typer standard and its `rich.progress` import was verified in the project venv. `itertools.batched` is stdlib on Python 3.12. sqlite-vec is deliberately NOT added this phase — the vec0 virtual table cannot be created without knowing the embedding dimension (STORE-03, Phase 3), and the phase constraint forbids embedding dependencies.

The phase's biggest risk — the < 60 s / 100 MB budget — was empirically retired on this machine: a micro-benchmark of the Phase-2-specific stages (combined masking regex at 146 k lines/s, sha256 event IDs, dict aggregation, 15-column `executemany` insert) extrapolates to **~8.4 s for 1 M lines (100 MB)**. The remaining budget belongs to the Phase-1 genericlog parser, leaving a wide margin. The plan should therefore optimise for auditability, not speed.

**Primary recommendation:** Extend `store.py` with migration 2 and a streaming query; add `pipeline/dedup.py` with one compiled alternation regex; convert `cli.py` ingest to batched inserts with a `rich.progress` bar on stderr; recompute template groups from the store (not from the ingest stream) so dedup is idempotent and re-runnable.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Schema migration 2, zstd raw compression | `store.py` (storage) | — | Store owns ALL SQL and migrations (Phase 1 invariant, T-02-02) |
| Volatile-token masking + template grouping | `pipeline/dedup.py` (pipeline) | `store.py` persists results | SPEC §7 repo layout puts dedup in `pipeline/`; masking is pure logic, no SQL |
| `template_groups` persistence + streaming event query | `store.py` | — | Single reviewable SQL owner |
| `sift show clusters`, `--filter` parsing | `cli.py` (CLI) | `store.py` executes parameterised WHERE | CLI parses/validates filter keys; store never sees raw SQL fragments |
| Progress feedback (CLI-03) | `cli.py` | adapters expose `byte_offset` in `Event.attrs` | Rendering concern; adapters stay UI-free (frozen Protocol) |
| 100 MB synthetic generator + perf test | `tests/` | — | SPEC M2: "generator script included in tests"; never ships in `src/` |

## User Constraints

No `02-CONTEXT.md` exists (planning invoked with `--auto`). The binding constraints instead come from prior locked decisions:

### Locked decisions (ADRs, STATE.md, CLAUDE.md — treat as non-negotiable)
- **Hand-rolled regex masking, NOT drain3** — ADR `docs/decisions/0003-hand-rolled-masking-over-drain3.md` (D-02, SPEC §10). Deterministic, auditable, ~50 lines.
- **Store owns ALL SQL**; every statement parameterised with `?`; migrations are numbered functions run by the `PRAGMA user_version` runner in `store.py` (Phase 1, T-02-02/D-03).
- **CaseStore is autocommit** (`isolation_level=None`); all transactionality explicit via `BEGIN IMMEDIATE` (`transaction()` context manager).
- **Event dataclass and Adapter Protocol are FROZEN** — no new fields, no Protocol changes. Per-run config travels on adapter instances (01-02 pattern).
- **`_sanitise()` at render time only** — stored text stays verbatim; anything printed to the terminal (templates, exemplars, filter echoes) goes through it (T-04-01).
- **No LLM/embedding dependencies this phase** — Phase 3 owns sqlite-vec loading, chunks/vectors tables, and the embedding-dimension `meta` contract (STORE-03).
- **Boring tech only**; quality gate = `ruff check` + `pyright` (strict) + `pytest` clean per task.
- **British English** in user-facing strings; type hints everywhere.

### Claude's discretion
- Exact placeholder tokens (`<NUM>`, `<HEX>`, …), mask alternation details, exemplar count K, filter key set, progress-bar styling, generator log shape.

## Project Constraints (from CLAUDE.md)

- Pipeline stages live in `src/sift/pipeline/`; `store.py` owns migrations and tables; adding an adapter must require zero changes outside a new module + registration (dedup must not special-case adapters).
- Determinism: identical case + config → identical stored groups; `event_id` contract frozen.
- Nothing disappears silently — dedup must account for every event, including `severity="unknown"` ones.
- Zero network egress; tests never call the network (existing autouse socket guard stays green — rich/zstd are local-only).
- Config precedence flags > `SIFT_*` env > config.toml > defaults (any new knobs follow `SiftConfig`).
- Commands: `uv sync`, `uv run pytest`, `uv run ruff check`, `uv run pyright`, `uv run sift <subcommand>`.
- Record open-question decisions in `docs/decisions/`.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| STORE-01 | Single portable `case.db` per case; deleting the file deletes the case | Already true structurally (Phase 1: `data_dir/cases/<name>/case.db`). Phase 2 proves it at scale and adds the WAL-sidecar caveat (see Pitfall 4); acceptance test deletes the case directory and asserts nothing survives |
| STORE-02 | Schema migrations via `PRAGMA user_version`; `raw` > 4 KB zstd-compressed | Migration runner exists; add `_migration_2` (template_groups table + compress existing oversized `raw` rows). zstd API verified via Context7; TEXT/BLOB discrimination pattern below |
| STORE-04 | `sift show <case> events\|clusters [--filter …]` inspection before any AI | `show events` exists; add `show clusters` (renders template_groups) + allowlisted `--filter` keys mapped to parameterised WHERE in store.py |
| CLUS-01 | Template dedup masks numbers/hex/UUIDs/SIDs/paths/timestamps; groups with count, first/last seen, exemplars — no ML | `pipeline/dedup.py`: one compiled alternation regex (pattern below, benchmarked at 146 k lines/s); aggregation over a streaming store cursor; ≥ 90% reduction fixture |
| CLI-03 | Long operations show progress feedback | `rich.progress` (already installed via Typer) on stderr; batched inserts give within-file ticks via `Event.attrs["byte_offset"]`. Note: CLI-03 also covers embedding/generation progress — those arrive Phases 3–4; this phase completes the ingest leg and REQUIREMENTS.md should only be ticked if the project treats per-phase scope as sufficient (flag for verifier) |
</phase_requirements>

## Standard Stack

### Core (all already installed — zero new packages)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| stdlib `sqlite3` | Python 3.12+ | Migration 2, template_groups, filtered/streaming queries | Already the store backbone; WAL + `synchronous=NORMAL` + `executemany` already configured [VERIFIED: src/sift/store.py] |
| `zstandard` | 0.25.0 (locked in uv.lock) | Compress `raw` > 4 KB (STORE-02) | Already a core dep, already imported in `adapters/base.py` for input decompression [VERIFIED: uv.lock, .venv] |
| stdlib `re` | — | Masking regexes (CLUS-01) | ADR 0003 locks hand-rolled masking; single compiled VERBOSE alternation, `lastgroup` dispatch |
| stdlib `hashlib` | — | `template_id = sha256(template)[:16]` | Mirrors the frozen `event_id` idiom; deterministic |
| `rich` | 15.0.0 (transitive via typer) | `rich.progress` ingest bar (CLI-03) | Already in `.venv` — Typer standard pulls it; import verified in project venv [VERIFIED: .venv/site-packages, import test] |
| stdlib `itertools.batched` | Python 3.12 | Stream adapter events in insert batches (memory + progress ticks) | Stdlib since 3.12 — project floor [VERIFIED: python 3.12 stdlib] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| stdlib `random.Random(seed)` | — | Deterministic 100 MB synthetic-log generator | Tests only; seeded so the perf fixture is reproducible |
| pytest markers | pytest 9.x | `@pytest.mark.perf` for the 100 MB test | Keep the default suite fast; run perf explicitly for the M2 gate |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Recompute dedup from store cursor | Aggregate in-memory during the ingest stream | Streaming aggregation is slightly faster but silently diverges from stored truth when the input dir changed between ingests (deleted/failed files); recompute-from-store is idempotent and auditable — take it |
| TEXT/BLOB type discrimination for `raw` | Explicit `raw_zstd INTEGER` flag column | Flag column is more self-describing but needs a schema change + wider INSERT; SQLite type affinity guarantees BLOBs survive in a TEXT column, and `isinstance(value, bytes)` is unambiguous. Either is defensible; discrimination is the smaller diff |
| `rich.progress` | Hand-rolled `\r`-counter on stderr | rich is already installed, auto-disables on non-TTY, and handles resize/legacy terminals; hand-rolling saves nothing |
| `template TEXT` column on `events` (GROUP BY dedup in SQL) | Python-side aggregation | A stored template column goes stale when mask rules evolve (Phase 5 adds DSSErrors-specific masks); Python aggregation + `mask_version` in meta stays honest |

**Installation:** none. `uv sync` already provides everything.

**Version verification:** all packages already pinned in `uv.lock` and present in `.venv` (rich 15.0.0, zstandard 0.25.0) — confirmed by directory listing and import test in this session. [VERIFIED: local venv]

## Package Legitimacy Audit

**No new packages are installed in this phase.** All libraries used are stdlib, already-locked direct dependencies (zstandard — approved at the Phase 1 blocking-human legitimacy checkpoint), or already-installed transitive dependencies (rich, via typer).

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| *(none new)* | — | — | — | — | — | — |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
 input dir ──► adapters.detect ──► adapter.parse() ─┐  (Iterator[Event], lazy)
                                                    │
                          itertools.batched(…, 5000)│◄── rich.progress advances per batch
                                                    ▼    (byte_offset from Event.attrs)
                                       CaseStore.insert_events(batch)
                                       └─ raw > 4 KB ? zstd BLOB : TEXT
                                                    │  (one BEGIN IMMEDIATE around whole ingest)
                                                    ▼
                                              events table
                                                    │
              after ingest commit:  dedup.rebuild_template_groups(store)
                                                    │
             store.iter_event_summaries() ──► mask(message) ──► dict aggregation
             (event_id, ts, severity, message       │            template → count, first/last ts,
              — no raw, no decompression)           ▼            severity_max, exemplar ids (first K)
                                          template_groups table  + meta.mask_version
                                                    │
        sift show <case> clusters [--filter …] ◄────┘   (render via _sanitise)
        sift show <case> events   [--filter …] ◄── parameterised WHERE from allowlisted keys
```

Trace of the primary use case: `sift ingest big-case` → files stream through the adapter → events land in batches (progress bar advances) → after commit, dedup rebuilds `template_groups` from the store → `sift show big-case clusters` prints groups sorted by count.

### Recommended Project Structure

```
src/sift/
├── store.py             # + _migration_2, compress/decompress helpers, iter_event_summaries,
│                        #   filtered queries, replace_template_groups, query_template_groups
├── pipeline/
│   ├── __init__.py      # NEW package
│   └── dedup.py         # NEW: MASK regex, mask(), MASK_VERSION, rebuild_template_groups()
├── cli.py               # ingest: batched streaming + progress; show: clusters + --filter
└── models.py            # UNCHANGED (frozen)
tests/
├── test_dedup.py        # NEW: mask unit tests, ≥90% reduction fixture, determinism
├── test_store.py        # extend: migration 2, zstd round-trip, TEXT/BLOB, filters
├── test_cli.py          # extend: show clusters, --filter, progress-on-non-TTY
└── perf/
    ├── generate_synthetic.py   # NEW: seeded 100 MB generator (importable + runnable)
    └── test_perf_ingest.py     # NEW: @pytest.mark.perf, <60 s gate
```

### Pattern 1: Migration 2 — additive table + in-place raw compression

**What:** One new numbered migration in the existing `_MIGRATIONS` dict; the runner already handles ordering, transactions, and rollback.
**When to use:** Every schema change, this phase and after.

```python
# Source: existing src/sift/store.py migration runner (Phase 1) — extend, don't rebuild
_RAW_ZSTD_THRESHOLD = 4096  # bytes of UTF-8, per STORE-02 / SPEC §5.3

def _migration_2(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE template_groups (
            template_id  TEXT PRIMARY KEY,      -- sha256(template)[:16]
            template     TEXT NOT NULL UNIQUE,  -- masked message
            count        INTEGER NOT NULL,
            first_ts     TEXT,                  -- ISO 8601, NULL if all ts missing
            last_ts      TEXT,
            severity_max TEXT NOT NULL,
            exemplar_event_ids TEXT NOT NULL    -- JSON array, first K in deterministic order
        )
        """
    )
    # Compress existing Phase-1 rows in place (dev-local cases only exist so far).
    cctx = zstandard.ZstdCompressor()  # level defaults to 3; no threads= (determinism)
    rows = conn.execute(
        "SELECT event_id, raw FROM events WHERE length(CAST(raw AS BLOB)) > ?",
        (_RAW_ZSTD_THRESHOLD,),
    ).fetchall()
    for event_id, raw in rows:
        if isinstance(raw, str):
            conn.execute(
                "UPDATE events SET raw = ? WHERE event_id = ?",
                (cctx.compress(raw.encode("utf-8")), event_id),
            )
```

**Key facts:**
- SQLite type affinity: a BLOB stored into a TEXT-affinity column is kept as a BLOB, unchanged — the discrimination `isinstance(value, bytes)` on read is reliable. [CITED: sqlite.org/datatype3.html — "no attempt is made to convert BLOB content"]
- `ZstdCompressor(level=3)` is the constructor default; `write_content_size` defaults True, so `ZstdDecompressor().decompress(frame)` works one-shot. [VERIFIED: Context7 /indygreg/python-zstandard]
- Do NOT pass `threads=` — keep single-threaded compression so frames are deterministic per library version. [ASSUMED — Context7 doc text on `threads=0` semantics is ambiguous; omitting the parameter sidesteps the question entirely]
- Cap decompression: `dctx.decompress(blob, max_output_size=128 * 2**20)` guards against a tampered `case.db` carrying a zstd bomb (a shared case file is untrusted input). [VERIFIED: Context7 — decompress supports max_output_size]

### Pattern 2: One compiled alternation regex for masking (CLUS-01)

**What:** Single `re.VERBOSE` alternation with named groups, most-specific-first; `m.lastgroup` dispatches to the placeholder. One pass, no backtracking blowup, deterministic.
**When to use:** `pipeline/dedup.py` — the ONLY place mask rules live. Bump `MASK_VERSION` whenever rules change.

```python
# Source: benchmarked in this session at 146k lines/s in the project venv
MASK_VERSION = 1

_MASK = re.compile(
    r"""
    (?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)
  | (?P<uuid>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})
  | (?P<hex>0[xX][0-9a-fA-F]+|\b[0-9a-fA-F]{8,}\b)      # SIDs (32-hex) fall in here too
  | (?P<path>(?:/[\w.\-]+){2,}|(?:[A-Za-z]:)?(?:\\[\w.\-]+){2,})
  | (?P<num>\b\d+\b)
    """,
    re.VERBOSE,
)
_PLACEHOLDER = {"ts": "<TS>", "uuid": "<UUID>", "hex": "<HEX>", "path": "<PATH>", "num": "<NUM>"}

def mask(message: str) -> str:
    """Deterministic volatile-token masking (CLUS-01). No ML, no state."""
    return _MASK.sub(lambda m: _PLACEHOLDER[m.lastgroup], message)  # type: ignore[index]
```

**Ordering rationale:** timestamps before numbers (else `2026-07-16` shatters into `<NUM>-<NUM>-<NUM>`); UUID before hex (else the 8-hex prefix wins); hex before num (else `0x1A2B` splits). MSTR SIDs (32-char hex) and OIDs are covered by the `hex` alternative in this phase; DSSErrors-specific placeholders (`<SID>`, `<OID>`) can be added in Phase 5 with a `MASK_VERSION` bump — the recompute-from-store design makes that a cheap re-run, not a migration. IPv4 addresses degrade to `<NUM>.<NUM>.<NUM>.<NUM>` — consistent, hence groupable; a dedicated `<IP>` alternative is discretionary polish.

**ReDoS safety:** every alternative is a linear scan (no nested quantifiers, no overlapping optional groups). Hostile log content cannot trigger catastrophic backtracking. Mask only `message`, never `raw`.

### Pattern 3: Recompute-from-store dedup (idempotent, re-runnable)

**What:** After the ingest transaction commits, stream `(event_id, ts, severity, message)` from the store — deliberately excluding `raw`, so nothing is decompressed — mask each message, aggregate into `template → (count, first_ts, last_ts, severity_max, first-K exemplar ids)`, then `DELETE FROM template_groups` + insert fresh rows inside one transaction, writing `mask_version` to `meta`.

**Why this shape:**
- Groups always reflect the store's actual contents, not what happened to stream past this run (a re-ingest after a file failure, or with files removed from the input dir, still produces correct groups).
- Re-runnable when mask rules change: compare `meta.mask_version` and rebuild.
- Aggregation over 1 M events benchmarked at ~0.05 s; the store read of four small columns is a few seconds at worst — irrelevant to the 60 s budget. [VERIFIED: micro-benchmark this session]

**Deterministic ordering:** stream events in the store's canonical order (`ORDER BY ts IS NULL, ts, source_file, line_start` — already the Phase 1 idiom), so exemplar ids and first/last timestamps are byte-stable across runs. Sort group output by `(count DESC, template)` for stable `show clusters` rendering.

**severity_max:** define an explicit ordering `fatal > error > warn > info > debug > unknown` as a module-level dict — do not rely on string comparison.

### Pattern 4: Batched streaming ingest with progress (CLI-03)

**What:** Replace `events = list(adapter.parse(...))` in `cli.py` with `for batch in itertools.batched(adapter.parse(path, case), 5000): store.insert_events(batch)` inside the existing single transaction, advancing a `rich.progress` bar after each batch.

```python
# Source: rich.progress import verified in project venv; API stable across rich majors
from rich.console import Console
from rich.progress import Progress, BarColumn, DownloadColumn, TimeElapsedColumn

console = Console(stderr=True)   # keep stdout scriptable/clean
with Progress(..., console=console, transient=True) as progress:
    task = progress.add_task("ingest", total=total_input_bytes)
    ...
    # after each batch: advance using the last event's byte_offset
    offset = int(batch[-1].attrs.get("byte_offset", "0")) + int(batch[-1].attrs.get("byte_len", "0"))
    progress.update(task, completed=file_base + offset)
```

**Key facts:**
- `genericlog` already exposes `byte_offset`/`byte_len` in `Event.attrs` (Phase 1, deliberately for mechanical checking) — within-file progress is free. For adapters that don't expose it, fall back to advancing by file size on completion.
- `total` = sum of on-disk file sizes (compressed size for `.gz`/`.zst` — offsets are decompressed-stream offsets, so per-file fallback to "advance whole file on completion" for compressed inputs is the honest simple choice; a mismatch merely makes the bar approximate).
- Rich auto-disables live rendering on non-TTY, so existing `CliRunner` tests keep passing; writing to **stderr** keeps the existing stdout assertions (`coverage`, `N events`) untouched. [ASSUMED — rich non-TTY behaviour from training; risk is trivial because the existing test suite will catch any stdout contamination immediately]
- Batching also bounds memory: a 100 MB single file no longer materialises ~1 M `Event` objects at once.

### Pattern 5: Allowlisted `--filter` → parameterised WHERE (STORE-04)

**What:** `sift show <case> events|clusters [--filter key=value]...`. CLI parses `key=value` (reuse the last-`=`-split idiom from `parse_adapter_overrides`), validates keys against a per-target allowlist, and passes a typed dict to store query methods, which build `WHERE` from fixed snippets with `?` params.

Recommended minimal key set (discretionary, keep small):
- events: `severity=error`, `source=genericlog`, `file=<substring>`, `since=<ISO>`, `until=<ISO>`, `limit=<N>`
- clusters: `severity=<max-severity>`, `min-count=<N>`, `contains=<substring of template>`, `limit=<N>`

Unknown key → exit 2 listing valid keys (mirrors the unknown-adapter error shape). Values are never interpolated into SQL — snippets like `"severity = ?"` are chosen from a dict keyed by the allowlisted name. `show` output goes through `_sanitise` (templates and exemplar text contain hostile log bytes).

**Streaming `show events`:** with 1 M events, `query_events()`'s `fetchall()` + full-`Event` hydration (including zstd decompression of `raw`) is the wrong tool for rendering a listing. Add an iterator-based, column-scoped query for `show` (message column only, no `raw`), leaving `query_events()` for callers that need full events.

### Anti-Patterns to Avoid

- **Creating `chunks`/`vectors`/`clusters` (semantic) tables now "to be ready":** the vec0 table needs the embedding dimension (unknown until Phase 3's doctor round-trip), and empty speculative tables are schema debt. Migration 3 in Phase 3 is the right home. `sift show clusters` reads `template_groups` until semantic clusters exist (SPEC M2: "lists template groups pre-embedding").
- **Storing the masked template as a column on `events`:** goes stale when mask rules evolve (Phase 5 domain masks); recompute-from-store + `mask_version` stays honest.
- **Per-event `INSERT` or per-batch transactions:** the Phase 1 single-`BEGIN IMMEDIATE`-per-ingest already gives all-or-nothing semantics and speed; keep it, commit once.
- **Masking `raw`:** only `message` is templated; `raw` is verbatim citation evidence.
- **`f-string` SQL anywhere outside the module-constant column list:** store owns SQL, values are always `?`.
- **Progress output on stdout:** breaks scriptability and existing test assertions; stderr only.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| zstd framing | Custom compression flags/containers | `zstandard.ZstdCompressor/ZstdDecompressor` (already a dep) | Frame carries magic + content size; battle-tested C library |
| Progress rendering | `\r` cursor tricks, TTY detection, resize handling | `rich.progress` (already installed) | Non-TTY auto-disable, width handling, zero new deps |
| Event batching | Manual chunking loops | `itertools.batched` (stdlib 3.12) | Exact stdlib fit for the project floor |
| Template mining | drain3 or any learned miner | Hand-rolled regex masking | **Inverted case:** ADR 0003 locks hand-rolling here — drain3 is dormant (≤ 3.11) and non-deterministic; ~50 auditable lines beat a dead dependency |
| SQL filtering | String-assembled WHERE clauses | Allowlisted snippets + `?` params in store.py | Injection surface, and Phase 1 review culture demands it |

**Key insight:** everything this phase needs is already in the dependency tree. The only genuinely new logic is ~50 lines of masking + ~80 lines of aggregation/persistence — keep it that small.

## Common Pitfalls

### Pitfall 1: Mask alternation order silently wrong
**What goes wrong:** `<NUM>` fires inside timestamps/hex; UUIDs shatter; groups multiply instead of collapsing, and the ≥ 90% reduction gate fails confusingly.
**Why it happens:** Python's `re` alternation is first-match-wins at each position.
**How to avoid:** most-specific-first order (ts → uuid → hex → path → num); unit-test each token class AND compound lines ("timestamp containing numbers", "path containing hex").
**Warning signs:** distinct-template count far above the number of distinct log formats in the fixture.

### Pitfall 2: zstd BLOB leaks into rendering or hashing
**What goes wrong:** `show`/report code prints `b'(\xb5/\xfd...'` or a `TypeError`, or a future determinism hash covers compressed bytes (level-dependent).
**Why it happens:** the TEXT/BLOB discrimination lives in one read helper; any query that selects `raw` without it bypasses decompression.
**How to avoid:** a single private `_decode_raw(value) -> str` in store.py used by every reader; property-style test: insert 5 KB raw → `typeof(raw) == 'blob'` in SQL AND `query_events()` returns the original string; insert 1 KB raw → `'text'`.
**Warning signs:** any `SELECT ... raw` outside store.py.

### Pitfall 3: Threshold measured in characters, not bytes
**What goes wrong:** a 4,000-character message with multibyte characters exceeds 4 KB encoded but is stored uncompressed (or vice versa), making the "> 4 KB" contract untestable.
**How to avoid:** compare `len(raw.encode("utf-8")) > 4096`; the migration's SQL predicate uses `length(CAST(raw AS BLOB))` for the same semantics.
**Warning signs:** boundary tests at 4096/4097 encoded bytes disagreeing between insert path and migration path.

### Pitfall 4: "Deleting the file deletes the case" vs WAL sidecars
**What goes wrong:** deleting only `case.db` while `-wal`/`-shm` exist (crash, or another handle open) leaves orphans; recreating a case with the same name could even replay a stale WAL.
**Why it happens:** Phase 1 enabled `journal_mode=WAL`; sidecars are checkpointed away only on clean close.
**How to avoid:** the deletable unit is `data_dir/cases/<name>/` (the directory) — one line in `--help`/docs; acceptance test removes the directory. `store.close()` already checkpoints on clean exit.
**Warning signs:** `case.db-wal` present after a completed CLI command (would also indicate an unclosed store).

### Pitfall 5: Perf test flakes the default suite
**What goes wrong:** a 100 MB generate+ingest test (~15–30 s plus generation I/O) runs on every `uv run pytest`, blowing the fast feedback loop, or flakes on slower CI.
**How to avoid:** mark `@pytest.mark.perf`, register the marker, exclude via `addopts = "-m 'not perf'"` (and run `uv run pytest -m perf` explicitly for the M2 gate). Assert a generous bound (< 60 s is the contract; the measured headroom is ~7×). Generate into `tmp_path`, never commit the artefact.
**Warning signs:** default suite runtime jumping from seconds to minutes.

### Pitfall 6: Dedup double-counts or under-counts on re-ingest
**What goes wrong:** aggregating during the ingest stream counts events the store rejected as duplicates (`INSERT OR IGNORE`), or misses events from files no longer in the input dir.
**How to avoid:** recompute from the store after commit (Pattern 3). Test: ingest twice → identical `template_groups` rows both times.
**Warning signs:** group counts ≠ `SELECT count(*) FROM events` totals per template.

### Pitfall 7: Migration 2 runs against a mid-ingest Phase 1 database
**What goes wrong:** none today (migrations run at `CaseStore.__init__`, before any ingest), but the in-migration UPDATE loop assumes `events` rows exist and are TEXT. A Phase-1-created dev case reopened with Phase 2 code must round-trip.
**How to avoid:** test fixture: build a v1-schema db (run only `_migration_1`, insert an event with 5 KB raw), reopen with the full store → assert user_version==2, raw readable, blob-typed.

## Code Examples

### zstd round-trip helpers (store.py)

```python
# Source: Context7 /indygreg/python-zstandard (compress API, defaults) — verified this session
import zstandard

_RAW_ZSTD_THRESHOLD = 4096
_MAX_RAW_BYTES = 128 * 2**20  # zstd-bomb cap for tampered case files
_CCTX = zstandard.ZstdCompressor()          # level=3 default; single-threaded
_DCTX = zstandard.ZstdDecompressor()

def _encode_raw(raw: str) -> str | bytes:
    data = raw.encode("utf-8")
    return _CCTX.compress(data) if len(data) > _RAW_ZSTD_THRESHOLD else raw

def _decode_raw(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return _DCTX.decompress(value, max_output_size=_MAX_RAW_BYTES).decode("utf-8")
    return value
```

### Deterministic synthetic generator sketch (tests/perf/generate_synthetic.py)

```python
# Seeded, importable, and runnable (python tests/perf/generate_synthetic.py out.log 100)
import random

TEMPLATES = [
    "ERROR [Thread-{t}] MCM contract 0x{h:08x} denied for session {s:032x} at /opt/app/log{n}.log",
    "WARN  connection pool exhausted after {n} retries (peer 10.0.{a}.{b}:{p})",
    "INFO  request {u} completed in {ms} ms",
    # ... ~20 templates -> after masking, distinct groups ≈ len(TEMPLATES): >90% reduction guaranteed
]

def generate(path, target_mb: int, seed: int = 42) -> None:
    rng = random.Random(seed)
    ...  # write ISO-timestamped lines cycling templates with rng-filled volatile tokens
```
The ≥ 90%-reduction fixture is the same generator at ~1 MB; the reduction assertion is `distinct_templates / event_count <= 0.10` — trivially true when volatile tokens are the only variation.

### Benchmark grounding the 60 s budget (run this session, project venv, this machine)

```text
lines=200000  distinct_templates=1
mask     1.37s  (146,424/s)   sha256 0.06s   agg 0.01s   insert 0.25s
total    1.68s  -> x5 scale (1M lines / ~100MB): 8.4s      [VERIFIED: local micro-benchmark]
```
The unmeasured remainder is the Phase 1 genericlog parse loop (regex ladder with per-file lock-in fast path). Even at a pessimistic 3× the masking cost, total stays under 30 s. Plan a profiling escape hatch (e.g. run the perf test once early in the phase), not a performance rewrite.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| drain3 template mining | Hand-rolled deterministic masking | ADR 0003 (Phase 1) | Locked; no ML, auditable, tunable per adapter |
| `list()`-materialised ingest | `itertools.batched` streaming | This phase | Bounded memory + progress ticks |
| `raw` plain TEXT | TEXT/BLOB with zstd > 4 KB | Migration 2 (this phase) | STORE-02; transparent via `_decode_raw` |
| stdlib `compression.zstd` | `zstandard` package | Until Python floor reaches 3.14 | Documented future deletion [CITED: .claude/CLAUDE.md stack validation] |

**Deprecated/outdated:** nothing new; sqlite3 datetime adapters remain avoided (explicit ISO strings, Phase 1 decision).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `zstandard` default constructor (no `threads=`) produces deterministic frames per library version | Pattern 1 / zstd helpers | Low — determinism contract (REPT-03) covers report JSON, not db bytes; frames only need to round-trip |
| A2 | rich `Progress` is a no-op-safe on non-TTY and stderr routing keeps CliRunner stdout assertions green | Pattern 4 | Trivial — existing test suite fails loudly on first run if wrong; fallback is a plain stderr counter |
| A3 | SQLite TEXT-affinity column preserves BLOBs unmodified | Pattern 1 | Low — cited from sqlite.org datatype3; covered by the `typeof(raw)` test either way |
| A4 | Phase-1 genericlog parse throughput leaves the 60 s budget intact (only Phase-2 stages were benchmarked) | Benchmark | Medium — mitigate by running the perf test in the FIRST plan wave, not the last |

## Open Questions (RESOLVED)

1. **Does ticking CLI-03 in REQUIREMENTS.md require embedding/generation progress too?**
   - What we know: CLI-03 text covers "ingest, embedding, generation"; this phase can only deliver the ingest leg.
   - Recommendation: implement ingest progress here; leave CLI-03 unticked in REQUIREMENTS.md (or tick with a note) and finish it in Phase 3/4 — verifier should confirm the intended convention.
   - RESOLVED: ingest-leg scope only this phase (plan 02-02). Tick CLI-03 with a partial-scope note — embedding/generation progress arrive in Phases 3–4.
2. **Should `show clusters` gain `--filter` parity now or minimal keys?**
   - What we know: SPEC shows `[--filter …]` without specification; STORE-04 only demands inspectability.
   - Recommendation: ship the small allowlist above; more keys are cheap follow-ups. Record the filter grammar in `--help`.
   - RESOLVED: minimal allowlisted key set adopted (plan 02-03); the grammar is recorded in `sift show --help`.
3. **Where does dedup re-run when `mask_version` changes?**
   - Recommendation: `sift ingest` compares `meta.mask_version` and rebuilds groups when stale — no new subcommand needed in v1.
   - RESOLVED: mooted — `rebuild_template_groups` runs unconditionally on every ingest (plan 02-01), so groups can never be stale; no staleness check needed.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | everything | ✓ | 3.12+ (project venv) | — |
| uv | build/test | ✓ | in use since Phase 1 | — |
| sqlite3 (stdlib) | store | ✓ | Fedora python3 | — |
| zstandard | STORE-02 | ✓ | 0.25.0 in .venv | — |
| rich (via typer) | CLI-03 | ✓ | 15.0.0 in .venv, import verified | plain stderr counter |
| ~100 MB tmp disk + time budget | perf test | ✓ | benchmark ran in venv this session | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 (locked), with autouse XDG redirect + socket guard from Phase 1 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (testpaths=tests) |
| Quick run command | `uv run pytest -x -q` |
| Full suite command | `uv run pytest && uv run ruff check && uv run pyright` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| STORE-01 | delete case dir ⇒ case gone; single-file portability | integration | `uv run pytest tests/test_cli.py -k portable -x` | ❌ Wave 0 (extend test_cli.py) |
| STORE-02 | migration 1→2; zstd >4 KB round-trip; `typeof(raw)` blob/text; v1-db upgrade | unit | `uv run pytest tests/test_store.py -k "migration or zstd" -x` | ❌ Wave 0 (extend test_store.py) |
| STORE-04 | `show clusters` lists groups; `--filter` allowlist + rejection; sanitised output | integration | `uv run pytest tests/test_cli.py -k "show_clusters or filter" -x` | ❌ Wave 0 |
| CLUS-01 | mask token classes; ≥90% reduction; determinism across two runs; count/first/last/exemplars correct | unit | `uv run pytest tests/test_dedup.py -x` | ❌ Wave 0 (`tests/test_dedup.py`) |
| CLI-03 | progress on stderr, stdout unchanged, non-TTY safe | integration | `uv run pytest tests/test_cli.py -k progress -x` | ❌ Wave 0 |
| M2 gate | 100 MB < 60 s + one portable file | perf (marked) | `uv run pytest -m perf` | ❌ Wave 0 (`tests/perf/`) |

### Sampling Rate
- **Per task commit:** `uv run pytest -x -q && uv run ruff check && uv run pyright` (Phase 1 convention: gate green before every commit)
- **Per wave merge:** full suite command above
- **Phase gate:** full suite + `uv run pytest -m perf` green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_dedup.py` — covers CLUS-01
- [ ] `tests/perf/generate_synthetic.py` + `tests/perf/test_perf_ingest.py` — covers M2 timing gate (register `perf` marker, exclude via addopts)
- [ ] extensions to `tests/test_store.py` (migration 2, zstd) and `tests/test_cli.py` (show clusters, filters, progress, portability)
- Framework install: none — pytest configured and green (108 tests) since Phase 1

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | local single-user CLI |
| V3 Session Management | no | — |
| V4 Access Control | partial | existing `validate_case_name` allowlist + containment check (Phase 1) — reuse, don't duplicate |
| V5 Input Validation | yes | `--filter` key allowlist → fixed SQL snippets + `?` params; last-`=` split parsing; exit 2 on unknown keys |
| V6 Cryptography | no (hashing only) | sha256 for identity, not secrecy — stdlib hashlib |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via `--filter` values | Tampering | Values only ever bound via `?`; snippets chosen from an allowlist dict in store.py (single SQL owner) |
| Terminal injection via templates/exemplars in `show clusters` | Tampering/Spoofing | Route ALL rendered text through existing `_sanitise` (T-04-01 precedent — this bit Phase 1's code review) |
| zstd decompression bomb in a shared/tampered `case.db` | DoS | `decompress(..., max_output_size=128 MiB)` cap |
| ReDoS via hostile log lines against mask regex | DoS | Linear alternatives only (no nested quantifiers); add a pathological-input test (e.g. 64 KB of `a` + digits) |
| Resource exhaustion: 1 M events materialised in RAM | DoS | `itertools.batched` streaming ingest; column-scoped streaming query for `show` |
| Path traversal via case name | Tampering | Already mitigated (`validate_case_name`, containment assert) — no new surface this phase |

Per project policy, the phase closes with a `gsd-secure-phase` audit and a `02-SECURITY.md`.

## Sources

### Primary (HIGH confidence)
- Local codebase: `src/sift/store.py`, `cli.py`, `models.py`, `adapters/base.py`, `pyproject.toml`, `uv.lock`, `.venv` contents — read/verified this session
- Local micro-benchmark (mask/sha/agg/insert throughput; rich import) — run in the project venv this session
- SPEC.md §5.1–5.4, §5.8, §8 (M2) — authoritative specification

### Secondary (MEDIUM confidence)
- Context7 `/indygreg/python-zstandard` — ZstdCompressor defaults, one-shot compress, frame content size, max_output_size (digest cached via research-store, key `2769ae04…`)
- `.claude/CLAUDE.md` Validation Findings (Phase 1 research): zstandard binding choice, drain3 rejection, sqlite-vec deferral rationale
- sqlite.org/datatype3.html — BLOB-in-TEXT-affinity preservation [CITED]

### Tertiary (LOW confidence)
- rich non-TTY auto-disable behaviour (training knowledge; A2 — trivially falsified by the test suite)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new packages; everything verified installed and imported locally
- Architecture: HIGH — extends frozen Phase 1 contracts; SPEC prescribes the shapes
- Performance: HIGH for Phase-2 stages (measured), MEDIUM end-to-end (A4 — parser leg unmeasured; run perf test early)
- Pitfalls: HIGH — derived from this codebase's own invariants and Phase 1 review findings

**Research date:** 2026-07-16
**Valid until:** 2026-08-15 (stable stdlib/local domain; nothing fast-moving)
