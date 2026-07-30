---
phase: 16-saturation-contention-signature-collapse
reviewed: 2026-07-25T00:00:00Z
depth: deep
files_reviewed: 5
files_reviewed_list:
  - src/sift/config.py
  - src/sift/pipeline/eustack.py
  - tests/test_config.py
  - tests/test_eustack_rules.py
  - docs/decisions/0016-eustack-saturation-analysis.md
findings:
  critical: 0
  warning: 2
  info: 2
  total: 4
status: issues_found
---

# Phase 16: Code Review Report

**Reviewed:** 2026-07-25T00:00:00Z
**Depth:** deep
**Files Reviewed:** 5
**Status:** issues_found

## Summary

Phase 16's new code (`analyse_saturation()`, `enclosing_application_frame()`, `PoolOccupancy`/`LockSite`/
`DependencyWait`/`SaturationFlag`/`SaturationAnalysis` in `src/sift/pipeline/eustack.py`, and
`EustackThresholdsConfig` in `src/sift/config.py`) is small, additive, and unusually well-specified: every
non-obvious decision (D-01 through D-12, S-1 through S-8) is documented inline and cross-checked against a
matching test in `tests/test_eustack_rules.py`. I traced every arithmetic path (pool occupancy, lock-site
denominator/ordering, dependency grouping, both ratio flags, the lock-count flag), every documented edge
case (zero threads, leaf-is-last-frame, all-unresolvable-frames, runtime-namespace skip, template-argument
namespace disambiguation, tie-breaking on every sort key), and cross-referenced the shipped rules file
(`src/sift/rules/eustack_roles.toml`) and `mcm._grade()`'s rounding convention against the new code. I did
not find a reachable logic defect, security issue, or crash path in the reviewed diff — `analyse_eustack()`
and `analyse_saturation()` both hold their stated invariants (deterministic ordering via explicit sort keys
never relying on dict/set iteration order, no-thread inputs producing empty tuples rather than division
errors, `unclassified` never folded into another pool's denominator, the ownership-blind vocabulary
guard extending correctly to emitted strings).

Two WARNING-level robustness gaps and two INFO-level nits below are worth fixing, none of them blocking.

## Warnings

### WR-01: `Rule.subsystem` has no non-empty validation, unlike `Rule.pattern`

**File:** `src/sift/pipeline/eustack.py:68-95` (the `Rule` model), consumed at `:634-662` (`PoolOccupancy`
grouping) and `:696-729` (`DependencyWait` grouping)

**Issue:** `Rule.pattern` is validated non-empty (`_pattern_nonempty`, line 82) and validated to already be
in `normalise()`'s canonical form (`_pattern_must_be_normalised`, line 89) — a curator mistake is rejected
loudly at load time, exactly the project's stated T-04-02 "a typo'd key must fail loudly" convention. `Rule.
subsystem` (line 76) carries none of that: it is `str`, required, but Pydantic only checks that a key is
present, not that its value is non-empty or non-whitespace. `test_missing_subsystem_rejected_at_load`
(`tests/test_eustack_rules.py:214-220`) only covers the *key absent* case, never `subsystem = ""` or
`subsystem = "   "`.

Before Phase 16, `subsystem` was inert provenance metadata carried through `Classification`/`SignatureGroup`
with no consumer. Phase 16 makes it a live grouping key: `analyse_saturation()` groups
`EustackAnalysis.signatures` on `group.subsystem` to build `PoolOccupancy` rows (line 635) and
`DependencyWait` rows (line 712), using the string verbatim as a report label. A rules-file edit that leaves
`subsystem = ""` (or all-whitespace) on a rule now silently ships a malformed, unnamed pool/dependency row
in the report instead of failing at `load_rules()` — the exact failure mode T-04-02 exists to prevent
elsewhere in this same file.

**Fix:**
```python
@field_validator("subsystem")
@classmethod
def _subsystem_nonempty(cls, value: str) -> str:
    if not value.strip():
        raise ValueError("rule subsystem must not be empty")
    return value
```

### WR-02: `load_config()`'s flag-override merge is one level deep despite being commented "Deep-merge"

**File:** `src/sift/config.py:236-249` (the merge loop), consumed by the newly-added three-level-nested
`EustackThresholdsConfig` at `:125-146`/`:156`

**Issue:** The merge comment at line 242-243 reads "Deep-merge so a nested flag override wins per field
without discarding toml/env siblings" — but the implementation only merges the *top level* of one section
dict (lines 244-246: `merged.update(existing); merged.update(value)`). For a two-level section (e.g.
`embeddings.base_url`), that is genuinely a full merge and the existing tests (`test_env_beats_toml_for_
embeddings_base_url_but_flag_wins`) pass correctly. But `EustackThresholdsConfig` — newly added this phase —
is *three* levels deep (`eustack -> thresholds -> unclassified_thread_pct -> {warn, critical}`). If a future
flag override supplies `{"eustack": {"thresholds": {"unclassified_thread_pct": {...}}}}` while a TOML file
already sets a *different* field under `[eustack.thresholds]` (e.g. `no_resolvable_frame_pct`), the merge
at line 246 replaces the entire `"thresholds"` dict wholesale — the TOML-configured `no_resolvable_frame_
pct` value is silently dropped, and Pydantic backfills it with the hardcoded class default (5.0/15.0)
because that key is now simply absent from the dict being validated. This directly contradicts the stated
precedence contract ("flags > env > toml > defaults" — overriding *one* field must never silently reset an
*unrelated sibling* field back to its default). The same latent bug already exists for `mcm.thresholds`
(also three levels deep), so this is not new to Phase 16, but Phase 16 adds a second three-level-nested
config surface that inherits it, and no test in `tests/test_config.py` exercises a TOML-plus-flag
interaction at this nesting depth for either section.

**Currently unreachable:** `grep -n "thresholds" src/sift/cli.py` shows no CLI flag exists yet for
`eustack.thresholds.*` or `mcm.thresholds.*` — `load_config()` is only ever called with `flag_overrides`
targeting `data_dir`, `embeddings`, `generation`, or `adapters`. This is a latent defect that will fire the
moment a `--eustack-threshold`-style flag (or equivalent) is added, not a currently-triggerable one.

**Fix:** Either recurse the merge (`_deep_merge(existing, value)` walking nested dicts key-by-key) or, more
simply, fix the comment to say "one level deep, single-field sections only" and add a guard/test the day a
CLI flag for `eustack.thresholds`/`mcm.thresholds` is introduced.

## Info

### IN-01: No `warn <= critical` validation on `ThresholdPair`/`EustackThresholdsConfig`

**File:** `src/sift/config.py:85-92` (`ThresholdPair`), `:125-146` (`EustackThresholdsConfig`)

**Issue:** Nothing rejects a TOML override with `warn > critical` (e.g. a curator swaps the two numbers by
mistake). `_grade()` (`src/sift/pipeline/mcm.py:609-624`) checks `critical` first, so an inverted pair would
silently produce nonsensical severity transitions rather than an error at config-load time. This mirrors an
existing gap in `McmThresholdsConfig` (not introduced by this phase), but `EustackThresholdsConfig` is new
and was a natural point to close it.

**Fix:** A `model_validator` on `ThresholdPair` asserting `warn <= critical` (or documenting the inverted-
metric exception the way `system_free_headroom_pct` already documents its own direction flip).

### IN-02: Redundant explicit `lock_finding_note=LOCK_FINDING_NOTE` in `analyse_saturation()`'s return

**File:** `src/sift/pipeline/eustack.py:840` vs. the field default at `:613`

**Issue:** `SaturationAnalysis.lock_finding_note` already defaults to `LOCK_FINDING_NOTE` (line 613). The
constructor call at line 840 passes the identical value explicitly for no behavioural reason — harmless, but
it invites a future editor to believe the field is ever set to something else, when in fact nothing in this
module ever varies it.

**Fix:** Drop the explicit keyword argument and rely on the model default (or, if the explicitness is
intentional documentation, say so in a one-line comment).

---

_Reviewed: 2026-07-25T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
