---
type: quick
created: 2026-07-21
slug: list-cases
---

# Quick: `sift list` — enumerate cases

## Problem

Every Sift command takes a case name, and nothing tells you what those names are.
`sift delete` (879b828) made this sharper: you cannot safely bin what you cannot
enumerate. The names live only in the operator's memory or in `ls` on a data
directory whose location is config-resolved.

## The hazard this design is built around

`CaseStore.__init__` calls `_migrate()` (`store.py:467`), which opens a write
transaction and rewrites the schema. Listing N cases through `CaseStore` would
**migrate every case on disk as a side effect of displaying it** — and print a
`note: migrating case.db to schema vN` line per case while doing it.

A listing must not mutate evidence. `sift list` therefore opens each `case.db`
with a read-only URI connection (`file:...?mode=ro`) and queries directly,
deliberately bypassing `CaseStore`. This is the one place in the CLI that is
allowed to touch sqlite outside the store, and the reason is written at the call
site so nobody "tidies" it back onto `CaseStore` later.

## Tasks

1. `sift list [--data-dir]` in `cli.py`: enumerate `<data_dir>/cases/*/case.db`,
   sorted by name. Columns: NAME, CREATED, EVENTS, HYPOTHESES, SIZE.
   - Read-only connection per case; every field degrades to `—` on any
     `sqlite3.Error`. A corrupt or unreadable case still appears in the list —
     it is exactly the case you are most likely to want to delete.
   - `hypotheses` only exists from a later migration, so a Phase-1-era case must
     render `—` rather than raise.
   - Directory names are filesystem-sourced and untrusted: route through
     `_sanitise` like every other display field (T-04-01).
   - No cases → a plain message naming the directory, exit 0. Not an error.
2. Tests: multi-case listing sorted and populated; empty data dir; a corrupt
   `case.db` still listed with `—`; and the migration guard — listing must leave
   `PRAGMA user_version` and the file mtime untouched on an old-schema case.

## Out of scope

- Filters/sorting flags, JSON output. Add when the list is long enough to need them.
