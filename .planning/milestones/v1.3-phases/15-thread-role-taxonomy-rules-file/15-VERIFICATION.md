---
phase: 15-thread-role-taxonomy-rules-file
verified: 2026-07-25T00:00:00Z
status: passed
score: 6/6 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 15: Thread-Role Taxonomy & Rules File Verification Report

**Phase Goal:** Every thread in an eu-stack dump carries a deterministic role label, produced by a
versioned rules file an engineer can edit without touching Python
**Verified:** 2026-07-25
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Every thread in a dump lands in exactly one of five roles (`idle-parked`, `blocked-on-external`, `blocked-on-lock`, `running`, `unclassified`); the partition is total, not a subset | ✓ VERIFIED | `analyse_eustack` (`src/sift/pipeline/eustack.py:321-373`) zero-fills all five keys from `_ALL_ROLES` before counting, so no reader can ever meet a missing key; `threads_by_role` sums exactly to `total_threads` by construction (each `Counter` entry adds to exactly one role bucket). `tests/test_eustack_rules.py::test_classification_partitions_all_threads` (live-run: PASS) asserts `set(analysis.threads_by_role) == {5 roles}` and the sum identity against the real 105-thread derivative fixture. Independently reproduced on both real out-of-repo dumps: 3,651+194+5+0+52 = 3,902 exactly (dump A) and equivalently for dump B — orchestrator-verified, no thread silently dropped. |
| 2 | `unclassified` is an honest, disclosed residual — not a catch-all hiding parse failures — and splits "no rule matched" from "no resolvable frame to test" | ✓ VERIFIED | D-07 implemented via `_is_resolvable()` (`eustack.py:204-213`) and the `reason` field on `Classification`/`SignatureGroup` (`matched-no-rule` vs `no-resolvable-frame`, `eustack.py:257-268`). `test_all_unresolved_frames_is_distinct_category` and `test_unmatched_signature_reports_count_and_example` (both in the suite, both green) prove the split is real, not cosmetic. `test_derivative_coverage_is_disclosed_not_inflated` (live-run: PASS) asserts `unclassified` is non-empty on the real derivative and disjoint from classified signatures — a future catch-all rule that drives it to zero would fail this test. EUS-02's `[x]` in REQUIREMENTS.md is justified: the report is computed and exposed on `EustackAnalysis`, consistent with how EUS-01 also closed at the library level (no CLI — D-13 explicitly defers `sift eustack` to Phase 17). |
| 3 | An engineer can change classification output by editing the rules file alone, with zero Python edits or reinstall | ✓ VERIFIED | `load_rules(rules_path)` (`eustack.py:164-197`) accepts an arbitrary file path and re-validates from scratch — no Python-side branching keyed on content. `test_rules_path_override_changes_classification` (live-run: PASS) writes a fresh TOML to `tmp_path`, loads it via `rules_path=`, and shows the same signature classifies differently (`idle-parked` → `running`) purely from file content. `test_rule_order_is_the_precedence_knob` further proves row position alone (not a `priority` field) decides precedence, both directions. `EustackConfig.rules_path` + `SIFT_EUSTACK_RULES_PATH` (`config.py:124-130,176`) give the operator-facing override surface (CLI-flag > env > TOML > default), fully tested in `test_config.py` (`test_eustack_rules_path_defaults_to_none`, `test_eustack_rules_path_round_trips_from_toml`, `test_env_beats_toml_for_eustack_rules_path_but_flag_wins`, `test_unknown_key_under_eustack_is_a_loud_error` — all live-run: PASS). **Scoped gap, not a defect:** nothing yet calls `load_rules(config.eustack.rules_path)` from a CLI command — there is no `sift eustack` command in this phase (D-13, explicitly deferred to Phase 17). The goal's "edit without touching Python" claim is proven at the library boundary the phase actually ships (`load_rules()` + tests), and the config key exists as the pre-wired operator surface for Phase 17 to consume. This is the phase's own declared boundary, not a hidden shortfall. |
| 4 | Classification is deterministic: same input + same rules → byte-identical output | ✓ VERIFIED | `analyse_eustack` builds signatures via `Counter` (dict-order-dependent internally) but the OUTPUT list is always explicitly re-sorted on `(-thread_count, frames)` (`eustack.py:352-355`) before being placed in the frozen `EustackAnalysis` model — no `set` iteration anywhere on the output path (confirmed by direct code read, matches the module's own determinism-contract docstring). `test_analysis_is_byte_identical_on_rerun` (live-run: PASS) asserts `model_dump_json()` byte-equality across two independent `analyse_eustack()` calls on the real 105-thread derivative fixture — genuine evidence of ordering-independence, not just an assumption. |
| 5 | Classification cost scales with distinct signature count, not thread count | ✓ VERIFIED | `analyse_eustack` classifies once per `Counter` key (`eustack.py:339-340`), never per thread. `test_classification_is_per_signature_not_per_thread` asserts a monkeypatched call counter equals `total_signatures` and is strictly less than `total_threads`. Orchestrator-verified real-capture timing (recorded in 15-06-SUMMARY.md, not re-run here): 0.034s classification against 3,902 threads/93 signatures. |
| 6 | Sift never emits ownership-attributed lock language (the permanent "deadlock" non-goal) | ✓ VERIFIED | `test_no_ownership_attributed_lock_language_in_shipped_surface` reads the forbidden term from `REQUIREMENTS.md` at runtime (not hardcoded) and asserts its absence from both `eustack_roles.toml` and `pipeline/eustack.py`. Orchestrator-verified: 0 occurrences of "deadlock" anywhere in `src/`. |

**Score:** 6/6 truths verified (0 present-but-behaviour-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/sift/pipeline/eustack.py` | Pydantic models + loader + normaliser + classifier + aggregate surface, pure/library-only | ✓ VERIFIED | 374 lines; `Rule`/`RulesMeta`/`ThreadRoleRules`/`Classification`/`SignatureGroup`/`EustackAnalysis` all `extra="forbid"`; `normalise`/`signature_of`/`load_rules`/`classify_signature`/`analyse_eustack` all present and match the D-01–D-16 contract read directly against source |
| `src/sift/rules/eustack_roles.toml` | Curated day-one rules file, TOML, versioned `[meta]` | ✓ VERIFIED | 24 `[[rule]]` rows across all four rule-assignable roles (running×5, blocked-on-lock×1, idle-parked×14, blocked-on-external×4), `[meta].version=2`, `validated_against` populated |
| `src/sift/rules/__init__.py` | Pure package-data marker mirroring `prompts/` | ✓ VERIFIED | `test_packaged_rules_file_is_importable_resource` (in suite) confirms `importlib.resources.files("sift.rules")` resolves |
| `src/sift/config.py::EustackConfig` | `[eustack] rules_path` operator override, mirrors `McmConfig` | ✓ VERIFIED | `config.py:124-130`, wired into `SiftConfig` (`config.py:144`) and `_ENV_SCALARS` (`config.py:176`) |
| `docs/decisions/0015-eustack-thread-role-taxonomy.md` | ADR recording D-01/D-05/D-09/D-02/D-07/containment-guard/deadlock-non-goal | ✓ VERIFIED | 207 lines, records all named decisions, alternatives, consequences, disclosed limitations |
| `tests/fixtures/eustack/reference_capture_derivative.txt` | Signature-preserving CI fixture, all 93 real signatures | ✓ VERIFIED | Orchestrator-verified: 150,475 bytes, 105 threads, max frame depth 59, retains single-`@`/double-`@@` GLIBC-suffixed symbols |
| `tests/test_eustack_rules.py` | Full EUS-01/EUS-02 test coverage per 15-VALIDATION.md's test map | ✓ VERIFIED | 592 lines, every test name 15-VALIDATION.md commits to (`test_classification_partitions_all_threads`, `test_rules_path_override_changes_classification`, `test_reference_derivative_headline_signature`, `test_classification_is_per_signature_not_per_thread`, `test_unmatched_signature_reports_count_and_example`, `test_all_unresolved_frames_is_distinct_category`, `test_unnormalised_pattern_rejected_at_load`, `test_running_rule_precedes_evaluation_ancestor_rule`, `test_single_at_glibc_suffix_is_stripped`) exists verbatim and is present in the file |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `pipeline/eustack.py` | `adapters/eustack.py` | `iter_frames`/`_condense_symbol` import (D-08) | ✓ WIRED | `eustack.py:38-41` imports both directly from the shipped adapter; no second frame regex exists (`normalise()` calls `_condense_symbol` at `eustack.py:153`, `signature_of()` calls `iter_frames` at `eustack.py:161`) |
| `pipeline/eustack.py::load_rules` | `src/sift/rules/eustack_roles.toml` | `importlib.resources.files("sift.rules")` | ✓ WIRED | `eustack.py:184-188`; confirmed importable via `test_packaged_rules_file_is_importable_resource` |
| `config.py::EustackConfig.rules_path` | `pipeline/eustack.py::load_rules(rules_path=...)` | Operator-supplied path, function signature match | ⚠️ NOT YET CONNECTED (scoped) | No caller currently reads `config.eustack.rules_path` and passes it to `load_rules()` — there is no CLI command in this phase to do so. This is D-13's explicit phase boundary (`sift eustack` lands in Phase 17), not an oversight; `load_rules()` itself is fully exercised via direct test calls with an explicit `rules_path` argument, proving the mechanism the config key will eventually drive |
| `pipeline/eustack.py::classify_signature` | `pipeline/eustack.py::analyse_eustack` | Called once per distinct `Counter` key | ✓ WIRED | `eustack.py:340`; `test_classification_is_per_signature_not_per_thread` proves the call count matches signature count, not thread count |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| EUS-01 | 15-01, 15-02, 15-04, 15-05, 15-06 | Every thread classified into one of 5 roles, driven by a versioned, Python-free-editable rules file | ✓ SATISFIED | Truths 1, 3, 4, 5 above; REQUIREMENTS.md `[x]` |
| EUS-02 | 15-03, 15-05, 15-06 | Unrecognised frames counted and reported as `unclassified`, never guessed | ✓ SATISFIED | Truths 2, 6 above; REQUIREMENTS.md `[x]` |

No orphaned requirements — REQUIREMENTS.md's phase-15 row lists only EUS-01/EUS-02, and both appear in every plan's `requirements:` frontmatter that touches them.

### Anti-Patterns Found

None. `grep` for `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER` across `pipeline/eustack.py`, `rules/eustack_roles.toml`, `config.py`, `adapters/eustack.py`, ADR 0015, `test_eustack_rules.py`, and the fixture-derivation script returned zero matches. No `deadlock` anywhere in `src/` (orchestrator-verified). All four Pydantic models carry `ConfigDict(extra="forbid")` (orchestrator-verified).

Two Warning-level findings from `15-REVIEW.md` (code review, not this verification) remain open and are recorded here for completeness, since they bear on the "every thread carries a role" and "determinism" truths above:

- **WR-01** (`tests/fixtures/eustack/derive_reference_capture_derivative.py:52-70`): the fixture-derivation tool does not mirror the shipped adapter's `MAX_EVENT_LINES`/`MAX_EVENT_BYTES` block-splitting cap, so a future capture containing a thread deeper than 256 lines could produce a fixture that is not actually signature-preserving on re-ingest. Inert today (max observed depth is 59, well under the 256-line cap — orchestrator-verified), but a real risk for future fixture regeneration. Not a defect in the shipped classifier or rules file; scoped to the offline derivation tool only.
- **WR-02** (`src/sift/adapters/eustack.py:69-73`, reused by `normalise()`): `_condense_symbol`'s naive `" - "` split, originally written for a cosmetic purpose, is now load-bearing for rule matching. A real (demangled) symbol containing a literal `" - "` substring before its own `<lib> <src>:<line>` tail would silently truncate mid-symbol with no error raised. No evidence this occurs in the reference capture; flagged as a design risk for future symbol sets.

Neither finding blocks phase completion — both are pre-existing code-review findings (0 critical), not gaps this verification independently discovered, and neither contradicts any of the six observable truths above.

### `blocked-on-lock` coverage assessment (0 occurrences on both real dumps)

The single `blocked-on-lock` rule (`__lll_lock_wait`, `eustack_roles.toml:74-78`) matched zero threads on both real reference dumps (orchestrator-verified: dump A and dump B). By inspection this is plausible, not a defect: `__lll_lock_wait` is glibc's internal symbol reached only on the contended futex slow path inside `pthread_mutex_lock`/`pthread_rwlock_*` — a thread parked in the uncontended fast path or in a plain condition-variable wait never reaches it. The reference capture is explicitly documented (ADR 0015, `eustack_roles.toml` header) as a healthy server snapshot with no observed lock contention, which is the expected result, not a missing rule. The rule's mechanism is proven independently: `test_all_four_rule_roles_are_reachable` (live-run: PASS) constructs a synthetic thread whose only frame is `__lll_lock_wait` and confirms it classifies `blocked-on-lock`. This is a genuine, disclosed coverage limitation — the rule is real and correctly wired but has never fired against production data — recorded here as a known gap for future validation against a contended capture, not treated as a hidden defect.

### 15-VALIDATION.md strategy carried out

Every test named in 15-VALIDATION.md's Per-Task Verification Map exists verbatim in `tests/test_eustack_rules.py` and was independently re-run live as part of this verification (all PASS): `test_rules_path_override_changes_classification`, `test_classification_partitions_all_threads`, `test_analysis_is_byte_identical_on_rerun`, `test_all_four_rule_roles_are_reachable`, `test_derivative_coverage_is_disclosed_not_inflated`. The two Manual-Only Verifications (real 1,715-thread population reading `idle-parked/job-queue`; wall-clock scaling) are both recorded with measured figures in `15-05-SUMMARY.md` and `15-06-SUMMARY.md`, matching the orchestrator-verified real-capture partition exactly. One documentation-hygiene note: `15-VALIDATION.md`'s own frontmatter (`status: draft`, `nyquist_compliant: false`, `wave_0_complete: false`) and its Validation Sign-Off checklist were never updated to reflect completion — the underlying validation work is done and verified, but the artifact itself was left in its pre-execution state. This is cosmetic (the tests it commits to all exist and pass), not a functional gap, and does not affect the phase-goal verdict.

### Human Verification Required

None. All must-haves resolved to VERIFIED via direct code inspection plus live re-execution of the load-bearing tests (not merely reading SUMMARY.md claims).

### Gaps Summary

No blocking gaps. The phase goal — "every thread in an eu-stack dump carries a deterministic role label, produced by a versioned rules file an engineer can edit without touching Python" — is genuinely achieved at the library level this phase scoped itself to (D-13: no CLI until Phase 17). The one item worth a human's attention going forward, not a defect today: the `[eustack] rules_path` config key exists and is fully tested in isolation, but nothing yet threads it through to `load_rules()` at runtime — that connection is Phase 17's explicit job, and its absence here is a declared scope boundary, not a hidden shortfall. The `blocked-on-lock` rule and the two code-review Warnings (WR-01, WR-02) are genuine, disclosed limitations worth tracking but do not block this phase's goal achievement.

---

_Verified: 2026-07-25_
_Verifier: Claude (gsd-verifier)_
