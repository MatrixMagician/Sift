---
phase: 02-case-store-template-dedup
reviewed: 2026-07-16T19:45:29Z
depth: deep
files_reviewed: 10
files_reviewed_list:
  - pyproject.toml
  - src/sift/cli.py
  - src/sift/pipeline/__init__.py
  - src/sift/pipeline/dedup.py
  - src/sift/store.py
  - tests/perf/generate_synthetic.py
  - tests/perf/test_perf_ingest.py
  - tests/test_cli.py
  - tests/test_dedup.py
  - tests/test_store.py
findings:
  critical: 1
  warning: 5
  info: 6
  total: 12
status: issues_found
---

# Phase 2: Code Review Report

**Reviewed:** 2026-07-16T19:45:29Z
**Depth:** deep
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Deep review of the Phase 2 surface: migration 2 (template_groups + in-place zstd of oversized raw), transparent zstd read/write paths, hand-rolled masking and recompute-from-store template rebuild, batched streaming ingest with stderr-only progress, allowlisted `--filter`, and the 100 MB perf gate. Cross-file call chains traced: `cli._ingest → adapters.detect → GenericLogAdapter.parse → store.insert_events → dedup.rebuild_template_groups → store.replace_template_groups`, and `cli.show → cli._parse_filters → store.iter_event_rows / query_template_groups → store._build_filter_clauses`.

The load-bearing invariants mostly hold and are verified, not assumed:

- **SQL confinement / injection:** all SQL lives in `store.py`; every value binds via `?`. `--filter` keys map to fixed snippets in module-constant dicts (`_EVENT_FILTER_SQL`, `_CLUSTER_FILTER_SQL`); unknown keys raise `ValueError` in both the CLI (`_parse_filters`) and the store (`_build_filter_clauses`) — genuine defence in depth. Substring filters use `instr`, so `%`/`_` stay literal. `LIMIT` is `?`-bound. The CLI and store allowlists are consistent (`severity/source/file/since/until/limit` vs events dict + limit; `severity/min-count/contains/limit` vs clusters dict + limit). `grep` confirms no SQL text outside `store.py` (tests excepted).
- **zstd bomb cap:** `_decode_raw` passes `max_output_size=_MAX_RAW_BYTES` (128 MiB); legitimate raws are capped at `MAX_EVENT_BYTES = 65536` in the adapter, so the cap can only trip on tampered files. Threshold counts encoded bytes on both write (`_encode_raw`) and migration (`length(CAST(raw AS BLOB))`) — consistent.
- **Determinism:** masking is a single compiled linear alternation; rebuild streams canonical order (`ts IS NULL, ts, source_file, line_start`), so first/last_ts min/max logic in `_Agg` is correct *because of* that ordering; `json.dumps(..., sort_keys=True)` for attrs and coverage; the shared `_CCTX` is single-threaded level 3.
- **since/until string comparison:** stored ts and bound values are both `datetime.isoformat()` UTC renderings; `'+' < '.' < digits` makes mixed microsecond precision compare chronologically. Verified against all four precision combinations.
- **Zero egress:** no network code anywhere in the diff; conftest's socket guard and XDG isolation cover the perf test (it uses `load_config().data_dir` safely because `_isolate_dirs` is autouse).
- **Terminal-injection regression check (Phase 1 classes):** `--filter` error echoes are `_sanitise`d (cli.py:408); the rich progress description is a static string (cli.py:190); adapter `notes` (cli.py:290) carry only operator-config-derived text (tz zone names/globs), verified in genericlog.py:436-450. However, several DB-sourced fields still reach the terminal unsanitised — see WR-01.

One critical accounting defect was found in the ingest error path (partial-file failure), plus five warnings.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Partial events from a mid-parse failure are committed but reported as zero in coverage meta and the Total line

**File:** `src/sift/cli.py:239-267` (interacting with the single transaction opened at `src/sift/cli.py:201`)
**Issue:** The whole ingest runs in ONE `store.transaction()`. Inside it, events are inserted batch-by-batch (`batched(..., 5000)` at line 239). When `file_adapter.parse()` raises **after one or more batches were already inserted** — the realistic case being a large `.gz`/`.zst` archive whose head decompresses fine at `detect()` but is truncated later (gzip raises `EOFError` mid-stream), i.e. exactly the corrupt-archive class Phase 1's CR-01 addressed — the `except` branch records `coverage[relpath] = {"error": ..., "event_count": 0, "coverage": 0.0}` and `continue`s. The already-inserted batches are **not rolled back** and commit with the surrounding transaction. Consequences:

1. `parse_coverage` meta persists `event_count: 0` for a file that contributed up to N×5000 rows — downstream phases (salience, report) read this meta and will state false coverage claims.
2. `total_new` excludes those rows, so `Total: N new events` (line 297) undercounts what is actually in the store.
3. `rebuild_template_groups` (line 296) *does* count them, so `sum(group.count)` ≠ `sum(coverage[*].event_count)` — the accounting invariant `test_accounting_every_event_counted_once` protects is silently broken at the case level, permanently: if the archive stays truncated, every re-ingest re-fails and the orphaned rows are never accounted for.

The existing test `test_ingest_corrupt_compressed_file_fails_loudly_but_continues` only exercises a **detect-time** failure (4-byte gz stub, zero events inserted), so this path is untested. This directly contradicts the "nothing disappears silently" invariant — here rows *appear* silently.
**Fix:** Give each file its own savepoint so a failed file contributes exactly zero rows, keeping the outer all-or-nothing transaction intact:

```python
# store.py
@contextmanager
def savepoint(self, name: str = "ingest_file") -> Generator[None]:
    self._conn.execute(f"SAVEPOINT {name}")   # name is a code constant, never user data
    try:
        yield
    except BaseException:
        self._conn.execute(f"ROLLBACK TO {name}")
        self._conn.execute(f"RELEASE {name}")
        raise
    else:
        self._conn.execute(f"RELEASE {name}")

# cli.py — wrap the per-file try body:
try:
    with store.savepoint():
        file_adapter = adapters.detect(path, relpath, overrides)
        ...
        for batch in batched(file_adapter.parse(path, case), 5000):
            new_count += store.insert_events(batch)
            ...
except Exception as exc:
    ...
```

Alternatively (smaller diff, weaker semantics): record the real inserted count in the error coverage entry (`"event_count": parsed_count`, add `new_count` to `total_new`) and document that failed files may be partially ingested. The savepoint fix is preferred — it keeps "failed file ⇒ 0 events" true, which is what the coverage record already claims. Add a test with a large truncated `.gz` (>5000 events before the cut) asserting the failed file contributes zero rows.

## Warnings

### WR-01: `show` renders several DB-sourced fields unsanitised — terminal-injection surface on a tampered case.db

**File:** `src/sift/cli.py:417-423` (clusters), `src/sift/cli.py:429-435` (events)
**Issue:** A shared `case.db` is untrusted input by this phase's own threat model — that is precisely why `_decode_raw` carries a zstd-bomb cap (store.py:23,44-46). Yet the render paths sanitise only some fields:

- events (line 433-434): `message` and `source_file` are `_sanitise`d, but `event_id`, `ts` and `severity` are printed raw. These are TEXT columns in a file the attacker fully controls (SQLite type affinity and CHECK constraints are whatever the tampered schema says), so ESC/CSI/bidi bytes there reach the operator's terminal.
- clusters (lines 420-423): only `template` is sanitised; `template_id`, `count`, `severity_max`, `first_ts`, `last_ts` and every `exemplar_event_ids` entry print raw. A hostile `exemplar_event_ids` JSON array of escape sequences is a one-line terminal-injection vector. (A non-list JSON value there also crashes `' '.join(...)` with a raw traceback.)

This is a direct regression of the Phase 1 T-04-01 class, just moved from bundle bytes to case-file bytes.
**Fix:** Sanitise the complete rendered line instead of individual fields — smallest diff, closes every field at once:

```python
print(_sanitise(
    f"{g.template_id}  {g.count:>7}  {g.severity_max:<7}  "
    f"{g.first_ts or '-'}  {g.last_ts or '-'}  {template}"
))
print(_sanitise(f"    exemplars: {' '.join(map(str, g.exemplar_event_ids))}"))
```

and equivalently wrap the events line. Extend `test_show_clusters_strips_terminal_escapes` with a store-level fixture that writes hostile bytes into `exemplar_event_ids`/`first_ts` directly.

### WR-02: `show` on a read-only or corrupt case.db crashes with a raw traceback (and silently rewrites Phase-1 evidence files)

**File:** `src/sift/store.py:221-227`, `src/sift/cli.py:62-72`
**Issue:** `CaseStore.__init__` unconditionally executes `PRAGMA journal_mode=WAL` (a write operation) and runs migrations. Two consequences for `sift show`, a nominally read-only command on a triage tool whose case files may live on read-only evidence media:

1. On a read-only `case.db`, `PRAGMA journal_mode=WAL` (or the migration `BEGIN IMMEDIATE`) raises `sqlite3.OperationalError: attempt to write a readonly database`, which nothing catches — the operator gets a stack trace instead of an error message. A corrupt/tampered file likewise surfaces as an uncaught `sqlite3.DatabaseError`.
2. Opening a Phase-1 v1 database with `show` runs migration 2, which **rewrites the file** (compresses oversized raws) as a side effect of a read command. That is surprising for evidence handling and deserves at least a printed notice.
**Fix:** In `_case_store`, wrap store construction: `except sqlite3.Error as exc: print(f"Error: cannot open case {case!r}: {_sanitise(str(exc))}"); raise typer.Exit(1)`. Separately, have `_migrate` print a one-line "migrating case.db v1 → v2" notice (stderr) when it actually applies a migration.

### WR-03: Crash window between event commit and group rebuild leaves `show clusters` silently stale

**File:** `src/sift/cli.py:294-296`, `src/sift/pipeline/dedup.py:121-124`
**Issue:** The event transaction commits first; `rebuild_template_groups` then runs in its own transaction. If the process dies (or rebuild raises — e.g. the WR-02 lock/disk errors, or a `template_id` PK collision) in that window, `template_groups` keeps the *previous* ingest's content while `events` has the new rows. `show clusters` then renders wrong counts with zero indication, until some later ingest happens to run. The recompute-from-store design makes recovery trivial, but nothing detects that recovery is needed.
**Fix:** Inside the event transaction (cli.py:293), add `store.set_meta("template_groups_stale", "1")`; clear it inside the rebuild transaction (dedup.py:123). In `show clusters`, if the flag is set, either rebuild before rendering or print a warning line ("template groups are stale; re-run 'sift ingest'").

### WR-04: Bare-hex mask swallows pure-decimal tokens of 8+ digits, shattering templates on numeric magnitude

**File:** `src/sift/pipeline/dedup.py:27`
**Issue:** `\b[0-9a-fA-F]{8,}\b` matches strings containing **only digits**: `retried 12345678 times` masks to `retried <HEX> times` while `retried 1234567 times` masks to `retried <NUM> times`. Any log line whose volatile token crosses the 8-digit width — epoch-seconds (10 digits), epoch-millis (13), request/order ids, byte counts — splits one message shape into two template groups depending on value magnitude. Nothing is lost (both mask), but the ≥90 % reduction property degrades on exactly the token classes real logs use most, and `show clusters` double-reports what is one event family. Note the synthetic perf corpus never exercises this: its `{n}` tokens stay < 100 000 (5-6 digits).
**Fix:** Require at least one hex letter in the bare-hex alternative so pure-decimal runs fall through to `<NUM>` (both lookaheads are bounded, linear scans — no ReDoS regression):

```python
| (?P<hex>0[xX][0-9a-fA-F]+|\b(?=[0-9a-fA-F]{8,}\b)(?=[0-9]*[a-fA-F])[0-9a-fA-F]+\b)
```

Bump `MASK_VERSION` to 2 (dedup.py:16). Existing tests pass (the 32-hex SID fixtures all contain letters); add `assert mask("id 1234567890123 end") == "id <NUM> end"`.

### WR-05: Duplicate `--filter` keys silently last-wins, contradicting both the documented AND-combine semantics and the fail-loud contract

**File:** `src/sift/cli.py:326-370`
**Issue:** `show --help` documents "Filters (repeatable, AND-combined)" and `_parse_filters`' docstring promises "bad input fails loudly, never an empty result set that looks like 'no matches'". But `filters[key] = value` in a dict means `--filter severity=error --filter severity=warn` silently discards `error` and shows warn-only — neither AND-combined nor loud. For `since`/`until` a typo'd duplicate silently narrows or widens a triage window, which is a wrong-conclusions risk in an evidence tool.
**Fix:**

```python
if key in filters:
    raise ValueError(f"duplicate filter key {key!r}; each key may appear once")
```

placed right after the allowlist check (line 335). Add a CLI test asserting exit 2 on a repeated key.

## Info

### IN-01: Six-severity vocabulary duplicated in four places

**File:** `src/sift/cli.py:305`, `src/sift/pipeline/dedup.py:43-50`, `src/sift/store.py:84-85`, `src/sift/store.py:115-118`
**Issue:** The `fatal|error|warn|info|debug|unknown` set is written independently in the CLI allowlist, the dedup rank map, and two CHECK constraints. Adding a severity (or a typo in one copy) drifts silently — the CLI would accept a value the store rejects, or vice versa.
**Fix:** Define `SEVERITIES: tuple[str, ...]` once in `sift/models.py` next to the frozen `Event`; derive the CLI tuple and the rank map from it, and interpolate `", ".join(f"'{s}'" for s in SEVERITIES)` into the migration DDL (code constant, not user data).

### IN-02: Migration 2 loads every oversized raw into memory at once

**File:** `src/sift/store.py:124-127`
**Issue:** `fetchall()` materialises all >4 KB raws of a v1 database before compressing. Bounded in practice by Phase-1 case sizes, but a multi-GB v1 case would spike memory during a one-time upgrade while the rest of the codebase carefully streams.
**Fix:** Iterate with `fetchmany(1000)` on one cursor and `UPDATE` via a second cursor (or collect event_ids first, then re-select each raw individually).

### IN-03: ROLLBACK in the exception path can mask the original error

**File:** `src/sift/store.py:240-242`, `src/sift/store.py:250-252`
**Issue:** If the original failure already ended or invalidated the transaction (e.g. connection-level `OperationalError`), the bare `self._conn.execute("ROLLBACK")` raises `cannot rollback - no transaction is active`, replacing the diagnostic root cause in the traceback.
**Fix:** `try: self._conn.execute("ROLLBACK") except sqlite3.OperationalError: pass` before `raise` in both `_migrate` and `transaction`.

### IN-04: TOCTOU on the upfront `stat()` pass aborts the entire ingest instead of one file

**File:** `src/sift/cli.py:184`
**Issue:** `sizes = {path: path.stat().st_size for path in files}` runs before the per-file try/except. A file deleted (or a symlink whose target vanishes) between `rglob` and `stat` raises `FileNotFoundError` here, crashing the whole run with a traceback — inconsistent with the loud-per-file-error design everywhere else.
**Fix:** Build `sizes` defensively: `sizes = {}; for p in files: try: sizes[p] = p.stat().st_size except OSError: sizes[p] = 0` (the per-file loop's existing error path then reports the file when parse fails).

### IN-05: Symlinked directories inside a bundle are silently ignored (file symlinks are recorded loudly)

**File:** `src/sift/cli.py:173`, `src/sift/cli.py:205-217`
**Issue:** `rglob("*")` does not traverse symlinked directories (correct for the trust boundary), and `p.is_file()` filters the symlink entry itself out, so a dir-symlink leaves **no** SKIP line and no coverage record — unlike file symlinks, which are recorded per T-02 requirements. A hostile or accidental dir-symlink disappears from the audit trail entirely.
**Fix:** In the file-collection pass, also collect `p.is_symlink() and not p.is_file()` entries and give them the same `"skipped": "symlink (not followed)"` coverage entry.

### IN-06: zstd decompression failures propagate as raw `ZstdError` through `query_events`

**File:** `src/sift/store.py:39-47`, `src/sift/store.py:288-313`
**Issue:** When the bomb cap trips or a frame is corrupt, `_decode_raw` raises `zstandard.ZstdError` with no context (no event_id, no "tampered case file" framing). No current CLI path reads `raw`, so this is latent — but `query_events` is the API Phase 3+ (analyze/report) will call, and the failure will surface there as an unexplained traceback.
**Fix:** Catch and re-raise with context in `query_events`: `raise ValueError(f"event {r[0]}: raw payload failed zstd decompression (corrupt or tampered case file)") from exc`.

---

_Reviewed: 2026-07-16T19:45:29Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
