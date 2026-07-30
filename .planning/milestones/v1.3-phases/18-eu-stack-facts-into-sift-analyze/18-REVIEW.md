---
phase: 18-eu-stack-facts-into-sift-analyze
reviewed: 2026-07-26T00:00:00Z
depth: deep
files_reviewed: 8
files_reviewed_list:
  - src/sift/pipeline/eustack_facts.py
  - src/sift/pipeline/hypothesise.py
  - src/sift/cli.py
  - src/sift/prompts/eustack_facts.md
  - src/sift/prompts/triage.md
  - tests/test_eustack_facts.py
  - tests/test_eustack_analyze.py
  - docs/decisions/0017-eustack-aggregate-citation-sampling.md
findings:
  critical: 1
  warning: 2
  info: 0
  total: 3
status: issues_found
---

# Phase 18: Code Review Report

**Reviewed:** 2026-07-26
**Depth:** deep
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Reviewed the wiring of deterministic eu-stack thread-dump figures into `sift analyze`'s triage
prompt (`eustack_facts.py`, the `hypothesise.py`/`cli.py`/`triage.md` splice points, the versioned
`eustack_facts.md` fragment, and the eu-stack-specific tests + ADR 0017). Traced the full call
chain through `sift.pipeline.eustack`/`eustack_progression` (`signature_of`, `group_dumps`,
`resolve_dump_order`, `compute_progression`, `analyse_saturation`) to independently verify the
event_id re-derivation, the D-17 union-then-sample exemplar contract, and the D-10 progression
suppression gate against every code path that can reach `_progression_lines`.

The event_id re-derivation, D-17 union-then-sample logic, and D-10 delta-suppression gate are
correct and internally consistent with the analysers they mirror — I traced every branch
(single-dump, zero-dump, unverified-order, verified-order, vanished/appeared signatures) and could
not find a path where a delta figure escapes the suppression branch, nor a path where an exemplar
id is drawn from a dump other than the one its accompanying population figure describes. `ruff`,
`pyright` and the eu-stack test files are clean, and the fourth `triage.md` sentinel block strips
residue-free per the byte-identity tests.

However, one load-bearing honesty invariant this phase's own ADR names explicitly — "every
aggregate line carries a mandatory disclosure sentence" (D-03) — is not upheld for `SaturationFlag`
lines: `_flag_lines` prints a bounded three-citation exemplar sample beside a percentage/count
figure with no sampling disclosure at all, unlike every other grouping in the module. This is
reproducible against the real reference-capture fixture and is untested. Two related robustness
gaps (an unenforced positional coupling to `lock_sites`, and a silent-drop fallback for an unknown
future flag dimension) are also flagged as warnings.

## Critical Issues

### CR-01: `_flag_lines` omits the mandatory D-03 sampling-disclosure sentence

**File:** `src/sift/pipeline/eustack_facts.py:301-348`
**Issue:**

Every other grouping in this module (role composition, per-pool occupancy, lock-site convergence,
external-wait concentration, the signature listing, progression deltas) routes its printed
exemplar count and the aggregate's true population through `_sampling_sentence` — the "single
definition site" the module's own docstring (lines 121-129) says "every grouping's sampling
parenthetical routes through... so the wording cannot drift between groupings." `_flag_lines` is
the sole exception: it prints the `[evt:...]` exemplar prefix and the flag's numeric `value`/`unit`
but never calls `_sampling_sentence`, so a `SaturationFlag` line carries three citation tokens next
to a percentage or count with **no statement anywhere that those three ids are a sample rather than
an enumeration**.

This is exactly the failure mode ADR 0017 D-01/D-03 were adopted to prevent ("Printing three
citation tokens beside the figure 1,715 with no such sentence would let a reader — human or model —
assume the population had been enumerated... this wording is treated as load-bearing honesty, not
cosmetic polish"). Reproduced against the committed `reference_capture_derivative.txt` fixture:

```
[evt:09b0d567655b8292][evt:1639e7fed7af15dc][evt:1b503db77fadd708] eu-stack saturation flag
(critical) unclassified_thread_pct: 38.1 percent (warn 5.0, critical 15.0). 38.1% of threads are
unclassified.
```

Three citations stand in for whatever the real `unclassified` thread population is (potentially
hundreds), with nothing in the line — or the fragment template — telling the model this is a
sample. This is the highest-severity flag class the block emits (severity-graded, most likely to
drive the LLM's headline root-cause claim), so an undisclosed sample here is the single worst place
for the honesty gap to land. No test in `tests/test_eustack_facts.py` asserts a sampling sentence on
a flag line (`_SAMPLING_RE` is only exercised against the pool line in
`test_sampling_sentence_states_true_population`), which is how this shipped clean through `ruff`/
`pyright`/`pytest`.

**Fix:**

```python
# in _flag_lines, after computing `exemplars` for each branch, thread the
# branch's own population figure through alongside it:
no_resolvable_exemplars = _union_exemplars(no_resolvable_frame_tuples, per_dump_sig_ids)
no_resolvable_population = sum(
    group.thread_count
    for group in bundle.analysis.signatures
    if group.role == "unclassified" and group.reason == "no-resolvable-frame"
)

...
lines: list[str] = []
lock_sites_in_order = iter(bundle.saturation.lock_sites)
for flag in bundle.saturation.flags:
    if flag.dimension == "unclassified_thread_pct":
        exemplars = pool_exemplars.get(None, ())
        population = bundle.analysis.threads_by_role["unclassified"]
    elif flag.dimension == "no_resolvable_frame_pct":
        exemplars = no_resolvable_exemplars
        population = no_resolvable_population
    elif flag.dimension == "lock_convergence_count":
        site = next(lock_sites_in_order, None)
        exemplars = lock_site_exemplars.get(site.site, ()) if site is not None else ()
        population = site.thread_count if site is not None else 0
    else:
        exemplars, population = (), 0
    if not exemplars:
        continue
    prefix = _cite_prefix(exemplars, ids)
    lines.append(
        f"{prefix} eu-stack saturation flag ({sanitise(flag.severity)}) "
        f"{sanitise(flag.dimension)}: {flag.value:,} {sanitise(flag.unit)} "
        f"(warn {flag.warn:,}, critical {flag.critical:,}). "
        f"{sanitise(flag.message)} "
        f"{_sampling_sentence(len(exemplars), population)}"
    )
```

Add a regression test mirroring `test_sampling_sentence_states_true_population` that asserts
`_SAMPLING_RE` matches on an `eu-stack saturation flag` line and that its population equals the
flag's own underlying thread count (`threads_by_role["unclassified"]` / the no-resolvable-frame sum
/ `site.thread_count`), not the flag's percentage `value`.

## Warnings

### WR-01: `_flag_lines`'s lock-site attribution relies on an unenforced positional invariant

**File:** `src/sift/pipeline/eustack_facts.py:325-336`
**Issue:** `lock_convergence_count` flags are matched to `lock_site_exemplars` by consuming
`bundle.saturation.lock_sites` through a shared iterator in the same order the flags appear
(`site = next(lock_sites_in_order, None)`), trusting that `analyse_saturation` always emits exactly
one such flag per `lock_sites` row, in that same order (verified true today by reading
`eustack.py:813-835`). There is no defensive assertion anywhere that the two sequences actually
stayed in lockstep. If a future change to `analyse_saturation` — e.g. filtering out a below-threshold
lock site from `flags` while leaving it in `lock_sites`, or reordering either list independently —
breaks that 1:1 correspondence, this code would silently attribute a lock-convergence flag's
citations to the *wrong* lock site rather than raising, and no existing test would catch it (none
exercises more than one lock site at once).
**Fix:** After the loop, assert the iterator was fully consumed
(`assert next(lock_sites_in_order, None) is None, "lock_convergence_count flag count must equal len(lock_sites)"`),
or better, key the match on an explicit field (e.g. thread count + site string already carried by the
flag's own `message`) rather than positional order, so a future divergence fails loudly instead of
mis-citing.

### WR-02: Unknown `SaturationFlag.dimension` silently drops the flag from the block

**File:** `src/sift/pipeline/eustack_facts.py:337-338`
**Issue:** The `else: exemplars = ()` branch means any `flag.dimension` value other than the three
currently emitted by `analyse_saturation` is silently skipped — no line, and no "N further flags not
shown" disclosure, unlike the capped signature listing and progression sections which explicitly
state a dropped count. This is dormant today (exactly three dimensions exist and are all handled),
but it is a "nothing disappears silently" (CLAUDE.md load-bearing invariant) regression waiting to
happen: a future `analyse_saturation` addition (e.g. a new flag dimension for a fifth Phase-16-style
grouping) would ship with the flag computed and graded correctly, yet vanish from the prompt with no
signal that anything was omitted, unless this file is remembered to be updated in lockstep.
**Fix:** Replace the silent `()` fallback with an explicit assertion/log
(`raise AssertionError(f"unhandled SaturationFlag.dimension {flag.dimension!r}")` or a one-line
"flags of unrecognised dimension X are not yet rendered" note) so an unhandled dimension fails a test
or is visibly disclosed rather than quietly disappearing.

---

_Reviewed: 2026-07-26_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
