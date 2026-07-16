---
phase: 02-case-store-template-dedup
verified: 2026-07-16T20:55:00Z
status: gaps_found
score: 20/24 must-haves verified
behavior_unverified: 3
overrides_applied: 0
gaps:
  - truth: "The write path never lets events appear or disappear silently — per-file failure contributes exactly the rows its coverage record claims"
    status: failed
    reason: "CR-01 (review Critical, confirmed live): a mid-parse failure after >=1 inserted batch (e.g. truncated .gz raising EOFError mid-stream) leaves up to N*5000 rows committed by the surrounding transaction while coverage meta records event_count: 0 and the Total line undercounts. sum(template_groups.count) != sum(parse_coverage event_counts) permanently; downstream phases will read false coverage claims. Introduced by 02-02's batched streaming (Phase 1's list() materialisation made parse failures insert nothing). Untested: the existing corrupt-archive test only exercises detect-time failure."
    artifacts:
      - path: "src/sift/cli.py"
        issue: "lines 239-267: batches inserted before the except branch are not rolled back; error coverage entry hardcodes event_count: 0"
    missing:
      - "Per-file SAVEPOINT in store.py (name is a code constant) wrapping the detect+parse+insert body so a failed file contributes exactly zero rows"
      - "Test with a truncated .gz yielding >5000 events before the cut, asserting the failed file contributes zero rows and accounting stays consistent"
  - truth: "All rendered cluster/event text and any echoed filter values pass through _sanitise (T-04-01)"
    status: failed
    reason: "WR-01 (review Warning, confirmed live): show events sanitises only message and source_file — event_id, ts, severity print raw; show clusters sanitises only template — template_id, count, severity_max, first_ts, last_ts and every exemplar id print raw. A tampered case.db (this phase's own trust boundary, the reason _decode_raw carries a zstd-bomb cap) can put ESC/CSI/bidi bytes in any TEXT column; a non-list exemplar_event_ids JSON also crashes ' '.join with a raw traceback. Regression of the Phase 1 T-04-01 class."
    artifacts:
      - path: "src/sift/cli.py"
        issue: "lines 417-423 (clusters) and 428-435 (events): per-field sanitisation misses most DB-sourced fields"
    missing:
      - "Sanitise the complete rendered line (wrap each print's f-string in _sanitise) on both show paths"
      - "Guard non-list exemplar_event_ids JSON before join"
      - "Store-level fixture test writing hostile bytes into exemplar_event_ids/first_ts and asserting no raw ESC in output"
  - truth: "Filtering fails loudly on bad input — never silently narrowed results (prohibition, 02-03)"
    status: partial
    reason: "WR-05 (review Warning, confirmed live): duplicate --filter keys silently last-win (dict assignment in _parse_filters) — '--filter severity=error --filter severity=warn' shows warn-only with no error, contradicting the documented AND-combine semantics and the fail-loud contract. Distinct-key AND-combination itself is tested and correct."
    artifacts:
      - path: "src/sift/cli.py"
        issue: "_parse_filters (lines 326-370): filters[key] = value overwrites without a duplicate check"
    missing:
      - "raise ValueError on duplicate key after the allowlist check; CLI test asserting exit 2 on a repeated key"
  - truth: "REQUIREMENTS.md ticks CLI-03 and STORE-04 with partial-scope notes (the phase's own convention, stated in 02-02/02-03 success criteria and SUMMARYs)"
    status: partial
    reason: "Both SUMMARYs claim the requirement was 'ticked with this partial-scope note', but REQUIREMENTS.md contains no note — CLI-03 and STORE-04 read as fully Complete while the embedding/generation progress legs (Phases 3-4) and the hypotheses inspection target (Phase 4) are still outstanding. Silent scope-widening in the traceability record."
    artifacts:
      - path: ".planning/REQUIREMENTS.md"
        issue: "lines 29, 65 and traceability rows 132/134: plain [x]/Complete, no partial-scope annotation"
    missing:
      - "Add partial-scope notes: CLI-03 'ingest leg delivered Phase 2; embedding/generation legs Phases 3-4'; STORE-04 'events+clusters targets delivered Phase 2; hypotheses target Phase 4'"
deferred:
  - truth: "STORE-04 hypotheses inspection target (`sift show <case> hypotheses`)"
    addressed_in: "Phase 4"
    evidence: "02-03-PLAN success criteria: 'the requirement's hypotheses target arrives with Phase 4'; cli.py show prints 'show hypotheses arrives in Phase 4 (M4)' and exits 1 (loud arrival stub); REQUIREMENTS.md maps hypotheses work (LLM-*/Phase 4) to later phases"
  - truth: "CLI-03 embedding and generation progress legs"
    addressed_in: "Phases 3-4"
    evidence: "02-02-PLAN flagged assumption: 'CLI-03's text covers ingest, embedding AND generation progress; this phase can only deliver the ingest leg (embedding/generation arrive in Phases 3-4)'"
behavior_unverified_items:
  - truth: "Long ingest shows live progress feedback on a real terminal (ROADMAP SC5 / CLI-03)"
    test: "uv run python tests/perf/generate_synthetic.py /tmp/big.log 100; uv run sift new demo --input <dir>; uv run sift ingest demo in a real terminal"
    expected: "A transient rich progress bar (bar, bytes, elapsed) renders on stderr during ingest and disappears on completion; stdout carries only the per-file/Total/Template-groups lines"
    why_human: "rich renders only when console.is_terminal; CliRunner/CI capture no TTY, so the rendering path is present and wired (cli.py:186-198) but never exercised by any test (02-VALIDATION.md manual-only item)"
  - truth: "Migration 2 runs atomically under a concurrent opener — no half-migrated schema observable (02-01 backstop)"
    test: "Open a v1 case.db from two processes simultaneously (one mid-migration); or accept the structural argument after inspection"
    expected: "The second opener sees either user_version=1 (pre) or fully-migrated v2 — never template_groups without compressed raws or vice versa"
    why_human: "No concurrency test exists. Structural evidence is strong (store.py:229-242 wraps each migration + user_version bump in one BEGIN IMMEDIATE...COMMIT), but the invariant is a concurrency behavior no test exercises — backstop truths abstain without behavioral evidence"
  - truth: "An interrupted ingest leaves the store fully updated or unchanged (02-02 backstop)"
    test: "Kill sift ingest mid-run on the 100 MB file; reopen the case and count events / check template_groups"
    expected: "Either zero new events (transaction rolled back on the WAL journal) or the complete result; never a partial commit"
    why_human: "The single BEGIN IMMEDIATE transaction spanning all batches is confirmed in code (cli.py:201, store.py:244-254) and the WAL-checkpoint-on-close half is test-verified (case dir == [case.db]), but no test kills a mid-ingest process — the rollback-on-interrupt behavior is unexercised"
---

# Phase 2: Case Store & Template Dedup Verification Report

**Phase Goal:** The full write path works at production scale with zero LLM dependency — a 100 MB log collapses into inspectable template groups in a single portable file
**Verified:** 2026-07-16T20:55:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Independent Gate Evidence (run by verifier, not quoted from SUMMARYs)

- `uv run pytest -q`: **164 passed, 1 deselected in 1.07 s** (perf test correctly deselected by addopts)
- `uv run ruff check`: clean
- `uv run pyright`: 0 errors, 0 warnings (strict)
- All 7 claimed task commits present in git log (93b3db8, 4ade286, e0f33d0, 62d027e, 3c8394b, 3d58c54, 7b036d0) on branch `gsd/phase-02-case-store-template-dedup`

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | SC1: 100 MB synthetic log ingests < 60 s on CPU; one portable case.db; deleting the file deletes the case | ✓ VERIFIED | Gated measurement 19.3 s at 02-02 task-2 verify (3x headroom); `test_100mb_ingest_under_60s` asserts elapsed<60, exit 0, case dir == ["case.db"]; portability tests (`test_case_dir_contains_only_case_db_after_clean_run`, `test_deleting_case_directory_deletes_the_case`) green in verifier's run. 02-03's 66.7 s re-run was environmental (load avg 12.4; pristine-HEAD control 69.6 s under same load; 02-03's diff does not touch ingest) — idle-machine re-run listed in UAT |
| 2 | SC2: template dedup reduces distinct groups >= 90% with count/first/last/exemplars | ✓ VERIFIED | `test_reduction` green (verifier's run): 0.005 <= 0.10 ratio plus independent full aggregation cross-check of count/first_ts/last_ts/exemplars per group |
| 3 | SC3: `sift show <case> events\|clusters [--filter ...]` works before any AI | ✓ VERIFIED | `test_show_clusters_e2e`, filter semantic tests (severity/min-count/contains/AND/limit), unknown-key exit-2 tests all green; wiring confirmed: cli.py:417 → query_template_groups, cli.py:429 → iter_event_rows |
| 4 | SC4: migrations via PRAGMA user_version; raw > 4 KB zstd-compressed transparently | ✓ VERIFIED | `test_v1_to_v2_upgrade` (typeof(raw)=='blob', round-trips), `test_raw_zstd_threshold_boundary` (0/4096 TEXT, 4097 BLOB), `test_zstd_threshold_measured_in_encoded_bytes`, `test_reopen_migrated_store_is_noop` all green; `_decode_raw` carries max_output_size=128 MiB (store.py:46) |
| 5 | SC5: long ingest shows progress feedback | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | Code present + wired (cli.py:183-198: Console(stderr=True), Progress with disable=not is_terminal, static description); non-TTY stdout regression test green — but live TTY rendering cannot be exercised by CliRunner (02-VALIDATION.md manual-only item) |
| 6 | show clusters lists groups with count, first/last seen, severity_max, exemplar ids | ✓ VERIFIED | `test_show_clusters_e2e` asserts 16-hex template_id, exemplars line, counts; render format at cli.py:419-423 |
| 7 | Re-running ingest on unchanged case → byte-identical template_groups rows | ✓ VERIFIED | `test_reingest_rebuild_idempotent` green; recompute-from-store design (dedup.py:84-124) |
| 8 | 4 KB threshold in UTF-8 encoded bytes; boundary exact at 4096/4097 | ✓ VERIFIED | Tests green; `_encode_raw` compares len(raw.encode("utf-8")) > 4096 (store.py:35-36); migration predicate length(CAST(raw AS BLOB)) matches |
| 9 | v1 db migrates in place; re-open is a no-op | ✓ VERIFIED | `test_v1_to_v2_upgrade`, `test_reopen_migrated_store_is_noop` green |
| 10 | clusters ordering (count DESC, template ASC); empty case exits 0 rendering nothing | ✓ VERIFIED | `test_show_clusters_ordering`, `test_show_clusters_empty_case_exits_0` green; ORDER BY in query_template_groups (store.py:390) |
| 11 | Exemplars = min(count, 5) in canonical order; severity_max via rank dict, never lexicographic | ✓ VERIFIED | `test_exemplar_cap`, `test_severity_max_uses_rank_not_lexicographic` green; _SEVERITY_RANK dict at dedup.py:43-50, EXEMPLAR_K=5 |
| 12 | Backstop: migration 2 atomic against concurrent opener | ? ABSTAIN → human | BEGIN IMMEDIATE wrapper confirmed (store.py:229-242) but no concurrency test — backstop abstains without behavioral evidence |
| 13 | Case dir contains ONLY case.db after clean run; rmtree deletes the case | ✓ VERIFIED | Both portability tests green in verifier's run; show events/clusters share try/finally store.close() (cli.py:436-438) |
| 14 | Duplicate case name exits 1 'already exists' | ✓ VERIFIED | `test_new_refuses_to_overwrite_existing_case` green (Phase 1 behaviour pinned as 02-02 acceptance) |
| 15 | Progress on stderr only; stdout contract byte-identical | ✓ VERIFIED | Non-TTY regression test green; all per-file/Total/Template-groups prints are plain stdout print() |
| 16 | Ingest streams via itertools.batched, never materialises a whole file | ✓ VERIFIED | cli.py:239 `for batch in batched(file_adapter.parse(path, case), 5000)`; no `list(file_adapter.parse` remains |
| 17 | Default suite excludes perf; -m perf runs the gate | ✓ VERIFIED | "1 deselected" in verifier's own run; pyproject.toml:34-36 addopts + marker |
| 18 | Synthetic generator deterministic per seed | ✓ VERIFIED | Determinism test (1 MB, byte-identical, seed 42) runs in default suite — green |
| 19 | Backstop: interrupted ingest all-or-nothing; WAL checkpointed on clean close | ? ABSTAIN → human | Single transaction spanning all batches confirmed (cli.py:201); WAL-checkpoint half test-verified (truth 13); rollback-on-interrupt behavior unexercised by any test |
| 20 | Filter semantics: severity/source/file/since/until/limit (events), severity/min-count/contains/limit (clusters); distinct keys AND-combine | ✓ VERIFIED | `test_iter_event_rows_*`, `test_query_template_groups_*`, `test_iter_event_rows_filters_and_combine`, `test_show_events_filter_severity` green |
| 21 | Unknown/invalid filter input exits 2 naming valid options | ✓ VERIFIED | Exit-2 tests green (unknown key both targets, limit=abc, since=notatime, severity=catastrophic, min-count=-1) |
| 22 | Injection-shaped values bind as literals; values never reach SQL text | ✓ VERIFIED | Injection-literal tests green (DROP-style values → zero rows, exit 0, tables intact); allowlist snippet dicts + ?-binding confirmed by code read (store.py:157-202); instr() not LIKE; store-level ValueError defence in depth |
| 23 | show events streams column-scoped rows byte-identical to Phase 1, no raw/zstd | ✓ VERIFIED | Never-xfailed byte-identical regression test green; iter_event_rows selects six columns, no raw, cursor-streamed (store.py:328-351) |
| 24 | All rendered cluster/event text passes through _sanitise (T-04-01) | ✗ FAILED | WR-01 confirmed live: events path sanitises only message/source_file (event_id, ts, severity raw — cli.py:433-434); clusters path sanitises only template (template_id, severity_max, first_ts, last_ts, exemplar ids raw — cli.py:420-423). Tampered case.db TEXT columns reach the terminal unsanitised |

**Score:** 20/24 truths verified (1 failed, 3 present-but-behavior-unverified/abstained)

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | STORE-04 hypotheses inspection target | Phase 4 | 02-03-PLAN: "hypotheses target arrives with Phase 4"; `show hypotheses` is a loud arrival stub (exit 1) |
| 2 | CLI-03 embedding/generation progress legs | Phases 3-4 | 02-02-PLAN flagged assumption; embedding arrives Phase 3, generation Phase 4 |

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `src/sift/pipeline/dedup.py` | mask(), MASK_VERSION, severity ranking, rebuild_template_groups | ✓ VERIFIED | 125 lines, substantive; typer/print/SQL-free confirmed; wired via cli.py:296 |
| `src/sift/pipeline/__init__.py` | package init | ✓ VERIFIED | Present |
| `src/sift/store.py` | migration 2, _encode_raw/_decode_raw, iter_event_summaries, template groups, filter allowlists, iter_event_rows | ✓ VERIFIED | All symbols present (`_migration_2`:101, `_EVENT_FILTER_SQL`:157, `TemplateGroup`:206, `iter_event_rows`:328); max_output_size in _decode_raw |
| `src/sift/cli.py` | batched streaming ingest + progress + --filter + streaming show | ✓ VERIFIED | All present and wired; see gaps for CR-01/WR-01/WR-05 defects within |
| `tests/test_dedup.py` | 15 tests incl. test_reduction, idempotency, accounting, ReDoS | ✓ VERIFIED | 15 test functions; all green |
| `tests/perf/generate_synthetic.py` | seeded importable + __main__ generator | ✓ VERIFIED | `def generate(` :69, `if __name__ ==` present |
| `tests/perf/test_perf_ingest.py` | @pytest.mark.perf < 60 s gate + portability assertion | ✓ VERIFIED | Marked test asserts elapsed<60, exit 0, dir==["case.db"], Template-groups line |
| `pyproject.toml` | perf marker + addopts exclusion + rich dependency | ✓ VERIFIED | Lines 34-36; deselection observed in verifier's run |

### Key Link Verification

(gsd-tools link checker errored on escaped patterns; all links verified manually by grep + code read)

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| cli.py | pipeline/dedup.py | rebuild_template_groups after event commit | ✓ WIRED | cli.py:296, post-transaction (cli.py:293-296) |
| pipeline/dedup.py | store.py | iter_event_summaries / replace_template_groups, no SQL in dedup | ✓ WIRED | dedup.py:94, 122; no sqlite3/typer imports in dedup.py |
| cli.py | store.py | show clusters → query_template_groups | ✓ WIRED | cli.py:417 (but see WR-01: only template sanitised) |
| cli.py | store.py | batched inserts inside the single ingest transaction | ✓ WIRED | cli.py:239-240 inside `with store.transaction():` at 201 |
| tests/perf/test_perf_ingest.py | generate_synthetic.py | import + generate() calls | ✓ WIRED | Lines 11, 25-26, 36 |
| cli.py | store.py | validated filter dict → iter_event_rows / query_template_groups | ✓ WIRED | cli.py:405 (_parse_filters), 417, 429 |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Full default gate | `uv run pytest -q` | 164 passed, 1 deselected, 1.07 s | ✓ PASS |
| Lint | `uv run ruff check` | All checks passed | ✓ PASS |
| Types (strict) | `uv run pyright` | 0 errors, 0 warnings | ✓ PASS |
| 100 MB perf gate | `uv run pytest -m perf` | NOT re-run: load avg 7.85 at verification time would reproduce the 02-03 environmental false-red; gated 19.3 s measurement (02-02) stands as phase evidence | ? SKIP → UAT |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| STORE-01 | 02-02 | Single portable case.db; delete file = delete case | ✓ SATISFIED | Portability tests green; sqlite-vec part of the requirement text arrives with Phase 3 vectors (not a Phase 2 claim) |
| STORE-02 | 02-01 | Migrations via PRAGMA user_version; raw > 4 KB zstd | ✓ SATISFIED | Migration/boundary/upgrade tests green |
| STORE-04 | 02-01, 02-03 | Inspect events\|clusters\|hypotheses [--filter] pre-AI | ⚠️ SATISFIED (partial, by convention) | events+clusters delivered; hypotheses deferred to Phase 4 — but the promised partial-scope note is MISSING from REQUIREMENTS.md (gap 4) |
| CLUS-01 | 02-01 | Mask volatile tokens; group with count/first/last/exemplars; no ML | ✓ SATISFIED | Reduction + token-class + accounting tests green; hand-rolled per ADR 0003. Note WR-04: bare-hex alternative swallows pure-decimal tokens of 8+ digits — reduction quality degrades on epoch timestamps/large ids in real logs (warning, not a requirement failure) |
| CLI-03 | 02-02 | Long operations show progress feedback | ⚠️ SATISFIED (partial, by convention) | Ingest leg delivered (TTY rendering = UAT item); embedding/generation legs Phases 3-4 — promised partial-scope note MISSING from REQUIREMENTS.md (gap 4) |

**Orphaned requirements:** none — REQUIREMENTS.md traceability maps exactly these five IDs to Phase 2; every plan-declared ID is accounted for.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| src/sift/cli.py | 239-267 | CR-01: partial-file rows committed, coverage meta records 0 | 🛑 Blocker | Write-path accounting integrity broken on mid-parse failure; false coverage claims persist for downstream phases |
| src/sift/cli.py | 417-435 | WR-01: DB-sourced fields rendered unsanitised | 🛑 Blocker (fails truth 24) | Terminal injection from a tampered case.db; regression of Phase 1 T-04-01 class |
| src/sift/cli.py | 326-370 | WR-05: duplicate --filter key silently last-wins | ⚠️ Warning (partial prohibition violation) | Silently narrowed triage windows on typo'd duplicates |
| src/sift/pipeline/dedup.py | 27 | WR-04: `\b[0-9a-fA-F]{8,}\b` matches pure-decimal 8+ digit runs | ⚠️ Warning | Templates shatter on numeric magnitude (epoch seconds/millis); ≥90% gate still passes on fixtures |
| src/sift/store.py | 221-242 | WR-02: show on read-only/corrupt case.db → raw traceback; show silently migrates (rewrites) v1 evidence files | ⚠️ Warning | Poor failure mode on evidence media |
| src/sift/cli.py | 293-296 | WR-03: crash window between event commit and rebuild leaves clusters silently stale | ⚠️ Warning | No staleness detection; recovery is trivial but undetected |
| various | — | IN-01..IN-06 (severity vocab duplication, migration fetchall, ROLLBACK masking, TOCTOU stat, dir-symlink silence, ZstdError context) | ℹ️ Info | See 02-REVIEW.md |

No TBD/FIXME/XXX/TODO debt markers in any phase-modified file (the two PLACEHOLDER grep hits are the `_PLACEHOLDER` mask-vocabulary dict, not stubs). No network imports anywhere in src/; autouse socket guard active in conftest.py.

### Prohibition Status (judgment-tier, flagged — evidence gathered, human sign-off required)

All seven plan prohibitions are descriptor-less judgment-tier items. None passes silently; each is listed with the verifier's evidence for the end-of-phase human checkpoint:

1. **No network egress (02-01, 02-02):** EVIDENCE STRONG — autouse `_no_network` socket-connect block in tests/conftest.py ran green across 164 tests; zero network imports in src/ (grep: socket/httpx/urllib/requests absent); dedup/generator/rich are pure-local.
2. **Dedup never loses events — sum(group counts) == count(events) incl. unknown severity (02-01):** EVIDENCE STRONG at the group level — `test_accounting_every_event_counted_once` green; recompute-from-store guarantees it structurally. **CAVEAT:** CR-01 breaks the mirror invariant at the coverage-meta level (rows appear that coverage denies) — see gap 1.
3. **Stored evidence stays verbatim; masking only in derived templates; sanitise at render only (02-01, 02-03):** EVIDENCE STRONG — mask() applies only to message→template (dedup.py:95); raw/message columns never modified; compression lossless with round-trip tests; filters are read-only SELECTs never touching raw (iter_event_rows omits the column). **CAVEAT:** render-time sanitisation is itself incomplete (WR-01, gap 2).
4. **Progress must not swallow per-file errors (02-02):** EVIDENCE STRONG — ERROR/SKIP lines are plain stdout print() (cli.py:209, 264), asserted by existing corrupt-archive/symlink tests, all green; progress is transient, stderr-only, disabled off-terminal.
5. **Filters fail loudly, never silent empty results (02-03):** EVIDENCE MOSTLY STRONG — five invalid-input exit-2 shapes tested green. **CAVEAT:** duplicate keys silently last-win (WR-05, gap 3).

### Human Verification Required

1. **Live progress bar on a real TTY** — `uv run python tests/perf/generate_synthetic.py /tmp/big.log 100`, create a case over it, run `uv run sift ingest <case>` in a real terminal. Expected: transient progress bar on stderr; stdout unchanged. Why: rich disables itself off-terminal; no test can exercise it.
2. **Perf gate on an idle machine** — `uv run pytest -m perf -s`. Expected: ~19-25 s (budget 60). Why: verifier's machine was under load (avg 7.85), same environmental condition that produced 02-03's 66.7 s false-red.
3. **Filter UAT** — `uv run sift show <case> events --filter severity=error --filter limit=5` and `... clusters --filter min-count=10` behave as `--help` documents (02-03 plan human-check).
4. **Backstop truths** — migration-2-under-concurrency and interrupted-ingest atomicity (structural evidence in report; behaviors unexercised — items 2-3 in behavior_unverified_items).
5. **Prohibition sign-off** — the five judgment-tier items above, with the two CR-01/WR-05 caveats resolved first or explicitly accepted.
6. **Partial-scope convention** — confirm ticking CLI-03/STORE-04 per-phase-leg is acceptable (both plans explicitly asked the verifier to surface this; the convention is reasonable, but the notes must actually land in REQUIREMENTS.md — gap 4).

### Gaps Summary

The phase substance is real and strong: schema v2, transparent zstd with a bomb cap, deterministic masking with a 0.005 reduction ratio, batched streaming inside one transaction, a 19.3 s / 100 MB gated measurement, and an allowlist+parameterised filter boundary that survived injection tests — all independently re-verified green (164 tests, ruff, pyright strict). SUMMARY claims matched the codebase everywhere except one: the REQUIREMENTS.md partial-scope notes both SUMMARYs claim to have written do not exist.

Four gaps block a clean pass, all small and precisely located:

1. **CR-01 (Critical):** the batched-streaming rewrite silently commits partial rows from mid-parse failures while coverage meta records zero — the write path's accounting integrity, the very contract this phase's goal statement ("nothing dropped silently") rests on, is broken for the truncated-archive class. Fix: per-file savepoint + one test.
2. **WR-01:** the sanitise-everything truth (02-03 must-have) fails — most DB-sourced fields render raw from a tampered case.db. Fix: sanitise whole rendered lines.
3. **WR-05:** duplicate filter keys silently last-win, against the fail-loud prohibition. Fix: one ValueError + one test.
4. **REQUIREMENTS.md** lacks the promised partial-scope notes for CLI-03/STORE-04. Fix: two annotations.

Remaining review warnings (WR-02, WR-03, WR-04) and the six info items do not fail must-haves but should ride along in the gap-closure plan where cheap. Human items (TTY progress, idle-machine perf, backstops, prohibition sign-off) are preserved in behavior_unverified_items and survive the gap-closure cycle.

---

_Verified: 2026-07-16T20:55:00Z_
_Verifier: Claude (gsd-verifier)_
