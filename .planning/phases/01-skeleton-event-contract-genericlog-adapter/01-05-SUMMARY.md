---
phase: 01-skeleton-event-contract-genericlog-adapter
plan: 05
subsystem: docs-and-acceptance
tags: [adrs, m1-gate, acceptance-tests, snapshot-semantics]

requires:
  - 01-03 (genericlog coverage semantics, gzip parity)
  - 01-04 (full CLI: config precedence, detection, hardening)
provides:
  - docs/decisions/ seeded with the three research-resolved SPEC §10 ADRs (D-02)
  - "`sift ingest --help` documents the snapshot contract incl. the renamed-file duplicate limitation (INGST-02 scope)"
  - M1 acceptance suite proving coverage >= 99% (bounded < 100%), idempotent re-ingest, cross-case event_id determinism, show-events rendering
  - Green milestone gate — Phase 2 is unblocked per SPEC §8
affects: [phase-2, phase-5, phase-6]

tech-stack:
  added: []
  patterns:
    - "ADR format: Status / Date / Answers / Context / Decision / Consequences, citing SPEC §10 question and research date"
    - "Acceptance fixture pins coverage strictly between 99% and 100% via a <1% unparseable preamble — the metric cannot pass vacuously"

key-files:
  created:
    - docs/decisions/0001-typer-over-argparse.md
    - docs/decisions/0002-weasyprint-pdf-extra.md
    - docs/decisions/0003-hand-rolled-masking-over-drain3.md
    - tests/test_acceptance.py
  modified:
    - src/sift/cli.py

key-decisions:
  - "ADR 0001: Typer 0.27.x over argparse (SPEC §10 Q1 / D-01) — typed params under pyright strict, CliRunner testing; typer-slim then argparse as fallbacks"
  - "ADR 0002: WeasyPrint behind sift[pdf] optional extra with URL fetching disabled, implementation deferred to Phase 6; ReportLab rejected (no Markdown/HTML rendering)"
  - "ADR 0003: hand-rolled volatile-token masking over drain3 (dormant since 2022, Python <= 3.11 metadata, non-deterministic learning vs Sift's determinism constraint)"
  - "Acceptance coverage assertion is bounded (>= 99.0 and < 100.0): the fixture's 2-line preamble is real unparsed bytes, proving the metric is computed, not defaulted"

patterns-established:
  - "Acceptance tests read event_ids straight from CaseStore (bypassing the CLI) so row-count and determinism claims are store-truth, not stdout parsing"

requirements-completed: [INGST-01, INGST-02, INGST-05]

coverage:
  - id: D1
    description: "Three ADRs exist with ## Decision headings; `sift ingest --help` contains 'snapshot' and the renamed-file limitation"
    requirement: "INGST-02 (documentation disposition)"
    verification:
      - kind: other
        ref: "ls docs/decisions/*.md; uv run sift ingest --help | grep -i snapshot"
        status: pass
    human_judgment: false
  - id: D2
    description: "Per-file coverage printed by ingest, all files >= 99.0%, app.log strictly < 100.0% (preamble is real unparsed bytes)"
    requirement: "INGST-05"
    verification:
      - kind: e2e
        ref: "uv run pytest tests/test_acceptance.py::test_acceptance_coverage_99"
        status: pass
    human_judgment: false
  - id: D3
    description: "Second ingest reports 'Total: 0 new events', per-file new counts all 0, CaseStore row count unchanged"
    requirement: "INGST-02"
    verification:
      - kind: e2e
        ref: "uv run pytest tests/test_acceptance.py::test_acceptance_idempotent_reingest"
        status: pass
    human_judgment: false
  - id: D4
    description: "Same input layout into two cases yields identical sorted event_id lists (identity = source_file + byte_offset, never case_id); show events renders every stored event with its 16-hex ID"
    requirement: "INGST-01"
    verification:
      - kind: e2e
        ref: "uv run pytest tests/test_acceptance.py::test_acceptance_cross_case_determinism and ::test_acceptance_show_events_renders_all"
        status: pass
    human_judgment: false
  - id: D5
    description: "Full M1 gate green"
    verification:
      - kind: other
        ref: "uv run pytest (98 passed); uv run ruff check; uv run pyright — all exit 0"
        status: pass
    human_judgment: false

duration: 8min
completed: 2026-07-16
status: complete
---

# Phase 01 Plan 05: ADRs, Snapshot Semantics & M1 Acceptance Summary

**Phase 1 closed: three docs/decisions/ ADRs (Typer over argparse, WeasyPrint behind sift[pdf], hand-rolled masking over drain3), the snapshot contract documented in `sift ingest --help`, and a four-test M1 acceptance suite proving bounded >=99% coverage, idempotent re-ingest and cross-case event_id determinism — full gate green at 98 tests**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-07-16T16:53:48Z
- **Completed:** 2026-07-16T17:01:00Z
- **Tasks:** 2 (both auto)
- **Files modified:** 5

## Accomplishments

- `docs/decisions/` seeded per D-02 with a consistent Status / Context / Decision / Consequences format, each ADR citing the SPEC §10 question it answers and the research date (2026-07-16): 0001 Typer 0.27.x over argparse; 0002 WeasyPrint behind a `sift[pdf]` optional extra with URL fetching disabled, deferred to Phase 6; 0003 hand-rolled volatile-token masking over drain3
- `sift ingest --help` now states the full snapshot contract: a case is one snapshot of artefacts; re-collect changed inputs into a new case; new files add events and renamed files produce duplicates (documented INGST-02 limitation — event identity is source_file + byte_offset within one snapshot)
- `tests/test_acceptance.py` proves SPEC §8 M1 end-to-end via CliRunner on a realistic fixture: ~200 ISO 8601 lines across all five severity tokens (FATAL/ERROR/WARN/INFO/DEBUG), a 12-line stack trace under one timestamp, indented continuation lines, a 2-line unparseable preamble under 1% of file bytes, plus a gzip-compressed second log
- Coverage assertion is bounded — >= 99.0 and < 100.0 for app.log — so the metric is demonstrably computed from real unparsed bytes, never vacuously 100%
- Idempotency proven both from stdout ("Total: 0 new events", per-file `0 new`) and from a direct CaseStore row count; cross-case determinism proven by ingesting the identical layout into two cases and comparing sorted event_id lists read straight from each store
- Full M1 gate green: 98 passed, `ruff check` clean, `pyright` strict clean — Phase 2 is unblocked

## Task Commits

Each task was committed atomically:

1. **Task 1: Seed docs/decisions/ ADRs and snapshot-semantics documentation** — `98fc12b` (docs)
2. **Task 2: M1 acceptance suite — >=99% coverage fixture, idempotency, cross-case determinism** — `b1e0371` (test)

## Files Created/Modified

- `docs/decisions/0001-typer-over-argparse.md` — D-01 rationale, dependency cost, typer-slim/argparse fallback ladder
- `docs/decisions/0002-weasyprint-pdf-extra.md` — SPEC §10 Q2; ReportLab rejection grounds; zero-egress note (URL fetching disabled); Phase 6 deferral
- `docs/decisions/0003-hand-rolled-masking-over-drain3.md` — drain3 dormancy/3.11 ceiling/determinism conflict; Phase 2 implementation pointer
- `src/sift/cli.py` — ingest docstring extended with the renamed-file duplicate limitation (help-text-only change; no behaviour altered)
- `tests/test_acceptance.py` — four acceptance tests with local fixture builders (conftest.py untouched, owned by 01-01)

## Decisions Made

- ADR contents follow STACK.md research verbatim rather than re-litigating: the ADRs are the auditable record of decisions already made (T-05-01 mitigation)
- Acceptance tests read event_ids directly from `CaseStore` (via `load_config({}).data_dir`, which resolves inside the conftest XDG sandbox) so determinism and row-count claims rest on store truth, not on parsing `show` output
- Task 2 carried `tdd="true"` but TDD_MODE is off per orchestrator config (established phase convention): the suite is test-only against already-built behaviour, landed in one `test(...)` commit — all four tests passed on first run, confirming plans 01-02..01-04 delivered the behaviour they claimed

## Deviations from Plan

None — plan executed as written. (The ingest docstring already contained the base snapshot sentence from plan 01-04; this plan added the new-files/renamed-files limitation the plan required. No residual ruff/pyright findings existed to fix.)

## TDD Gate Compliance

TDD_MODE is off for this phase (orchestrator config; consistent with plans 01-02..01-04). Task 2's `tdd="true"` flag was satisfied as a test-only task: the RED phase is inapplicable because the task adds acceptance tests for behaviour built and committed by earlier plans — a failing-first cycle would require reverting shipped code. Commit `b1e0371` is a `test(...)` commit.

## Known Stubs

No new stubs. Remaining intentional stubs carried from 01-04, all owned by later phases:

| Stub | File | Resolved by |
|------|------|-------------|
| analyze/report/eval/doctor exit 1 with arrival message | src/sift/cli.py | Phases 3–7 |
| Per-run adapter config set via `isinstance(…, GenericLogAdapter)` narrowing | src/sift/cli.py | Phase 5 |

## Threat Flags

None — this plan added documentation and tests only; no new code surface beyond help text. T-05-01 (repudiation of decisions) mitigated by the ADRs themselves.

## Issues Encountered

None. All four acceptance tests passed on the first run; both gates were green at each task boundary.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- SPEC §8 M1 gate is green (98 tests, ruff, pyright strict) — Phase 2 (case store scale + template dedup) may begin
- ADR 0003 already records the Phase 2 dedup approach (hand-rolled masking in `pipeline/dedup.py`)
- The acceptance fixture builder is a reusable pattern for Phase 2's 100 MB synthetic-log generator (M2 acceptance)

## Self-Check: PASSED

All five created/modified files exist on disk; both task commits (98fc12b, b1e0371) present in git log; each ADR contains exactly one `## Decision` heading; full gate `uv run pytest && uv run ruff check && uv run pyright` green (98 passed).

---
*Phase: 01-skeleton-event-contract-genericlog-adapter*
*Completed: 2026-07-16*
