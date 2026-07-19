# Phase 2: Case Store & Template Dedup - Pattern Map

**Mapped:** 2026-07-16
**Files analyzed:** 9 (4 modified, 5 new)
**Analogs found:** 8 / 9

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/sift/store.py` (extend: migration 2, zstd helpers, iter/filter queries, template_groups) | store/model | CRUD | `src/sift/store.py` itself (Phase 1 code) | exact |
| `src/sift/pipeline/__init__.py` (NEW, empty package) | config | — | `src/sift/adapters/__init__.py` (package init) | role-match |
| `src/sift/pipeline/dedup.py` (NEW) | service/utility | batch transform | `src/sift/models.py` (`event_id` hashing idiom) + `src/sift/adapters/__init__.py` (pure-logic, typer-free module) | role-match |
| `src/sift/cli.py` (extend: batched ingest + progress, `show clusters`, `--filter`) | controller (CLI) | request-response | `src/sift/cli.py` itself (`ingest`, `show`, `new`) | exact |
| `tests/test_dedup.py` (NEW) | test | batch | `tests/test_store.py` (`_ev` factory, tmp_path stores) | exact |
| `tests/test_store.py` (extend) | test | CRUD | itself | exact |
| `tests/test_cli.py` (extend) | test | request-response | itself (CliRunner + FIXTURE_LOG idiom) | exact |
| `tests/perf/generate_synthetic.py` (NEW) | utility (test-only) | file-I/O | none | no analog |
| `tests/perf/test_perf_ingest.py` (NEW) | test (marked perf) | batch | `tests/test_cli.py` (CliRunner end-to-end shape) | role-match |

## Pattern Assignments

### `src/sift/store.py` — migration 2 + zstd + queries (store, CRUD)

**Analog:** `src/sift/store.py` (Phase 1) — extend in place, do not restructure.

**Migration registration** (lines 41-73). New migrations are numbered module-level functions added to `_MIGRATIONS`; the runner (lines 93-106) already handles ordering, `BEGIN IMMEDIATE`, commit/rollback, and `PRAGMA user_version` bump. Copy this shape exactly:

```python
def _migration_1(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE events (
            event_id      TEXT PRIMARY KEY,
            ...
            severity      TEXT NOT NULL
                CHECK (severity IN ('fatal','error','warn','info','debug','unknown')),
            ...
        )
        """
    )
    conn.execute("CREATE INDEX idx_events_ts ON events(ts)")
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _migration_1,
}
```

→ Add `_migration_2` (template_groups table + in-place zstd compression of oversized `raw`) and `2: _migration_2` to the dict. RESEARCH.md Pattern 1 gives the body verbatim. Reuse the CHECK-constraint severity vocabulary for `severity_max`.

**Column-list constant idiom** (lines 75-79, 145-147). SQL column lists are module constants; the `# noqa: S608` comment documents why the f-string is safe:

```python
_EVENT_COLUMNS = (
    "event_id, case_id, ts, ts_confidence, source, source_file, "
    "line_start, line_end, severity, component, thread, session, "
    "message, attrs, raw"
)
...
self._conn.executemany(
    f"INSERT OR IGNORE INTO events ({_EVENT_COLUMNS}) "  # noqa: S608 — column list is a module constant, values are all ?
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    rows,
)
```

→ New `template_groups` insert/query methods follow the same constant + `?`-only shape. The allowlisted `--filter` WHERE snippets belong in a module-level dict here (RESEARCH.md Pattern 5) — CLI never passes SQL fragments.

**Insert-count idiom** (lines 144-150): `before = self._conn.total_changes` … `return self._conn.total_changes - before`. Keep for batched inserts — the CLI's `N new` output depends on it.

**Canonical ordering** (lines 154-157): `ORDER BY ts IS NULL, ts, source_file, line_start` — reuse verbatim in the new streaming `iter_event_summaries()` so exemplar selection is deterministic. The new iterator should select only `(event_id, ts, severity, message)` and yield rows (cursor iteration), not `fetchall()` + full `Event` hydration like `query_events()` (lines 152-177).

**ISO timestamp convention** (lines 126-128, comment): "always store explicit ISO 8601 strings" — `first_ts`/`last_ts` in template_groups follow this; never touch sqlite3 datetime adapters.

**zstd helpers:** analog is `src/sift/adapters/base.py` lines 60-63 (existing `ZstdDecompressor` usage) plus RESEARCH.md's `_encode_raw`/`_decode_raw` code example. Threshold in encoded bytes: `len(raw.encode("utf-8")) > 4096`; decompress with `max_output_size=128 * 2**20`. `_decode_raw` must be the single read path for `raw` (Pitfall 2).

**Meta persistence** (lines 179-188): `get_meta`/`set_meta` with `INSERT OR REPLACE` — use for `mask_version`.

---

### `src/sift/pipeline/dedup.py` (NEW — service, batch transform)

**No structural analog exists for a pipeline stage** — this creates the pattern. Copy conventions from two places:

**Hashing idiom** — `src/sift/models.py` line 44:

```python
return hashlib.sha256(f"{source_file}\x00{byte_offset}".encode()).hexdigest()[:16]
```

→ `template_id = hashlib.sha256(template.encode()).hexdigest()[:16]`, mirroring the frozen `event_id` contract.

**Typer-free pure-logic module** — `src/sift/adapters/__init__.py` `parse_adapter_overrides` (lines 30-51): raises `ValueError` with a helpful message listing valid options; "this module stays typer-free; the CLI converts the error." dedup.py holds `MASK_VERSION`, the compiled `re.VERBOSE` alternation (RESEARCH.md Pattern 2 gives it verbatim), `mask()`, an explicit severity-ordering dict, and `rebuild_template_groups(store)` — no SQL text (store methods only), no typer, no print.

**Module docstring convention** — every Phase 1 module opens with a docstring citing the requirement/decision IDs (see store.py lines 1-7, base.py lines 1-7). Do the same, citing CLUS-01 and ADR 0003.

---

### `src/sift/pipeline/__init__.py` (NEW)

Analog: package inits are minimal. A one-line docstring is enough; no re-exports needed (imports are `from sift.pipeline.dedup import ...`).

---

### `src/sift/cli.py` — batched ingest, progress, `show clusters`, `--filter` (controller)

**Analog:** `src/sift/cli.py` itself.

**Error/exit convention** (throughout): `print(f"Error: {exc}")` then `raise typer.Exit(1) from None` for missing-resource errors; **exit 2 for user-input errors** (unknown adapter, lines 142-150) — unknown `--filter` keys mirror this exactly:

```python
if unknown:
    print(
        f"Error: unknown adapter(s) {unknown}; "
        f"known adapters: {sorted(adapters.REGISTRY)}"
    )
    raise typer.Exit(2)
```

**Repeated-option pattern** (lines 70-72) — `--filter` copies `--adapter`'s shape:

```python
adapter: Annotated[
    list[str], typer.Option("--adapter", help="glob=name adapter override")
] = [],  # noqa: B006
```

**key=value parsing** — copy `parse_adapter_overrides`' `rpartition("=")` split-on-last-equals idiom (`src/sift/adapters/__init__.py` lines 39-51) for `--filter key=value`, but note filter values may contain `=` less often than globs — for filters split on FIRST `=` (`partition`) since keys are the allowlisted side; document the choice.

**Batched streaming ingest** — modify lines 186-187 in `ingest`. Current:

```python
events = list(file_adapter.parse(path, case))
new_count = store.insert_events(events)
```

→ `for batch in itertools.batched(file_adapter.parse(path, case), 5000): new_count += store.insert_events(batch)`, still inside the existing single `with store.transaction():` (line 161) — do NOT add per-batch transactions. Note: `event_count = len(events)` fallback at line 208 must switch to a running counter. Progress bar per RESEARCH.md Pattern 4: `Console(stderr=True)`, advance via `Event.attrs["byte_offset"]`/`"byte_len"`; **stdout stays byte-identical** — existing tests assert on it.

**`show` rendering** — replace the stub at lines 233-235. Copy the `show events` render shape (lines 242-250), notably `_sanitise` on every rendered field and truncation:

```python
for e in store.query_events():
    ts = e.ts.isoformat() if e.ts is not None else "-"
    message = _sanitise(e.message.replace("\n", " "))[:120]
    print(
        f"{e.event_id}  {ts}  {e.severity:<7}  "
        f"{_sanitise(e.source_file)}:{e.line_start}  {message}"
    )
```

→ `show clusters` renders template_groups the same way (templates and exemplar text carry hostile bytes — `_sanitise` everything). Also switch `show events` to the new streaming column-scoped store query.

**Store lifecycle:** `_case_store()` helper (lines 52-62) for opening; note `new` calls `store.close()` explicitly (line 105) — close stores in new code paths too (WAL sidecar checkpoint, Pitfall 4).

**Post-ingest dedup hook:** call `dedup.rebuild_template_groups(store)` AFTER the ingest transaction commits (after line 223's `with` block exits), comparing `meta.mask_version` first.

---

### `tests/test_dedup.py` (NEW)

**Analog:** `tests/test_store.py`. Copy the `_ev()` event-factory pattern (lines 13-35) — keyword defaults, `event_id(source_file, offset)` for identity — and the `tmp_path` + `CaseStore(tmp_path / "case.db")` setup (line 57). Determinism test shape mirrors `test_query_events_deterministic_order` (lines 64-83): insert unordered, assert exact ordered tuples. Add: per-token-class mask tests, compound lines, ≥90% reduction fixture, ingest-twice-identical-groups (Pitfall 6), pathological ReDoS input.

### `tests/test_store.py` (extend)

Migration-upgrade test analog: `test_fresh_store_applies_migration_1` (lines 38-53) — raw `sqlite3.connect` to assert `PRAGMA user_version` and table set. For the v1→v2 upgrade test (Pitfall 7), build a v1 db by running `_migration_1` directly on a raw connection, insert a 5 KB-raw row, reopen via `CaseStore`, assert `user_version == 2`, `typeof(raw) == 'blob'`, and round-trip via the store reader.

### `tests/test_cli.py` (extend)

Copy the existing idioms: module-level `runner = CliRunner()` (line 33), `FIXTURE_LOG` + `_make_case(tmp_path)` (lines 37-49), invoke chains `new → ingest → show` asserting `result.exit_code == 0, result.output` and regex `\b[0-9a-f]{16}\b` for event ids (lines 52-92). Sanitisation test shape: `test_show_strips_terminal_escapes` (lines 124-130) — write hostile bytes into the fixture log, assert no ESC in output; reuse for `show clusters`. Portability test (STORE-01): create case, ingest, delete `data_dir/cases/<name>/` directory, assert gone.

### `tests/perf/` (NEW — no analog)

No existing perf tests or standalone scripts. Use RESEARCH.md's generator sketch (seeded `random.Random(42)`, importable + `__main__`-runnable). Mark `@pytest.mark.perf`; register the marker and `addopts = "-m 'not perf'"` in `pyproject.toml` `[tool.pytest.ini_options]` (currently only has `testpaths`). Reuse the CliRunner end-to-end shape from test_cli.py; generate into `tmp_path`.

## Shared Patterns

### Sanitisation at render time (T-04-01)
**Source:** `src/sift/cli.py` `_sanitise` (lines 30-49)
**Apply to:** every string printed by `show clusters`, filter echoes, progress labels containing file names. Stored text stays verbatim.

### Store owns ALL SQL
**Source:** `src/sift/store.py` module docstring (lines 1-7)
**Apply to:** dedup.py and cli.py must never contain SQL text; filter values only ever bound via `?`; WHERE snippets chosen from an allowlist dict inside store.py.

### Explicit transactions
**Source:** `src/sift/store.py` `transaction()` (lines 108-118) — `BEGIN IMMEDIATE`, rollback on `BaseException`. Ingest keeps ONE transaction (cli.py line 161 comment); `rebuild_template_groups` wraps its DELETE+INSERT+meta write in one `store.transaction()`.

### Requirement-ID docstrings/comments
**Source:** throughout Phase 1 (e.g. store.py line 121 "(INGST-02)", cli.py line 33 "T-04-01"). New code cites STORE-02/STORE-04/CLUS-01/CLI-03 the same way.

### Test isolation (autouse, do not duplicate)
**Source:** `tests/conftest.py` — XDG redirect + socket guard are autouse; conftest is frozen ("Later plans add fixtures in their own test files, never here"). rich/zstd are local-only so the socket guard stays green.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `tests/perf/generate_synthetic.py` | utility | file-I/O | No generator scripts exist; use RESEARCH.md's seeded-generator sketch |

## Metadata

**Analog search scope:** `src/sift/` (store.py, cli.py, models.py, adapters/), `tests/`, `pyproject.toml`
**Files scanned:** 10
**Pattern extraction date:** 2026-07-16
