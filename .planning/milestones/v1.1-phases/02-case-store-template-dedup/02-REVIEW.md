---
phase: 02-case-store-template-dedup
reviewed: 2026-07-16T22:24:53Z
depth: deep
files_reviewed: 9
files_reviewed_list:
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
  critical: 0
  warning: 4
  info: 3
  total: 7
status: issues_found
---

# Phase 2: Code Review Report (post-gap-closure re-review)

**Reviewed:** 2026-07-16T22:24:53Z
**Depth:** deep
**Files Reviewed:** 9
**Status:** issues_found

## Summary

Re-review of the Phase 2 surface after gap-closure plan 02-04 (8 commits,
`a78ac6f..0e8fd32`). All gates are green as reviewed: `ruff check` clean,
`pyright` clean (strict), `pytest` 174 passed / 1 perf-deselected. Cross-file
analysis traced the ingest path end-to-end (cli → adapters.detect →
GenericLogAdapter.parse → store savepoint/transaction →
dedup.rebuild_template_groups) and both show render paths, plus the
timestamp-string comparison contract between `_parse_filters` normalisation
and the adapter's UTC-normalised output (verified chronological: all stored
`ts` carry a `+00:00` suffix, and ASCII ordering of `'+' < '.' < digits`
makes mixed-microsecond comparisons correct).

**All eight prior findings are verifiably resolved in the current code** (see
table below). The re-review found **no blockers** and **four new warnings** —
two of which are residual gaps in the very mechanisms the fixes introduced
(`_sanitise` whole-line coverage, savepoint rollback guards) — plus three
info items. The warnings are edge-triggered (hostile filenames, disk-level
SQLite failures, mask-version drift on old cases); none invalidates the
phase's core deliverables. Two warnings (WR-06, WR-08) were confirmed
empirically by executing the sanitisation logic, not by inspection alone.

### Prior findings verification (02-04 gap closure)

| Prior finding | Status | Evidence |
|---|---|---|
| CR-01 per-file savepoint | **Resolved** | `store.savepoint()` (`src/sift/store.py:276-300`) wraps detect+parse+insert per file (`src/sift/cli.py:239`); `test_ingest_truncated_gz_mid_stream_contributes_zero_rows` proves a >5000-event mid-stream failure contributes zero rows and the three-way accounting identity (groups == events == coverage) holds. Savepoint nesting inside the outer `BEGIN IMMEDIATE` is correct: each per-file savepoint is released before the next opens, `ROLLBACK TO` + `RELEASE` on failure fully discards the file. |
| WR-01 whole-line sanitisation | **Resolved (residual gap: WR-06 below)** | Both `show events` and `show clusters` sanitise the complete rendered line (`src/sift/cli.py:464-485`); tampered-db test `test_show_sanitises_every_db_sourced_field` plants ESC/bidi in `event_id`, `ts`, `first_ts`, `exemplar_event_ids`. Non-array exemplar JSON coerced in `query_template_groups` (`src/sift/store.py:447-459`) with tests on both layers. |
| WR-02 graceful corrupt-db open | **Resolved** | `_case_store` catches `sqlite3.Error`, sanitises the message, exits 1 (`src/sift/cli.py:74-81`); migration announces on stderr (`src/sift/store.py:243`); tests `test_show_corrupt_case_db_exits_1_without_traceback`, `test_migration_prints_stderr_notice`. |
| WR-03 stale-groups flag | **Resolved** | `template_groups_stale=1` written inside the event transaction (`src/sift/cli.py:323`), cleared inside the rebuild transaction (`src/sift/pipeline/dedup.py:134`); `show clusters` warns on stderr and still renders (`src/sift/cli.py:452-458`); test `test_show_clusters_warns_when_template_groups_stale`. |
| WR-04 MASK_VERSION 2 hex mask | **Resolved** | Letter-required lookahead `(?=[0-9]*[a-fA-F])` (`src/sift/pipeline/dedup.py:34`); verified empirically: 13-digit epoch millis, 8-digit and even 32-digit pure-decimal runs → `<NUM>`; letter-bearing 32-hex SIDs and `0x`-prefixed → `<HEX>`. Re-ingest determinism unaffected — `event_id` never involves masking; `test_reingest_rebuild_idempotent` green; groups recompute at next ingest. Rule-version drift on already-ingested cases is a new gap (WR-09). |
| WR-05 duplicate --filter keys | **Resolved** | `_parse_filters` raises on a repeated key (`src/sift/cli.py:366-371`); test `test_show_duplicate_filter_key_exits_2` covers both targets. |
| IN-03 rollback guards | **Resolved** | ROLLBACK failure never masks the original error in `_migrate`, `transaction`, `savepoint` (`src/sift/store.py:251-257,266-272,291-298`) — but see WR-07 for a consequence the guard introduces. |
| IN-04 stat race | **Resolved** | `sizes[path] = 0` fallback on `OSError` (`src/sift/cli.py:195-200`); a vanished file then fails loudly in the per-file loop via the detect/open error path. |

Also verified during cross-file analysis (no findings): adapter timestamps
are always UTC-normalised before storage (`_match_ts`/`to_utc` in
`genericlog.py`), so the string `ts >= ?` filter comparison is chronological;
`ParseStats.notes` contain only config-derived text (counts, tz names) —
currently safe unsanitised, see IN-07; `tests/conftest.py` isolates
XDG dirs per test and blocks all socket connections (zero-network rule holds
for the perf test too); the synthetic generator is ASCII-only so its
`len(line)` byte accounting is exact.

## Warnings

### WR-06: `_sanitise` passes newlines through — hostile filenames and tampered DB fields can forge output lines

**File:** `src/sift/cli.py:42-61` (render sites at 225, 290, 312, 444, 466-471, 482-485)
**Issue:** `_sanitise` deliberately keeps `\n`, but every ingest/show render
site is a *single-line* record. A POSIX filename may legally contain a
newline, and WR-01's own threat model treats every DB-sourced field as
attacker-controlled. Verified empirically:
`_sanitise("app.log\nTotal: 999999 new events")` returns the string
unchanged. Consequences: a bundle file named `x.log\nTotal: 0 new events`
forges the ingest summary line; a tampered `event_id`, `ts` or exemplar id
containing `\n` injects a fully attacker-authored fake event/cluster row into
`show` output — spoofed citation evidence in a forensic tool. The WR-01
tampered-db test plants ESC and bidi characters but never a newline, so the
gap is untested. (`\t` pass-through is also attacker-usable for column
misalignment, but is cosmetic by comparison.)
**Fix:** keep `_sanitise` as the multi-line-capable base (exception text
legitimately spans lines) and strip newlines at single-line render sites:

```python
def _sanitise_line(text: str) -> str:
    """Single-line render: newlines/tabs become spaces before sanitising."""
    return _sanitise(text.replace("\n", " ").replace("\t", " "))
```

Use it for every per-record `print` in ingest and both `show` paths; extend
`test_show_sanitises_every_db_sourced_field` to plant `"\nFORGED-ROW"` in
`event_id`, and add a newline-bearing filename to the hostile-filename test.

### WR-07: after a SQLite auto-rollback (disk full / I/O error) the per-file loop continues outside any transaction, breaking the all-or-nothing ingest contract

**File:** `src/sift/store.py:291-298`, `src/sift/cli.py:277-293`
**Issue:** certain SQLite errors (`SQLITE_FULL`, `SQLITE_IOERR`,
`SQLITE_NOMEM`) automatically roll back the *entire* transaction, destroying
all savepoints. The savepoint guard then swallows the resulting
`OperationalError` from `ROLLBACK TO` (correctly re-raising the original
error), the per-file `except Exception` in `_ingest` treats this
transaction-fatal error as an ordinary per-file failure, and the loop
continues — but the connection is now in **autocommit** mode. Every
subsequent `insert_events`/`set_meta` commits immediately (violating "an
interrupted ingest leaves either the complete result or nothing",
`src/sift/cli.py:215-216`), and the outer `transaction()` exit then executes
`COMMIT` with no transaction active, raising an uncaught `OperationalError`
traceback. Net effect on a disk-full event: partial per-file data durably
committed plus a Python traceback.
**Fix:** after a swallowed rollback failure, detect the lost transaction and
abort the run instead of continuing:

```python
except BaseException:
    try:
        self._conn.execute(f"ROLLBACK TO {name}")
        self._conn.execute(f"RELEASE {name}")
    except sqlite3.OperationalError:
        if not self._conn.in_transaction:
            # Outer transaction auto-rolled-back (SQLITE_FULL/IOERR):
            # continuing would insert in autocommit mode.
            raise
    raise
```

Raise a distinct exception type (or have `_ingest`'s per-file handler check
`store` transaction state) so the run fails loudly with nothing committed;
also guard `transaction()`'s `COMMIT` with an `in_transaction` check for a
clean message instead of a traceback.

### WR-08: a non-UTF-8 (surrogate-escaped) filename aborts the whole ingest with a traceback and rolls back every good file

**File:** `src/sift/cli.py:311-314` (also 225, 290)
**Issue:** on Linux, a filename containing invalid UTF-8 bytes (legacy
encodings, hostile tar bundles) decodes via `surrogateescape` — `relpath`
then contains lone surrogates (category `Cs`). `_sanitise` does not strip
them (verified: `_sanitise("caf\udce9.log")` returns the surrogate intact),
and `print` raises `UnicodeEncodeError` on the default strict UTF-8 stdout
(also verified). The success-path `print` at line 311 sits *inside*
`store.transaction()` but *outside* the per-file try/except, so one odd
filename destroys the entire ingest run: full rollback of every good file
plus a raw traceback — violating both the loud-per-file invariant and
WR-02's no-traceback goal.
**Fix:** strip surrogates in `_sanitise` alongside format characters:

```python
and unicodedata.category(ch) not in ("Cf", "Cs")
```

Add a test that creates a file via a bytes path
(`open(os.path.join(os.fsencode(input_dir), b"caf\xe9.log"), "wb")`) and
asserts ingest exits 0 with the file's events stored and no traceback.

### WR-09: `mask_version` meta is written but never read — a MASK_VERSION bump leaves existing cases silently showing stale groups

**File:** `src/sift/pipeline/dedup.py:16,131`, `src/sift/cli.py:449-458`
**Issue:** the WR-04 fix bumped `MASK_VERSION` to 2 and the constant's
comment promises "groups recompute cheaply" on a bump, but nothing ever
reads the `mask_version` meta. A case ingested under MASK_VERSION 1 and
opened with current code has `template_groups_stale == "0"`, so
`show clusters` renders version-1 groups (pure-decimal runs shattered as
`<HEX>`) with no warning and nothing triggers recomputation. The stale-flag
mechanism (WR-03) covers crash staleness but not rule-version staleness —
the operator gets no signal that `sift ingest` must be re-run, and identical
inputs analysed before/after the bump show different clusters (a determinism
gap across code versions that the operator cannot see).
**Fix:** in `show clusters`, warn on version drift, mirroring the WR-03
warning:

```python
stored = store.get_meta("mask_version")
if stored is not None and stored != str(dedup.MASK_VERSION):
    print(
        f"Warning: template groups were built with mask rules v{stored} "
        f"(current v{dedup.MASK_VERSION}); re-run 'sift ingest'",
        file=sys.stderr,
    )
```

(Alternatively rebuild transparently — cheap per the module's own claim —
but a warning matches the WR-03 precedent.) Add a test that rewrites the
meta to `"1"` and asserts the stderr warning.

## Info

### IN-05: dangling symlinks vanish silently from coverage accounting

**File:** `src/sift/cli.py:182,196`
**Issue:** `files = [p for p in sorted(input_dir.rglob("*")) if p.is_file()]`
— `is_file()` follows symlinks and returns False for a dangling one, so a
broken symlink is excluded before the loud symlink-skip branch (line 221)
can record it. Regular symlinks are loudly skipped and persisted in coverage;
broken ones disappear without a trace — a letter-of-the-law violation of
"nothing disappears silently". Also, `sizes[path] = path.stat().st_size`
follows symlinks, so a symlink to a huge target inflates the progress total
even though the file is skipped (cosmetic).
**Fix:** include symlinks in the listing
(`if p.is_file() or p.is_symlink()`) so the existing skip branch records
dangling ones too, and use `path.lstat().st_size` when `p.is_symlink()`.

### IN-06: filter-key allowlists and severity vocabulary duplicated between cli.py and store.py

**File:** `src/sift/cli.py:335-342`, `src/sift/store.py:164-176`
**Issue:** `_FILTER_KEYS`/`_SEVERITIES` in the CLI mirror
`_EVENT_FILTER_SQL`/`_CLUSTER_FILTER_SQL` keys and the store CHECK
vocabulary. The mirror is documented and the store re-validates (genuine
defence in depth), but adding a filter key now requires touching two dicts
that can drift — the failure mode is a key accepted by one layer and
rejected by the other.
**Fix:** derive the CLI allowlists from the store's dicts, e.g. export
`EVENT_FILTER_KEYS = (*_EVENT_FILTER_SQL, "limit")` from `store.py` and
build `_FILTER_KEYS` from those — a single source of truth.

### IN-07: per-file adapter notes are printed unsanitised

**File:** `src/sift/cli.py:315-316`
**Issue:** `print(f"  note: {note}")` skips `_sanitise`. Today this is safe —
`ParseStats.notes` in `genericlog.py` (lines 434-450) are template strings
built only from counts and config-supplied tz names/globs — but the ingest
loop treats every other printed value as untrusted, and a future adapter
that embeds file content in a note (e.g. "unparseable header: <bytes>")
would leak hostile bytes to the terminal through this one gap.
**Fix:** `print(f"  note: {_sanitise(note)}")` — one call closes the class.

---

_Reviewed: 2026-07-16T22:24:53Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
