---
phase: 02-case-store-template-dedup
plan: 03
subsystem: store-cli-inspection
tags: [filters, sql-injection, streaming, store-04]

requires:
  - 02-01 store v2 (template_groups, query_template_groups, show clusters format)
  - 02-02 streaming ingest + perf gate (tests/perf pyright executionEnvironment)
provides:
  - "Allowlisted --filter on `sift show <case> events|clusters` (STORE-04 Phase-2 targets)"
  - "store.py _EVENT_FILTER_SQL/_CLUSTER_FILTER_SQL + iter_event_rows() column-scoped streaming"
  - "query_template_groups(filters=...) optional parameter"
  - "CLI _parse_filters(): typed validation, exit-2 error shape, grammar in --help"
affects: [phase-03-embedding, phase-04-hypotheses, phase-05-domain-adapters]

tech-stack:
  added: []
  patterns:
    - "Filter key -> fixed WHERE snippet allowlist dicts in store.py; values only ever ?-bound; instr() over LIKE for substrings (T-02-08)"
    - "limit handled as a trailing 'LIMIT ?' clause, never via the snippet dicts"
    - "CLI validates filters typed (severity vocab, non-negative ints, ISO timestamps); store re-validates keys as defence in depth (ValueError)"
    - "show streams rows via iter_event_rows — no raw column, no zstd, no Event hydration (T-02-10)"

key-files:
  created: []
  modified:
    - src/sift/store.py
    - src/sift/cli.py
    - tests/test_store.py
    - tests/test_cli.py

key-decisions:
  - "--filter splits on the FIRST '=' (str.partition): keys are allowlisted and never contain '='; values may. Deliberate opposite of parse_adapter_overrides' last-'=' split (documented beside the code)"
  - "Filter key vocabulary frozen: events -> severity, source, file, since, until, limit; clusters -> severity, min-count, contains, limit (RESEARCH Pattern 5 minimal set; more keys are cheap follow-ups)"
  - "Naive since/until treated as UTC, normalised via astimezone(UTC).isoformat() before binding so string comparison against stored UTC ts is chronological; NULL-ts rows excluded (documented in --help)"
  - "instr() not LIKE for file/contains so % and _ in values stay literal (proven by a %-containing positive-match test plus a LIKE-wildcard no-match test)"
  - "STORE-04 ticked with partial-scope note: events+clusters targets delivered; hypotheses inspection target arrives in Phase 4 (mirrors 02-02's CLI-03 convention)"
  - "show events/clusters both close the store in try/finally — the events path previously leaked the connection (WAL sidecars); fixed as part of the streaming rewrite"

requirements-completed: [STORE-04]

metrics:
  duration: ~16min
  completed: 2026-07-16
  tasks: 2
  tests-before: 137
  tests-after: 164

status: complete
---

# Phase 2 Plan 03: Filtered Inspection & Streaming Show Summary

`sift show <case> events|clusters --filter key=value` (repeatable, AND-combined) inspects stored data pre-AI through an allowlist-plus-parameterised injection boundary: keys map to fixed WHERE snippets inside store.py, every value binds via `?`, substring matches use `instr()` so SQL wildcards stay literal, and `show events` now streams column-scoped rows byte-identical to the Phase 1 format without touching `raw`.

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | RED — filter contract pinned by strict-xfail tests | 3d58c54 | tests/test_cli.py, tests/test_store.py |
| 2 | GREEN — allowlisted filters + --filter + streaming show | 7b036d0 | src/sift/store.py, src/sift/cli.py, tests/test_store.py, tests/test_cli.py |

## Contracts (frozen for Phase 3+)

**Filter grammar (documented in `sift show --help`):**

- events keys: `severity=<fatal|error|warn|info|debug|unknown>`, `source=<adapter>`, `file=<source_file substring>`, `since=<ISO 8601>`, `until=<ISO 8601>`, `limit=<N>`
- clusters keys: `severity=<max severity>`, `min-count=<N>`, `contains=<template substring>`, `limit=<N>`
- Multiple `--filter` options AND-combine; substring matches are literal (no wildcards); naive since/until are UTC; since/until exclude NULL-ts events (documented semantic, not silent loss). Phase 3+ extends clusters inspection to semantic clusters.

**New store API (src/sift/store.py):**

```python
_EVENT_FILTER_SQL: dict[str, str]    # severity/source/file/since/until -> ?-bound snippets
_CLUSTER_FILTER_SQL: dict[str, str]  # severity/min-count/contains -> ?-bound snippets
def _build_filter_clauses(filters, allowed) -> tuple[where_sql, limit_sql, params]
CaseStore.iter_event_rows(filters=None) -> Iterator[tuple[str, str | None, str, str, int, str]]
    # (event_id, ts, severity, source_file, line_start, message) — exactly the six
    # rendered fields, canonical order, cursor-streamed, no raw (T-02-10)
CaseStore.query_template_groups(filters=None)  # ORDER BY count DESC, template preserved
```

Unknown keys reaching the store raise ValueError naming valid keys (defence in depth behind CLI validation). `limit` is a trailing `LIMIT ?`, never a snippet.

**CLI (src/sift/cli.py):** `_parse_filters(specs, target)` is typer-free; splits each spec on the FIRST `=` (keys never contain `=`, values may — the deliberate opposite of `parse_adapter_overrides`' last-`=` split). Every validation failure prints `Error: ...` naming the offending key/value plus valid options and exits 2 (unknown-adapter precedent); echoed values pass through `_sanitise` (T-02-09).

## Verification

- `uv run pytest -x -q`: 164 passed, 0 xfailed / 0 xpassed (27 RED tests flipped GREEN across commits 3d58c54 -> 7b036d0)
- `uv run ruff check` and `uv run pyright` (strict, incl. tests/perf executionEnvironment): clean
- Byte-identical regression (never xfailed): unfiltered `show events` lines equal the query_events-derived Phase 1 rendering before AND after the streaming rewrite
- Injection boundary: SQL-shaped values (`file='; DROP TABLE events;--`, `contains=' OR 1=1; ...`) return zero rows with exit 0; both tables intact afterwards; store remains the single SQL owner (no SQL text outside store.py)
- instr semantics: `contains=<NUM>% full` matches its group literally; `contains=d%full` (LIKE-style wildcard) matches nothing
- `sift show --help` documents the full grammar

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] ruff misparsed a `# noqa-rationale` comment as an invalid noqa directive**
- **Found during:** Task 2 verify
- **Issue:** a rationale comment starting with `# noqa-rationale` tripped ruff's noqa parser ("expected `:` followed by codes")
- **Fix:** reworded the comment so only the real `# noqa: S608` remains noqa-prefixed
- **Files modified:** src/sift/store.py
- **Commit:** 7b036d0

**2. [Rule 2 - Missing critical] `show events` never closed the store**
- **Found during:** Task 2 (streaming rewrite)
- **Issue:** the pre-existing events path lacked the try/finally close the clusters path had, leaving WAL sidecars (STORE-01 / Pitfall 4 gap)
- **Fix:** both show paths now share one try/finally `store.close()`
- **Files modified:** src/sift/cli.py
- **Commit:** 7b036d0

### Environmental (not a code issue)

**Perf gate red under external machine load — control run proves no regression.**
`uv run pytest -m perf` measured 66.7 s (budget 60 s) with system load average 12.4 and an unrelated user process consuming 8+ cores. A control run of the identical gate against pristine HEAD code (byte-identical ingest path to 02-02, which measured **19.3 s** on an idle machine) in a throwaway worktree measured **69.6 s** under the same load — the working-tree code (66.7 s) is within noise of pristine, and this plan's diff does not touch the ingest path at all (only `show` rendering and new filtered query methods). **Action for verifier/UAT:** re-run `uv run pytest -m perf` on an idle machine; expected ~19-25 s.

## STORE-04 Scope Note (flagged for verifier)

STORE-04's text covers inspecting events, clusters AND hypotheses. This plan delivers the **events and clusters targets**; the hypotheses target arrives with Phase 4's `show hypotheses`. REQUIREMENTS.md STORE-04 is ticked with this partial-scope note, mirroring 02-02's CLI-03 convention.

## Prohibition Status (flagged items)

- **Filters never alter or mask stored evidence:** filters are read-only SELECT queries built from constant snippets; `raw` and `message` are never selected by the filter paths (iter_event_rows omits raw entirely) and sanitisation applies at render time only — stored bytes stay verbatim.
- **No silent hiding on bad input:** every invalid key or value is a loud exit-2 error naming the valid options (asserted for unknown keys on both targets, `limit=abc`, `since=notatime`, `severity=catastrophic` listing all six severities, `min-count=-1`) — never an empty result set masquerading as "no matches".

## Human Verification Outstanding (end-of-phase UAT)

- `uv run sift show <case> events --filter severity=error --filter limit=5` and `uv run sift show <case> clusters --filter min-count=10` behave as documented in `--help` (plan task 2 human-check).
- Re-run `uv run pytest -m perf` on an idle machine (see environmental note above).

## Known Stubs

None introduced. `analyze`, `report`, `eval`, `doctor`, `show hypotheses` remain Phase 1 arrival stubs by design.

## Threat Flags

None — all new surface was in the plan's threat model (T-02-08 allowlist+parameterised filters, T-02-09 sanitised rendering/echoes, T-02-10 column-scoped streaming, T-02-SC no new packages).

## Self-Check: PASSED

Commits 3d58c54 and 7b036d0 present in git log; `_EVENT_FILTER_SQL`, `iter_event_rows` in store.py and `--filter` in cli.py confirmed on disk; default gate re-verified green (164 passed, ruff, pyright strict).
