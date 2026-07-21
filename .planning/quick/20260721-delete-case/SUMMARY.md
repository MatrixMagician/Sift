---
type: quick
created: 2026-07-21
slug: delete-case
status: complete
---

# Summary: `sift delete`

Added `sift delete <case> [--force]` — the inverse of `sift new`. It removes the
whole case directory (`case.db` plus the `mcm/` and `perfmon/` artefacts), prompts
before doing so, and takes `--force` for scripted use. No analysed-gate: an
abandoned ingest is exactly the case most worth deleting.

## What landed

- `cli.py` — `delete`, defined next to `new`. Path resolution reuses `case_db_path`,
  which allowlist-validates the name and asserts containment under `<data_dir>/cases`
  after `resolve()`. `shutil.rmtree`; `OSError` → exit 1 sanitised.
- `cli.py` module docstring said "Seven flat subcommands" — already wrong before this
  change (there were nine). Dropped the count rather than bump a number that rots.
- `tests/test_cli.py` — four tests: `--force` removes the whole tree including report
  artefacts; declining at the prompt changes nothing and exits non-zero; unknown case
  exits 1 without a traceback; a traversal-shaped name is refused and deletes nothing.
- `README.md` + `docs/GETTING-STARTED.md` — command table row and a quickstart note.

## Verification

Gate green: ruff clean, pyright 0 errors, pytest 666 passed (662 before).

The traversal test was proven load-bearing rather than assumed. Replacing
`case_db_path(...)` with a naive `data_dir / "cases" / case / "case.db"` join makes
the command print `Deleted case '../not-a-case'` — it really does escape the case
root and recursively delete an outside directory. The decoy directory in that test
carries its own `case.db` precisely so the broken build gets past the existence
check and the "keep.txt survives" assertion is what fires.

Also exercised live (not just under pytest) against a scratch `--data-dir`:
declining leaves `case.db` and `mcm/` in place at exit 1; accepting empties
`cases/` at exit 0.

## Deliberately not done

- **`sift list`.** There is no case-enumeration command in Sift today, so `delete`
  gives you no new way to discover case names. Worth considering, but not asked for.
- **Secure erase.** `rmtree` unlinks; it does not overwrite. The docstring says so
  rather than implying a wipe. If the threat model needs shredding, that is a
  different piece of work with filesystem-specific caveats.
