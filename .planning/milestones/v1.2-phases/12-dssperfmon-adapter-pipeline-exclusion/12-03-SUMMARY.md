---
phase: 12-dssperfmon-adapter-pipeline-exclusion
plan: 03
subsystem: adapters
tags: [dssperfmon, registration, detection, sniff-collision, adr-0013, perf-01]
status: complete
requires:
  - sift.adapters.dssperfmon.DssperfmonAdapter (12-01, 12-02)
  - sift.adapters.base.ConfigurableAdapter (ADR 0006)
  - sift.adapters.detect / REGISTRY / SNIFF_THRESHOLD
  - tests/fixtures/dssperfmon/hartford_deny_slice.csv (12-01)
provides:
  - REGISTRY["dssperfmon"] — PDH-CSVs route by sniff with no --adapter override
  - docs/decisions/0013-dsserrors-qualified-mcm-sniff.md
  - tests/test_cli.py::test_ingest_perfmon_full_coverage
  - tests/test_cli.py::test_ingest_perfmon_idempotent
  - detection regression coverage extended to all five adapters
affects:
  - 12-04 (pipeline exclusion — perfmon events now actually reach the pipeline)
  - 13-* (episode correlation consumes the ingested per-sample Events)
  - any future adapter — the sole-claimant invariant now gates five adapters
tech-stack:
  added: []
  patterns:
    - REGISTRY entries are appended, never interleaved (iteration order feeds detect())
    - domain sniff markers must be qualified, not bare substrings (ADR 0013)
    - one data edit to _PHASE5_CASES/_DOMAIN_ADAPTERS extends three parametrised assertions at once
key-files:
  created:
    - docs/decisions/0013-dsserrors-qualified-mcm-sniff.md
  modified:
    - src/sift/adapters/__init__.py
    - src/sift/adapters/dsserrors.py
    - tests/test_adapters_detect.py
    - tests/test_cli.py
decisions:
  - dsserrors sniff markers qualified ("AvailableMCM"/"MCM Settings") because the bare "MCM" substring collided with the Total MCM Denial PDH counter (ADR 0013)
  - the sole-claimant invariant was kept as written, NOT relaxed to unique-maximum
  - idempotence asserts the event_id set, not the count — a count-only check passes if ids were regenerated
metrics:
  duration: ~35 min
  tasks: 2
  files: 4
  completed: 2026-07-20
---

# Phase 12 Plan 03: dssperfmon Registration and Detection Regression Summary

`DssperfmonAdapter` is the fifth registered adapter — PDH-CSVs route to it by sniff alone, all four
existing fixtures still route exactly where they did, and a real sniff collision the registration
exposed in the shipped `dsserrors` adapter was fixed at root rather than tested around.

## What Was Built

**The registration** (`8dd39ac`). One import plus one appended `REGISTRY` entry — SPEC §5.2's
self-containment rule holds exactly as the module docstring claims. `src/sift/cli.py` is untouched
(`git diff --name-only` confirms): it narrows on `ConfigurableAdapter` by `isinstance`, which
`DssperfmonAdapter` subclasses per ADR 0006, so `input_root`, `tz_overrides` and `last_stats` are
wired by registration alone. Appended rather than interleaved, since `REGISTRY` iteration order
feeds `detect()`'s scoring loop and appending is the change least able to perturb existing routing.

The detection suite was extended by appending one tuple to `_PHASE5_CASES` and one name to
`_DOMAIN_ADAPTERS`. All three parametrised assertions read those constants, so the single data edit
extended routes-to-own-adapter, beats-genericlog and no-cross-collision to the fifth adapter at once.
No new test function was written — one would have duplicated coverage the parametrisation provides.

**The collision fix** (`996cdc5`, ADR 0013 in `acabf7b`). See Deviations below.

**The CLI tests** (`ee0d885`). `test_ingest_perfmon_full_coverage` asserts exit 0, exactly 20 stored
events (one per sample row; the PDH header is metadata, never an Event per D-01) and a real `1.0`
coverage — the fixture has no malformed cells, so nothing degrades to the `severity="unknown"`
fallback. `test_ingest_perfmon_idempotent` runs ingest twice and asserts the stored `event_id` **set**
is identical, not merely the count: a count-only assertion still passes if ids were regenerated, and
stable ids under re-ingest are the actual determinism contract (`event_id = sha256(source_file,
byte_offset)[:16]`). Neither test passes `--adapter`, so both also exercise sniff-based routing end
to end. Both reuse the existing `_copy_fixture` helper and inherit the autouse network block and XDG
isolation from `conftest.py`.

## Deviations from Plan

### Escalated to a blocking decision (approved before implementation)

**1. [Rule 4 — Architectural] `dsserrors` sniff markers qualified; plan scope widened**

- **Found during:** Task 1, on the regression suite's very first run — which is precisely the risk
  the plan existed to cover.
- **Issue:** `test_phase5_no_cross_collision[dssperfmon]` failed with
  `assert ['dsserrors', 'dssperfmon'] == ['dssperfmon']`. `_SNIFF_STRINGS` in
  `src/sift/adapters/dsserrors.py` contained the bare substring `"MCM"`, matched against the first
  64 KB of content. Every PDH-CSV header enumerates its counter paths, including
  `\MicroStrategy Server Jobs(CastorServer)\Total MCM Denial` at byte 941 of the fixture — **the very
  counter PERF-05 tracks**. This is emitted by DSSPerformanceMonitor by default, so the collision is
  universal across real perfmon artefacts, not a fixture quirk.
- **Routing was never wrong.** `dssperfmon` scores 0.95 against `dsserrors`'s 0.80, a strict unique
  maximum, so PDH-CSVs routed correctly regardless and no existing fixture changed adapter. The
  failing property was the stricter sole-claimant invariant.
- **Why it was fixed rather than tolerated:** a PDH-CSV whose header does not match `dssperfmon`'s
  anchored `"(PDH-CSV 4.0)` prefix — truncated, byte-shifted, or a variant PDH version — scores
  `dssperfmon 0.00` / `dsserrors 0.80`, and would be silently parsed as a DSSErrors log instead of
  degrading to `genericlog`. That is the misrouting-hijack class threat T-12-11 names.
- **Fix:** `"MCM"` → `"AvailableMCM"`, `"MCM Settings"`. Both are attested DSSErrors-only spellings
  and neither is a legal substring of any PDH counter path. (`"MCM denial"` was rejected as a
  candidate: only capital-D case-sensitivity would separate it from `Total MCM Denial` — too fragile.)
- **Evidence the bare marker was redundant**, measured across the full local corpus of 11 real
  DSSErrors logs: all 11 match the `[Xxx.cpp:NNNN]` source-location regex, which alone returns 0.8;
  `hartford_Linux_snapshotDSSErrors (3).log` contains no `"MCM"` substring at all yet still detects;
  and all 11 still sniff 0.80 and route to `DsserrorsAdapter` after the change.
- **Process:** this modifies shipped v1.0 detection behaviour and was outside the plan's declared
  `files_modified`, so it was **not** auto-applied. Task 1 was left uncommitted and red, the
  counterfactual was measured and then reverted byte-identically (`git diff --quiet` confirmed), and
  the choice was escalated as a blocking decision with both options costed. Scope was explicitly
  widened on approval.
- **Files modified:** `src/sift/adapters/dsserrors.py`, `docs/decisions/0013-dsserrors-qualified-mcm-sniff.md`
- **Commits:** `996cdc5` (fix), `acabf7b` (ADR 0013)

**Rejected alternative, recorded:** relaxing the test to assert only the unique maximum was cheaper
and in-scope, but leaves the variant-header misrouting open and weakens a deliberate gate to
accommodate a genuine signature defect. **The sole-claimant assertion is kept exactly as written.**

### Plan-document inconsistency (recorded, not silently diverged)

The plan's threat model describes T-12-11's gate as *"the unique-maximum assertion in
`test_phase5_no_cross_collision`"*, but the test asserts sole-claimancy — that exactly one domain
adapter clears `SNIFF_THRESHOLD` — which is **strictly stronger** than what `detect()` guarantees.
`detect()` only needs a unique maximum; two adapters may both clear the threshold and routing stays
deterministic and correct.

This divergence is pre-existing and was surfaced, not introduced, by this plan. The test remains the
stricter of the two and is unchanged. Noting it here so a future reader does not "reconcile" the
prose by weakening the test — the discrepancy is exactly what caught the `dsserrors` collision, since
the unique-maximum reading would have passed silently.

### TDD Gate Note (Task 2)

Both Task 2 tests passed on first run. This is expected and not a skipped RED: Task 1 delivered the
behaviour they assert, so they are regression pins rather than new behaviour — the same situation
plan 12-02 recorded for its alignment test. Rather than accept a possibly-vacuous green, they were
verified load-bearing by counterfactual: with the `REGISTRY` entry removed, `genericlog` claims the
CSV and both tests fail (1 whole-file event instead of 20). `src/sift/adapters/__init__.py` was
restored byte-identically before commit (`git diff --quiet` confirmed).

## Verification

| Check | Result |
|-------|--------|
| `uv run pytest tests/test_adapters_detect.py` | 25 passed (4 domain adapters parametrised) |
| `uv run pytest -k no_cross_collision` | 4 passed — unique routing on every fixture |
| `uv run pytest tests/test_cli.py -k perfmon` | 2 passed |
| `uv run pytest` (full suite) | **559 passed, 8 deselected** (baseline 554 + 5 new) |
| `uv run ruff check` | clean |
| `uv run pyright` | 0 errors, 0 warnings |
| `grep -c dssperfmon src/sift/adapters/__init__.py` | 2 — exactly one import, one registry entry |
| `src/sift/cli.py` in the diff | **no** — registration alone wired everything |
| `pyproject.toml` unchanged | confirmed — no new dependency (T-12-SC) |
| 11 real DSSErrors logs after the sniff change | all still 0.80 → `DsserrorsAdapter` |
| Counterfactual: registration removed | both CLI tests fail (1 event, not 20) |

Files touched beyond the plan's three: `src/sift/adapters/dsserrors.py` and the new ADR, both under
the approved scope widening.

## Known Stubs

None. Perfmon events now flow through the full ingest path. Note that they currently also flow into
dedup/embed/cluster/salience — excluding them by source kind is PERF-03, plan 12-04's scope, and the
STATE.md blocker about cross-cutting regression risk to v1.0/v1.1 cluster output still stands.

## Threat Flags

None. The added sniff is an anchored fixed-length byte-prefix comparison (T-12-10 bounded as
planned), and the `dsserrors` change strictly narrows a matcher rather than widening any surface.

## Self-Check: PASSED

- FOUND: `src/sift/adapters/__init__.py`
- FOUND: `src/sift/adapters/dsserrors.py`
- FOUND: `docs/decisions/0013-dsserrors-qualified-mcm-sniff.md`
- FOUND: `tests/test_adapters_detect.py`
- FOUND: `tests/test_cli.py`
- FOUND commits: `996cdc5`, `acabf7b`, `8dd39ac`, `ee0d885`
