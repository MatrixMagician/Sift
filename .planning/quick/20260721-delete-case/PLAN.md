---
type: quick
created: 2026-07-21
slug: delete-case
---

# Quick: `sift delete` — remove a case once it has been analysed

## Problem

Sift ingests customer diagnostic artefacts into `<data_dir>/cases/<name>/case.db`.
Once a case is analysed and the report is out, that directory still holds the raw
customer log text — the exact data the tool exists to keep off the network. There
is no command to get rid of it. `sift new` has no inverse; the only route is `rm -rf`
on a path the operator has to reconstruct by hand.

The mechanism already exists and is documented: `cli.py:181` notes that a clean
store close checkpoints the WAL so "the case directory holds only case.db
afterwards — deleting the directory is deleting the case". Nothing consumes it.

## Decisions (agreed 2026-07-21)

- **Scope: the whole case directory.** `case.db` plus the `mcm/` and `perfmon/`
  report subdirs — the entire `<data_dir>/cases/<name>/` tree. Reports the operator
  exported elsewhere via `sift report --out` are outside the case dir and untouched.
- **No analysed-gate.** A botched or abandoned ingest is exactly the case most worth
  deleting; the confirmation prompt is the safety mechanism, a second gate is friction.
- **Confirm unless `--force`.** First `typer.confirm` in the CLI. `--force` exists so
  the command stays usable from scripts and non-tty contexts.

## Tasks

1. `sift delete <case> [--force] [--data-dir]` in `cli.py`, defined next to `new`
   as its inverse. Resolve the path through the existing `case_db_path` — it already
   allowlist-validates the name (T-02-01) and asserts containment under
   `<data_dir>/cases` after `resolve()`, which is what closes the symlinked-case-dir
   escape. Do not re-implement either check. Missing case → exit 1, matching
   `_case_store`'s wording. Show path + size + file count, confirm, `shutil.rmtree`,
   `OSError` → exit 1 sanitised, never a traceback.
2. Tests in `tests/test_cli.py`: `--force` removes the whole tree; answering `n`
   leaves it intact; unknown case exits 1; a traversal-shaped case name exits 1 and
   deletes nothing.

## Out of scope

- `sift list` (no case-enumeration command exists today; not asked for).
- Secure/shred overwrite — `rmtree` is an unlink, not a wipe. Note it in the docstring
  rather than pretending otherwise.
