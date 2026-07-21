---
type: quick
created: 2026-07-21
slug: list-cases
status: complete
---

# Summary: `sift list`

```
CASE    CREATED           EVENTS  HYPOTHESES  DB (MB)
acme    2026-07-21T09:16  1       0           0.1
beta    2026-07-21T09:17  0       0           0.1
broken  —                 —       —           0.0
```

Completes the pair with `sift delete` (879b828): you can now see what you have
before binning it. `HYPOTHESES` is the "have I analysed this yet" column.

## The design constraint

`CaseStore.__init__` runs `_migrate()` (`store.py:467`). Listing N cases through
the store would rewrite the schema of every case on disk — and print a migration
note per case — purely as a side effect of displaying them. `_case_row` therefore
opens each `case.db` read-only (`file:...?mode=ro`), the one deliberate sqlite
access outside `CaseStore` in the CLI, with the reason recorded at the call site.

Everything degrades to an em dash per field on any `sqlite3.Error`, so a corrupt
or old-schema case still appears — that is exactly the case you most want to see
and most likely want to delete.

## Verification

Gate green: ruff clean, pyright 0 errors, pytest 670 passed (666 before).

**The first version of the migration guard was vacuous, and the counterfactual is
what caught it.** It rewound `user_version` to 0 on an already-migrated case; a
store-based listing then hits "table events already exists" in migration 1, errors
out, and writes nothing — so the test passed against the very implementation it
was supposed to reject. Rebuilt around an empty (0-byte, genuinely un-migrated)
`case.db`, where the migration chain runs to completion: the broken version now
fails the assertion loudly. Restored implementation passes.

Also exercised live against a scratch `--data-dir`: three cases including a
deliberately corrupt one list correctly, the listing shrinks after `sift delete`,
and an emptied directory reports `No cases in <path>` at exit 0.

## Deliberately not done

- Filter, sort and `--json` flags. Add them when a listing is long enough to need
  them, not before.
- No "N cases" footer — the rows are the answer.
