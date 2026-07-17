---
phase: 05-domain-adapters-journald-dsserrors-eustack
plan: 03
subsystem: adapters
tags: [adapters, ingest, journald, jsonl, coverage, severity, python]

# Dependency graph
requires:
  - phase: 05-domain-adapters-journald-dsserrors-eustack
    plan: 01
    provides: "base.ConfigurableAdapter (input_root/tz_overrides/last_stats), ParseStats, open_bytes/read_head"
  - phase: 01-skeleton-event-contract-genericlog-adapter
    provides: "frozen Event/event_id, genericlog byte-line discipline, ParseStats coverage metric"
provides:
  - "JournaldAdapter(ConfigurableAdapter) — journalctl -o json JSONL -> one Event per line"
  - "_field_to_str journald value normaliser (string / null / int-array-with-NUL / value-array)"
  - "_severity + _PRIORITY_SEVERITY exhaustive PRIORITY 0-7 -> six-value CHECK-safe map"
  - "genericlog.byte_lines — private _byte_lines promoted public as the shared byte-split seam (force-split DoS cap)"
affects: [wave-3-cli-integration, adapters-registration, dsserrors-adapter, eustack-adapter]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Domain adapter = subclass ConfigurableAdapter; parse() splits bytes via shared byte_lines, one Event per JSONL line, offset += len(bline) for event_id determinism"
    - "_field_to_str: route every mapped journald field through a value normaliser so binary/NUL int-arrays decode instead of storing a Python list repr (Pitfall 1)"
    - "Exhaustive severity map defaulting to unknown keeps the store severity CHECK inviolable regardless of input PRIORITY"

key-files:
  created:
    - src/sift/adapters/journald.py
    - tests/test_journald.py
    - tests/fixtures/journald/basic.json
    - tests/fixtures/journald/field_types.json
  modified:
    - src/sift/adapters/genericlog.py

key-decisions:
  - "Reused genericlog's byte-line splitter instead of a plain b'\\n' split so a monster single JSON line inherits the MAX_EVENT_BYTES force-split DoS cap (T-05-10); promoted _byte_lines -> public byte_lines (it is a genuine shared byte-split seam, not adapter-private)"
  - "A blank/whitespace-only line is counted as covered (not unknown_fallback) — no data was lost — but still emitted as an event so the byte-span partition stays contiguous"
  - "_field_to_str kept module-private (matches the plan's key_links naming); tested directly with a narrow pyright reportPrivateUsage suppression, following the established test convention (test_store/test_llm_client/test_salience)"

requirements-completed: [INGST-07]

coverage:
  - id: J1
    description: "PRIORITY 0-7 -> six-value severity; missing/invalid/out-of-range -> unknown, never violating the store CHECK"
    requirement: "INGST-07"
    verification:
      - kind: unit
        ref: "tests/test_journald.py#test_priority_full_range_maps_to_six_value_set + test_priority_invalid_or_missing_maps_to_unknown + test_no_emitted_severity_outside_check_set"
        status: pass
    human_judgment: false
  - id: J2
    description: "__REALTIME_TIMESTAMP (us epoch) -> aware UTC exact; missing timestamp -> ts=None/missing but bytes covered"
    requirement: "INGST-07"
    verification:
      - kind: unit
        ref: "tests/test_journald.py#test_realtime_timestamp_becomes_utc_exact + test_missing_timestamp_is_covered_not_fallback"
        status: pass
    human_judgment: false
  - id: J3
    description: "_field_to_str normalises string/null/int-array(with embedded NUL)/value-array; MESSAGE never stored as a list repr"
    requirement: "INGST-07"
    verification:
      - kind: unit
        ref: "tests/test_journald.py#test_field_to_str_* + test_message_nul_from_fixture"
        status: pass
    human_judgment: false
  - id: J4
    description: "malformed/non-object line -> one severity=unknown event, bytes counted as unknown_fallback; bounded coverage (>=95 and <100) with contiguous span partition; event_id identical for plain vs gzip"
    requirement: "INGST-07"
    verification:
      - kind: unit
        ref: "tests/test_journald.py#test_malformed_line_becomes_unknown_and_byte_accounted + test_non_object_json_line_is_unknown + test_basic_fixture_coverage_bounded + test_event_id_plain_vs_gzip_identical"
        status: pass
    human_judgment: false
  - id: J5
    description: "sniff ~0.95 on a journald head with a signature key, 0.0 on non-journald / non-signature JSON"
    requirement: "INGST-07"
    verification:
      - kind: unit
        ref: "tests/test_journald.py#test_sniff_journald_head_high + test_sniff_plain_text_zero + test_sniff_non_signature_json_zero"
        status: pass
    human_judgment: false

# Metrics
duration: 20min
completed: 2026-07-18
status: complete
---

# Phase 5 Plan 03: journald Adapter Summary

**`JournaldAdapter` turns a `journalctl -o json` JSONL export into one canonical, severity-mapped, UTC-stamped `Event` per line — decoding binary/NUL-bearing MESSAGE fields via `_field_to_str`, byte-accounting every line for real coverage, and keeping `event_id` byte-offset deterministic across plain and gzip copies (INGST-07 at the adapter level).**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-07-18
- **Completed:** 2026-07-18
- **Tasks:** 2
- **Files:** 5 (4 created, 1 modified)

## Accomplishments
- `JournaldAdapter(ConfigurableAdapter)` (`name = "journald"`): splits the decompressed byte stream on `b"\n"` via the shared `byte_lines` seam, `json.loads` per line, and maps each object to one `Event` — `PRIORITY`→severity, `__REALTIME_TIMESTAMP`→UTC `ts`, `_SYSTEMD_UNIT`→component, `_PID`/`_COMM`→attrs, `_SYSTEMD_INVOCATION_ID`→session.
- `_field_to_str` value normaliser: string→verbatim, `null`→`None`, array-of-byte-ints→`bytes(...).decode(errors="replace")` (embedded NUL survives, never a list repr), value-array→newline-joined, int→str — the one genuinely journald-specific piece (Pitfall 1), plus a guard so a byte-int >255 falls through to the value-array join instead of raising.
- `_severity` + exhaustive `_PRIORITY_SEVERITY` (0/1/2→fatal, 3→error, 4→warn, 5/6→info, 7→debug); missing / non-numeric / out-of-range → `unknown`, so the store severity CHECK (store.py:150) can never be violated (Pitfall 4).
- Fail-soft coverage: a line failing `json.loads` or that is not a JSON object → one `severity="unknown"`, `ts=None` event whose bytes count as `unknown_fallback_bytes` ("nothing disappears", T-05-11). A valid entry lacking `__REALTIME_TIMESTAMP` still parses — its bytes are covered, not fallback.
- Determinism: byte offsets computed on the raw decompressed stream (`offset += len(bline)`), `event_id(relpath, line_offset)`; a plain and a gzip copy of the same export under the same relative name yield identical `event_id`s (Pitfall 6).
- `sniff`: first non-blank head line is a JSON object carrying a journald signature key (`__REALTIME_TIMESTAMP`/`__CURSOR`/`_BOOT_ID`) → `0.95`; not JSON / no signature → `0.0` (never collides with genericlog's `0.1`).
- Two handcrafted JSONL fixtures: `basic.json` (PRIORITY 0-7, a kernel entry with no `_SYSTEMD_UNIT`, a missing-timestamp entry, one malformed line → ~98.8% coverage, inside the bounded 95-100 band) and `field_types.json` (string / int-array-with-NUL / value-array / null / oversized-dropped-to-null MESSAGE).

## Task Commits

1. **Task 1: journald JSONL fixtures** — `106e138` (test)
2. **Task 2: JournaldAdapter sniff/parse/_field_to_str/severity (TDD RED→GREEN)** — `1b80a55` (feat)

## Files Created/Modified
- `src/sift/adapters/journald.py` — new: `JournaldAdapter`, `_field_to_str`, `_severity`, `_PRIORITY_SEVERITY`, `_parse_ts`.
- `tests/test_journald.py` — new: 19 tests (local `run_parse`/`parse_lines`/`assert_span_partition` harness mirroring test_genericlog).
- `tests/fixtures/journald/basic.json`, `tests/fixtures/journald/field_types.json` — new handcrafted JSONL fixtures.
- `src/sift/adapters/genericlog.py` — modified: `_byte_lines` → public `byte_lines` (rename + one call site); behaviour unchanged (genericlog suite stays green).

## Decisions Made
- **Reuse over reimplement for byte-splitting.** The plan text described a plain `b"\n"` split, but the threat register (T-05-10) requires the genericlog force-split DoS cap. Reusing genericlog's splitter satisfies both; promoting `_byte_lines` to public `byte_lines` reflects that it is a genuine shared seam (like `open_bytes`/`read_head` in base), not adapter-private.
- **Blank lines are covered, not lost.** A whitespace-only line carries no event data, so it is counted as covered while still emitting an event to keep the byte-span partition contiguous (the fixtures contain none; this is robustness for untrusted input).
- **`_field_to_str` stays private + directly tested** with a narrow `# pyright: ignore[reportPrivateUsage]`, matching the plan's `key_links` naming and the existing test convention (test_store, test_llm_client, test_salience all do this for helpers under test).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Promoted `genericlog._byte_lines` → public `byte_lines`**
- **Found during:** Task 2 (pyright gate)
- **Issue:** Importing the private `_byte_lines` across modules failed pyright strict (`reportPrivateUsage`); a plain `b"\n"` split (the plan's literal wording) would not inherit the `MAX_EVENT_BYTES` force-split DoS cap the threat register (T-05-10) mandates.
- **Fix:** Renamed `_byte_lines` → `byte_lines` in genericlog (definition + its single call site) and imported the public name; it is a legitimate shared byte-split seam. genericlog behaviour and tests unchanged.
- **Files modified:** src/sift/adapters/genericlog.py, src/sift/adapters/journald.py
- **Commit:** 1b80a55

No architectural changes. `adapters/__init__.py` left untouched (registration + e2e ingest is the Wave-3 integration plan's job).

## Issues Encountered
None beyond the gate fixes above (all resolved before the Task 2 commit).

## Known Stubs
None. The adapter is fully wired; registration and the end-to-end `sift ingest` slice are deliberately deferred to the Wave-3 integration plan per the plan's scope.

## Threat Flags
None. No new network, auth, or filesystem surface — stdlib `json`/`datetime` only, reading files already inside the case input dir.

## User Setup Required
None — zero new dependencies (stdlib only).

## Next Phase Readiness
- INGST-07 satisfied at the adapter level: journald JSONL → severity/component/attrs/session/ts Events with real, non-vacuous coverage.
- `byte_lines` is now the public shared byte-split seam the dsserrors/eustack adapters can reuse.
- Wave-3 owns `adapters/__init__.py` registration and the CliRunner e2e ingest slice.

## Self-Check: PASSED

All four created files and the modified genericlog.py exist on disk; both task commits (`106e138`, `1b80a55`) are present in `git log`. Full M5 gate: **332 passed, 2 deselected** (pre-existing live-UAT markers), ruff clean, pyright 0 errors/0 warnings.

---
*Phase: 05-domain-adapters-journald-dsserrors-eustack*
*Completed: 2026-07-18*
