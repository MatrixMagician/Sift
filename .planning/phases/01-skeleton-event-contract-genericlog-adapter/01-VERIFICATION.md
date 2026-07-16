---
phase: 01-skeleton-event-contract-genericlog-adapter
verified: 2026-07-16T18:30:00Z
status: passed
human_verification_resolved: 2026-07-16 — all 4 flagged prohibitions signed off by user (see 01-UAT.md, 4/4 passed; symlink skip-with-record explicitly accepted as satisfying the no-silent-skips intent)
score: 31/31 must-haves verified
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "Prohibition (judgment-tier, flagged-unverified): zero network egress — confirm no HTTP client dependency exists and no module under src/sift/ opens a socket"
    expected: "Runtime deps are exactly pydantic/typer/zstandard; no socket/http/urllib/requests/httpx import anywhere in src/; autouse socket guard active in every test"
    why_human: "NON-AUTHORITATIVE LLM-judge verdict: HOLDS (deps verified in pyproject.toml; grep of src/ found zero socket/HTTP imports; conftest.py _no_network autouse guard covered all 108 passing tests). Judgment-tier prohibition with no wired test enforcement — per policy it must be human-resolved, never silently passed."
  - test: "Prohibition (judgment-tier): event_id purity — confirm event_id incorporates nothing beyond (source_file, byte_offset)"
    expected: "sha256(source_file + NUL + byte_offset)[:16] only; no case_id, clock, or randomness"
    why_human: "NON-AUTHORITATIVE LLM-judge verdict: HOLDS (models.py:44 is a single-expression hash over exactly those two inputs; test_acceptance_cross_case_determinism behaviourally proves case-independence; test_event_id_golden_value pins f7fdcb4b3de90265, confirmed live). Flagged for human sign-off as a frozen-contract prohibition."
  - test: "Prohibition (judgment-tier): sift ingest never silently skips a file — every file appears in the per-file report; failures are loud with non-zero exit"
    expected: "Failed files print ERROR <file>, persist an error record in parse_coverage meta, and force exit 1; symlinks skip LOUDLY (printed + persisted), never silently"
    why_human: "NON-AUTHORITATIVE LLM-judge verdict: HOLDS (cli.py:188-227 per-file try/except with loud error, persisted failure record, exit 1; review fixes WR-02/WR-04 added tests test_ingest_skips_symlinks_loudly_never_follows and test_failed_file_recorded_in_parse_coverage_meta, both passing). Note the deliberate design choice: symlinks are skipped (not followed) as a trust-boundary measure — loud and persisted, but a human should confirm skip-with-record satisfies the prohibition's intent."
  - test: "Prohibition (judgment-tier): parser never fabricates a severity or timestamp"
    expected: "Unrecognised severities stay 'unknown'; unparseable timestamps stay None with ts_confidence 'missing'"
    why_human: "NON-AUTHORITATIVE LLM-judge verdict: HOLDS (genericlog._severity returns 'unknown' when no token matches — no default guess; unparseable regions get ts=None/'missing'; test_format_all_ts_aware_utc_or_none and the coverage test group pass). Flagged per judgment-tier prohibition policy."
---

# Phase 1: Skeleton, Event Contract & genericlog Adapter — Verification Report

**Phase Goal:** A user can turn a directory of ordinary logs into a queryable case of canonical, deterministic events — nothing dropped silently
**Verified:** 2026-07-16T18:30:00Z
**Status:** human_needed (all automated checks passed; 4 judgment-tier prohibitions flagged for human resolution)
**Re-verification:** No — initial verification
**Mode:** MVP (user-story goal; User Flow Coverage below)

## User Flow Coverage (MVP mode)

User story: *As a support engineer with a directory of raw diagnostic logs, I want to turn it into a queryable case of canonical, deterministic events, so that nothing is dropped silently and every event can later be cited as evidence.*

| Step | Expected | Evidence | Status |
|------|----------|----------|--------|
| `sift new vcase --input <dir>` | Case created, exit 0 | Live run: "Created case 'vcase' for …", exit 0 | ✓ |
| `sift ingest vcase` | Canonical events, per-file coverage printed | Live run: "app.log  coverage 100.0%  3 events  3 new", exit 0 | ✓ |
| `sift ingest vcase` (again) | Zero new events (idempotent) | Live run: "3 events  0 new / Total: 0 new events", exit 0 | ✓ |
| `sift show vcase events` | 16-hex deterministic IDs, ts, severity, file:line, message | Live run: three 16-hex IDs, aware-UTC ts, error/warn/info severities, continuation line grouped into event 2 (line 4 offset confirms) | ✓ |
| Outcome: nothing dropped silently | Every byte attributed; failures loud | Span-partition invariant test across 7 encodings; per-file error path + persisted failure records; coverage formula bounded < 100% in acceptance test | ✓ |
| Outcome: events citable as evidence | Deterministic identity | Golden `event_id("app.log", 12345) == "f7fdcb4b3de90265"` confirmed live; cross-case determinism test passes | ✓ |

## Goal Achievement

### Observable Truths — ROADMAP Success Criteria (contract)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC1 | `sift new` + `sift ingest` on a fixture yields canonical events with deterministic IDs and per-file coverage ≥ 99% | ✓ VERIFIED | Live e2e run above; `test_acceptance_coverage_99` asserts ≥ 99.0 AND < 100.0 (metric is real, not vacuous) — passing in the 108-test suite |
| SC2 | Re-running `sift ingest` adds zero new events | ✓ VERIFIED | Live run: "0 new"; `test_acceptance_idempotent_reingest`, `test_reingest_adds_zero_events`, `test_reingest_idempotent` (store-level INSERT OR IGNORE with total_changes delta, store.py:120-150) |
| SC3 | Low-confidence files fall back to genericlog; `--adapter glob=name` overrides; unparseable regions surface as severity="unknown" | ✓ VERIFIED | `detect()` implements override-first → threshold 0.5 → tie/below-threshold fallback (adapters/__init__.py:54-85); tests: `test_all_below_threshold_falls_back_to_genericlog`, `test_tie_at_max_falls_back_to_genericlog`, `test_override_beats_losing_sniff_score`, `test_coverage_leading_unknown_region_hand_computed` |
| SC4 | Multi-line records ingest as single events; gzip/zstd inputs work without manual decompression | ✓ VERIFIED | `test_multiline_stack_trace_is_one_event`; 7 compressed tests incl. multi-member gzip and multi-frame zstd byte-offset-identical to plain (`read_across_frames=True`, base.py:62); acceptance fixture includes a `.gz` file through the CLI path |
| SC5 | Timestamps normalise to UTC with ts_confidence (per-node tz override); config resolves flags > SIFT_* env > config.toml > defaults | ✓ VERIFIED | `to_utc()` + ladder (genericlog.py:91-200); tz-override tests + `test_config_timezones_reach_adapter_and_events` (end-to-end); precedence matrix `test_defaults_when_no_config_anywhere` → `test_flag_beats_env` (all four adjacent pairs); `test_data_dir_flag_beats_env` through CliRunner |

### Observable Truths — Plan-level must_haves (deduplicated against SCs)

| # | Truth (plan) | Status | Evidence |
|---|--------------|--------|----------|
| 1 | Help lists exactly seven subcommands (01-01) | ✓ VERIFIED | Live `sift --help` shows new, ingest, analyze, report, show, eval, doctor |
| 2 | Autouse socket guard blocks network in tests (01-01) | ✓ VERIFIED | conftest.py:34-50 patches `socket.socket.connect` to raise, `autouse=True`; active across all 108 passing tests |
| 3 | Autouse XDG isolation + SIFT_* env clearing (01-01) | ✓ VERIFIED | conftest.py:15-31 redirects XDG_DATA_HOME/XDG_CONFIG_HOME to tmp_path, deletes SIFT_* vars |
| 4 | Walking-skeleton e2e test exists (01-01) | ✓ VERIFIED | `test_walking_skeleton_happy_path` collected and passing |
| 5 | ruff + pyright exit 0 (01-01/01-05 gate) | ✓ VERIFIED | Ran both: "All checks passed!" / "0 errors, 0 warnings, 0 informations" |
| 6 | Golden `event_id("app.log", 12345) == "f7fdcb4b3de90265"` (01-02) | ✓ VERIFIED | Confirmed live via python -c; `test_event_id_golden_value` passing |
| 7 | Deleting the case directory deletes the case entirely, D-04 (01-02) | ✓ VERIFIED | Structural: all per-case state (case.db + WAL/SHM) lives under data_dir/cases/<name>/ (store.py:31-38, `test_case_db_path_layout`); no cross-case index exists anywhere in src/ |
| 8 | query_events deterministic order: ts NULLs last, source_file, line_start (01-02) | ✓ VERIFIED | `ORDER BY ts IS NULL, ts, source_file, line_start` (store.py:156); `test_query_events_deterministic_order` |
| 9 | `sift show <case> events` prints stored events (01-02) | ✓ VERIFIED | Live run output above; `test_acceptance_show_events_renders_all` asserts rendered ID set == stored ID set |
| 10 | **Backstop:** all inserts + coverage meta write in ONE transaction; interrupted ingest leaves complete result or nothing (01-02) | ✓ VERIFIED | Explicit evidence chain: single `with store.transaction():` wraps the whole file loop AND `set_meta("parse_coverage", …)` (cli.py:161-223); BEGIN IMMEDIATE/COMMIT/ROLLBACK-on-BaseException (store.py:108-118); behavioural test `test_transaction_rolls_back_on_error` raises mid-transaction after insert + meta write and asserts BOTH are gone — the invariant is exercised, not just present |
| 11 | Timestamp ladder: ISO variants, syslog RFC3164 w/ mtime year, epoch s/ms window, CLF (01-03) | ✓ VERIFIED | Ladder at genericlog.py:105-175; 8 `-k format` tests incl. `test_format_epoch_window_rejects_out_of_range` and the fromisoformat-greediness guard `test_format_iso_greedy_prefix_not_a_timestamp` |
| 12 | 256-line/64 KB caps split into severity-unknown continuation events (01-03) | ✓ VERIFIED | MAX_EVENT_LINES/MAX_EVENT_BYTES (genericlog.py:38-39), cap-breach branch at 404-416; `test_multiline_cap_256_lines_splits`, `test_multiline_cap_64kb_splits` |
| 13 | Span-partition invariant: every decompressed byte in exactly one event (01-03) | ✓ VERIFIED | `test_coverage_span_partition_invariant_all_encodings` parametrised over utf-8, utf-8-sig, utf-16-le/be BOM, cp1252, invalid-bytes, crlf — 7 variants passing |
| 14 | Empty file: zero events, coverage 1.0, no error (01-03) | ✓ VERIFIED | ParseStats.coverage returns 1.0 for total_bytes==0 (base.py:48-50); `test_coverage_empty_file`, `test_empty_file_detects_as_genericlog` |
| 15 | Encoding edge cases: UTF-16LE/BE BOM, cp1252, invalid bytes, CRLF parse with correct byte offsets (01-03) | ✓ VERIFIED | 7 `-k encoding` tests incl. the review-fix regression `test_encoding_utf16le_fake_newline_across_char_boundary_not_split` (unit-aligned newline scan, genericlog.py:230-276) |
| 16 | **Backstop:** corrupt/truncated compressed file → loud per-file error, never silent skip (01-03) | ✓ VERIFIED | Explicit behavioural evidence: `test_compressed_corrupt_zstd_raises` (adapter level) + `test_ingest_corrupt_compressed_file_fails_loudly_but_continues` (CLI level, CR-01 fix: detect() moved inside per-file try; exit 1, ERROR line printed, good files survive) |
| 17 | Detection deterministic: insertion-order registry, tie → genericlog (01-04) | ✓ VERIFIED | Documented + implemented (adapters/__init__.py:69-85); `test_tie_at_max_falls_back_to_genericlog`, `test_first_matching_override_glob_wins` |
| 18 | sniff operates on first 65536 DECOMPRESSED bytes (01-04) | ✓ VERIFIED | read_head → open_bytes (base.py:67-70); `test_compressed_sniff_on_decompressed_content`, `test_read_head_returns_decompressed_content` |
| 19 | Empty-input semantics: empty dir warn-but-create; ingest 0 files exit 0 (01-04) | ✓ VERIFIED | cli.py:97-98, 152-155; `test_new_warns_but_creates_on_empty_input_dir`, `test_ingest_empty_input_dir_reports_zero_files_exit_0` |
| 20 | show strips control chars — no terminal escape injection (01-04) | ✓ VERIFIED | `_sanitise` strips C0/DEL/C1/Cf (cli.py:30-49), applied to message, source_file, relpath, and exception text (CR-02/WR-06 fixes); `test_show_strips_terminal_escapes`, `test_hostile_filename_escapes_never_reach_terminal`, `test_show_strips_bidi_and_zero_width_characters` |
| 21 | config.timezones reaches the adapter (D-05 wiring) (01-04) | ✓ VERIFIED | cli.py:183-185 sets `adapter.tz_overrides = dict(config.timezones)` before parse; end-to-end `test_config_timezones_reach_adapter_and_events` |
| 22 | Unknown adapter name errors listing registered names (01-04) | ✓ VERIFIED | cli.py:142-150 + parse_adapter_overrides validation; `test_unknown_adapter_name_fails_listing_registered`, `test_parse_adapter_overrides_unknown_name_lists_registered` |
| 23 | Full M1 flow as one test: new → ingest → show, second ingest zero (01-05) | ✓ VERIFIED | 4 acceptance tests passing; live CLI run reproduced the flow independently |
| 24 | Cross-case event_id determinism (01-05) | ✓ VERIFIED | `test_acceptance_cross_case_determinism`: identical sorted ID sets across cases "alpha"/"beta" |
| 25 | Three ADRs in docs/decisions/ (01-05) | ✓ VERIFIED | All three files exist, each contains "## Decision"; 0001 contains "Typer", 0002 "WeasyPrint", 0003 "drain3" |
| 26 | `sift ingest --help` documents snapshot semantics (01-05) | ✓ VERIFIED | Live `ingest --help` contains "snapshot" (2 hits); docstring cli.py:111-118 documents rename limitation |

**Score:** 31/31 truths verified (5 roadmap SCs + 26 deduplicated plan truths; 0 present-but-behaviour-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `pyproject.toml` | uv project, sift entry point, quality-gate config | ✓ VERIFIED | Contains `sift.cli:app`; deps typer/pydantic/zstandard only; strict pyright config effective (0 errors) |
| `src/sift/cli.py` | 7 subcommands, real new/ingest/show bodies | ✓ VERIFIED | 278 lines; new/ingest/show fully implemented; analyze/report/eval/doctor stub-by-design (arrive Phases 3-7, exit 1 naming their phase — planned, not gaps) |
| `src/sift/models.py` | Frozen Event (16 fields) + canonical event_id | ✓ VERIFIED | `@dataclass(frozen=True)`, all 16 SPEC §5.1 fields in order; `test_event_is_frozen` |
| `src/sift/adapters/base.py` | Adapter Protocol, open_bytes, read_head, ParseStats | ✓ VERIFIED | `class Adapter(Protocol)` with exact SPEC §5.2 signatures; `read_across_frames=True` present |
| `src/sift/store.py` | CaseStore, migrations, INSERT OR IGNORE, deterministic query | ✓ VERIFIED | PRAGMA user_version runner; all SQL parameterised (only interpolations are a module-constant column list and an int-cast migration version) |
| `src/sift/adapters/genericlog.py` | Full ladder, encodings, caps, coverage, tz | ✓ VERIFIED | 451 lines; contains MAX_EVENT_LINES; one deliberate `ponytail:` ceiling comment (cap-boundary force-split, documented and even-cap-safe) |
| `src/sift/adapters/__init__.py` | detect() + parse_adapter_overrides + REGISTRY | ✓ VERIFIED | `def detect`, `def parse_adapter_overrides` present |
| `src/sift/config.py` | SiftConfig (data_dir, timezones, adapters) + layered load_config | ✓ VERIFIED | tomllib import, no pydantic_settings; `extra="forbid"` (WR-05); ZoneInfo validation |
| `tests/conftest.py` | XDG isolation + socket guard autouse | ✓ VERIFIED | Two `autouse=True` fixtures |
| `tests/test_models.py` | Golden-value + frozen-contract tests | ✓ VERIFIED | Contains `f7fdcb4b3de90265` |
| `tests/test_store.py` | Idempotency + schema + ordering + rollback | ✓ VERIFIED | `test_reingest_idempotent` present |
| `tests/test_genericlog.py` | 6 test groups (format/timezone/multiline/coverage/encoding/compressed) | ✓ VERIFIED | 38 tests, all groups selectable by `-k` |
| `tests/test_config.py` / `test_adapters_detect.py` | Precedence matrix / detection tests | ✓ VERIFIED | 12 + 13 tests respectively (both exceed plan minimums) |
| `tests/test_acceptance.py` | M1 acceptance: ≥99% bounded coverage, idempotency, determinism | ✓ VERIFIED | Contains "99"; coverage assertion bounded ≥99.0 AND <100.0 |
| `docs/decisions/000{1,2,3}-*.md` | Three ADRs | ✓ VERIFIED | Exist with Decision sections and required content |
| `LICENSE` | Apache-2.0 text | ✓ VERIFIED | Present, 11.1K |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| pyproject.toml | src/sift/cli.py | `[project.scripts] sift = sift.cli:app` | ✓ WIRED | `uv run sift` executes live |
| tests/test_cli.py, test_acceptance.py | cli.app | CliRunner | ✓ WIRED | Imports + invocations present, tests pass |
| genericlog.py | models.py | `event_id(relpath, rec.offset)` | ✓ WIRED | genericlog.py:344 |
| cli.py | store.py | `with store.transaction():` around inserts + coverage meta | ✓ WIRED | cli.py:161-223 |
| cli.py | adapters/__init__.py | `adapters.detect(path, relpath, overrides)` + REGISTRY | ✓ WIRED | cli.py:143, 179 |
| genericlog.py | base.py | `open_bytes` / `read_head` / `ParseStats` | ✓ WIRED | genericlog.py:28, 308, 331, 367 |
| cli.py | config.py | `load_config({"data_dir": data_dir})` in all three implemented commands | ✓ WIRED | cli.py:76, 119, 242 |
| config.py | ~/.config/sift/config.toml | `tomllib.loads` when file exists | ✓ WIRED | config.py:50-55, loud error on malformed TOML |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|--------------------|--------|
| `sift ingest` output | coverage/event counts | GenericLogAdapter.last_stats ← real byte-level parse | Yes (live run: real counts, real coverage) | ✓ FLOWING |
| `sift show events` | query_events() rows | SQLite events table ← insert_events during ingest | Yes (live run: real events with parsed ts/severity) | ✓ FLOWING |
| parse_coverage meta | per-file dict | ParseStats + error/skip records | Yes (persisted incl. failures, WR-04) | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full quality gate | `uv run pytest -q && uv run ruff check && uv run pyright` | 108 passed; All checks passed; 0 errors/warnings | ✓ PASS |
| E2E: new → ingest → re-ingest → show | live CLI run in scratchpad | exit 0 each; 3 events, 0 new on re-ingest; 16-hex IDs; continuation line grouped | ✓ PASS |
| Golden event_id | `python -c "…event_id('app.log', 12345)"` | `f7fdcb4b3de90265` | ✓ PASS |
| Seven subcommands | `sift --help` | all 7 present | ✓ PASS |
| Snapshot semantics documented | `sift ingest --help \| grep -ci snapshot` | 2 | ✓ PASS |
| Zero-egress dep surface | pyproject deps + src import grep | pydantic/typer/zstandard only; no socket/HTTP imports | ✓ PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh` probes exist in this project and no plan declares any — SKIPPED (not applicable).

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|----------------|-------------|--------|----------|
| INGST-01 | 01-01, 01-02, 01-05 | new + ingest → canonical events, deterministic IDs | ✓ SATISFIED | Live e2e + walking-skeleton + acceptance tests |
| INGST-02 | 01-02, 01-05 | Idempotent re-ingest | ✓ SATISFIED | Live "0 new" + 3 dedicated tests |
| INGST-03 | 01-04 | sniff auto-detection, threshold ≥ 0.5, fallback, --adapter override | ✓ SATISFIED | detect() + 13 detection tests |
| INGST-04 | 01-03 | ISO/syslog/epoch parsing, continuation grouping | ✓ SATISFIED | Format test group + multiline group |
| INGST-05 | 01-03, 01-05 | Unknown regions as events, parse-coverage metric | ✓ SATISFIED | Coverage group + bounded ≥99/<100 acceptance assertion |
| INGST-06 | 01-03 | Multi-line records as one event | ✓ SATISFIED | Stack-trace test + cap tests |
| INGST-10 | 01-03 | gzip/zstd without manual decompression | ✓ SATISFIED | 7 compressed tests incl. magic-not-extension |
| INGST-11 | 01-03 | UTC normalisation, tz overrides, ts_confidence | ✓ SATISFIED | Timezone group + end-to-end config wiring test |
| CLI-01 | 01-01, 01-04 | 7 subcommands, config precedence chain | ✓ SATISFIED | Live help + full precedence matrix tests |

Orphaned requirements: NONE — REQUIREMENTS.md maps exactly these 9 IDs to Phase 1; all are claimed by plans and verified.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | No TBD/FIXME/XXX/TODO/HACK markers in src/ or tests/ | — | Clean |
| src/sift/adapters/genericlog.py | 260 | `ponytail:` deliberate-ceiling comment (cap-boundary force-split may bisect a UTF-16 newline) | ℹ️ Info | Documented, cap is even so alignment survives; region already severity-unknown |
| src/sift/cli.py | 254-278 | analyze/report/eval/doctor are stubs exiting 1 | ℹ️ Info | By design — each names its arrival phase; ROADMAP schedules them for Phases 3-7 |

Note (Info, no action): plan 01-04 text said `parse_adapter_overrides` splits on the FIRST equals sign, but its own behaviour requirement ("a glob containing an equals sign survives") is only satisfiable by splitting on the LAST (adapter names never contain `=`). The implementation uses `rpartition`, documents the reasoning, and `test_parse_adapter_overrides_glob_with_equals_survives` proves the intended behaviour — an internally-contradictory plan clause resolved correctly.

### Human Verification Required

All four items are `must_haves.prohibitions` entries with `status: flagged-unverified` and no verification descriptor (judgment-tier). Per policy they carry NON-AUTHORITATIVE LLM-judge verdicts and must be human-resolved — never silently passed. All four verdicts are HOLDS; details in frontmatter. Summary:

1. **Zero network egress** (01-01) — deps are pydantic/typer/zstandard only; no socket/HTTP imports in src/; autouse socket guard active in all 108 tests. Judge: HOLDS.
2. **event_id purity** (01-02) — sha256 over (source_file, NUL, byte_offset) only; cross-case determinism behaviourally proven; golden value confirmed live. Judge: HOLDS.
3. **No silently skipped files** (01-02) — loud per-file errors, persisted failure/skip records, exit 1 on failure; symlinks skipped loudly by design (confirm this satisfies intent). Judge: HOLDS.
4. **No fabricated severity/timestamp** (01-03) — token-less severity stays "unknown"; unparseable ts stays None/"missing"; asserted by tests. Judge: HOLDS.

### Gaps Summary

No gaps. Every roadmap success criterion and every plan-level truth (including both backstop truths, which have explicit behavioural test evidence: `test_transaction_rolls_back_on_error` and `test_ingest_corrupt_compressed_file_fails_loudly_but_continues`) is verified against the current post-review-fix codebase (108 tests, ruff + pyright strict clean). The 9 code-review fixes (2 Critical, 7 Warning) from 01-REVIEW-FIX.md are all present in the code with their regression tests collected and passing. Status is `human_needed` solely because the four judgment-tier prohibitions require explicit human resolution per the flagged-unverified policy.

---

_Verified: 2026-07-16T18:30:00Z_
_Verifier: Claude (gsd-verifier)_
