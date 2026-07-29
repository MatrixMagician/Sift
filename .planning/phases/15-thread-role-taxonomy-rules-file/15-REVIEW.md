---
phase: 15-thread-role-taxonomy-rules-file
reviewed: 2026-07-25T00:00:00Z
depth: deep
files_reviewed: 11
files_reviewed_list:
  - src/sift/pipeline/eustack.py
  - src/sift/adapters/eustack.py
  - src/sift/config.py
  - src/sift/rules/__init__.py
  - src/sift/rules/eustack_roles.toml
  - tests/fixtures/eustack/derive_reference_capture_derivative.py
  - tests/test_eustack_rules.py
  - tests/test_eustack.py
  - tests/test_config.py
  - tests/test_cli.py
  - docs/decisions/0015-eustack-thread-role-taxonomy.md
findings:
  critical: 0
  warning: 2
  info: 2
  total: 4
status: issues_found
---

# Phase 15: Code Review Report

**Reviewed:** 2026-07-25
**Depth:** deep
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Reviewed the eu-stack thread-role classifier (`pipeline/eustack.py`), its shared adapter helpers
(`adapters/eustack.py`), the curated rules file and its Pydantic loader (`rules/eustack_roles.toml`,
`pipeline/eustack.py::load_rules`), the `[eustack]` config surface, the fixture-derivation tool, and
the full test suite, at deep depth (call-chain tracing from `analyse_eustack` down through
`classify_signature`/`_is_resolvable`/`normalise`/`iter_frames`, and up to the only current callers,
which are all tests — this module is not yet wired into the CLI/pipeline, as expected for Phase 15).

Core correctness holds up under adversarial tracing:
- `classify_signature`'s rule-major/frame-minor loop, first-match-wins semantics, and the
  `matched-no-rule` vs `no-resolvable-frame` split are all correctly implemented and match their
  documented and tested behaviour, including the one documented ordering trap (`running` rules 1–5
  placed before the `MSIEvaluationTask::Run` idle rule). I independently re-derived this ordering trap
  against the real reference-capture derivative fixture: all 5 `running`-tagged signatures that also
  contain `MSIEvaluationTask::Run` are the *only* overlaps between any `running` pattern and any later
  rule's pattern in the real data — there is no second, undocumented instance of the shared-ancestor
  trap lurking in the 24-rule set as shipped.
- `analyse_eustack` reads `Event.raw` (never `.message`), classifies once per distinct signature and
  fans out by `Counter`-derived thread count, and produces a fully deterministic, explicitly-sorted
  five-bucket partition with no `set` iteration anywhere on the output path — the determinism and
  raw-not-message invariants both hold.
- The Pydantic loader (`Rule`/`RulesMeta`/`ThreadRoleRules`) fails loudly on every bad-input path I
  tried to construct: missing file, malformed TOML, unknown key, wrong `Literal`, unnormalised pattern,
  empty pattern, duplicate `(match, pattern)` pair. Nothing silently falls back to the packaged default.
- No new third-party dependency; no `deadlock` in `src/`; British English spelling holds throughout the
  new files.

Two Warning-level design risks and two Info-level test/doc-coverage gaps below — none block release,
but the first Warning affects a fixture-generation tool that other future phases will likely reuse.

## Warnings

### WR-01: Fixture-derivation script doesn't mirror the adapter's cap-splitting, contradicting its own docstring

**File:** `tests/fixtures/eustack/derive_reference_capture_derivative.py:52-70` (`iter_thread_blocks`)
**Issue:** `iter_thread_blocks()`'s docstring claims it "Mirrors the shipped adapter's own grouping
rule: a `TID <n>:` header line starts a new block, and every following line accrues to it until the
next header or end of file." That is only half of `EustackAdapter.parse()`'s grouping rule
(`src/sift/adapters/eustack.py:225-244`): the shipped adapter *also* force-closes a thread block and
opens a `thread=None` fallback continuation once `MAX_EVENT_LINES` (256) or `MAX_EVENT_BYTES` (65536)
is exceeded (Pitfall 5 / T-05-30). `iter_thread_blocks()` has no such cap — it accrues a thread block
to the next `TID` header or EOF unconditionally.

For the current reference dumps this is inert (documented classifying-frame depth is 8–19, far under
256 lines), but the mismatch means the tool's "signature-preserving" guarantee is not actually
guaranteed for any future capture containing a thread deeper than the cap: `derive_...py` would compute
one signature from the full untruncated stack, while re-ingesting the resulting fixture through the
real `EustackAdapter` would split that same thread into a truncated `thread=<n>` event plus one or more
`thread=None` fallback events — silently changing what `signature_of()` sees on replay, for exactly the
class of pathological/monster stack block this cap exists to guard against.

**Fix:** Either mirror the cap in `iter_thread_blocks()` (reuse `MAX_EVENT_LINES`/`MAX_EVENT_BYTES` from
`sift.adapters.eustack`, splitting a block the same way `parse()` does), or assert loudly and refuse to
run if any block exceeds the cap, e.g.:
```python
from sift.adapters.eustack import MAX_EVENT_BYTES, MAX_EVENT_LINES

def iter_thread_blocks(text: str) -> Iterator[str]:
    ...
    for block in blocks:
        if block.count("\n") > MAX_EVENT_LINES or len(block.encode()) > MAX_EVENT_BYTES:
            raise ValueError(
                "thread block exceeds the adapter's cap; derivative would not be "
                "signature-preserving after re-ingest"
            )
```

### WR-02: `_condense_symbol`'s naive `" - "` split became load-bearing without being hardened for the new stakes

**File:** `src/sift/adapters/eustack.py:69-73` (`_condense_symbol`), reused by `src/sift/pipeline/eustack.py:153` (`normalise`)
**Issue:** `_condense_symbol` was written pre-Phase-15 purely to shorten a cosmetic condensed `message`
field (`frame_body.split(" - ", 1)[0].strip()`). Phase 15 correctly reuses it (D-08) inside
`normalise()`, but reuse changes its role from cosmetic to load-bearing: the text before the first
literal `" - "` is now the exact string every rule pattern is matched against. If a real (demangled)
symbol legitimately contains a literal `" - "` substring before eu-stack's own `<lib> <source>:<line>`
separator — plausible for some compiler-generated or vendor symbol names — `normalise()` silently
truncates the symbol mid-name, and the truncated fragment is matched against the rules file with no
error raised anywhere. Nothing in this phase adds a check that what follows `" - "` actually looks like
`<lib> <source>:<line>` before trusting the split.
**Fix:** Anchor the split more specifically, e.g. require what follows to match a `<lib> <path>:<line>`
shape before treating it as the tail:
```python
_TAIL_RE = re.compile(r" - \S+\.(?:so|dll)(?:\.\d+)* \S+:\d+$")

def _condense_symbol(frame_body: str) -> str:
    return _TAIL_RE.sub("", frame_body).strip()
```
or, at minimum, document the risk next to `normalise()`'s docstring so a future curator who sees a
suspiciously short pattern knows where to look.

## Info

### IN-01: Two assertions in `test_eustack_rules.py` are tautologically guaranteed and add no real assurance

**File:** `tests/test_eustack_rules.py:552-566` (`test_derivative_coverage_is_disclosed_not_inflated`), `tests/test_eustack_rules.py:346-354` (`test_classification_partitions_all_threads`)
**Issue:** `classified_frames.isdisjoint(unclassified_frames)` can never fail given `analyse_eustack`'s
own implementation: `analysis.unclassified` is defined as `tuple(g for g in groups if g.role ==
"unclassified")`, and `classified_frames` is built by filtering the same `analysis.signatures` list for
`g.role != "unclassified"` — the two sets are complementary by construction, not by anything the test
independently verifies. Similarly, `sum(analysis.threads_by_role.values()) == analysis.total_threads`
re-derives an identity that `analyse_eustack` already guarantees by construction (`threads_by_role` is
built by summing the same `counts` that produce `total_threads`). Neither assertion would catch a real
classification-correctness regression (e.g. a rule firing on the wrong role).
**Fix:** Not a correctness bug — the *other* assertions in each of these two tests (`len(unclassified) >
0`; `total_threads == count of thread events`) do carry real signal and should stay. Consider either
deleting the tautological assertions or replacing them with something that could actually fail, e.g.
asserting a specific frame's role/subsystem against known reference-capture ground truth.

### IN-02: The "raw not message, frame 8-19 deep" claim is documented but not pinned by a deep `frame_index` regression

**File:** `tests/test_eustack_rules.py:50-58`, `tests/test_eustack_rules.py:488-506`
**Issue:** The module docstring, the tracer-test comment, and the ADR all repeat that classification
must read `Event.raw` because the real classifying frame sits 8–19 deep, past `CONDENSED_FRAMES = 5`.
Both places in the suite that assert `frame_index` (`test_tracer_thread_block_classifies_via_packaged_rules`
and `test_reference_derivative_headline_signature`) assert `frame_index == 3`, which is *inside* the
message cap and would pass even if the message-capped text happened to carry the same frame. (In
practice a `raw`→`message` swap would still be caught, since `Event.message` lines don't carry the `#N
0xADDR` prefix `iter_frames`'s regex requires, collapsing every signature to `()` — so this is a
coverage gap, not an unguarded regression path.) I independently confirmed real material exists to
close this gap: on the reference-capture derivative, 16 of 53 classified signatures have `frame_index >=
5`, including several `MSIEvaluationTask::Run` matches at indices 18/19/23/24 — exactly the "8-19 deep"
population the docs describe, currently unused as a pinned assertion.
**Fix:** Add one assertion (e.g. in `test_reference_derivative_headline_signature` or a new test) that
pins a real signature's `frame_index >= CONDENSED_FRAMES` against the packaged rules, so the headline
documented claim is actually exercised by CI rather than only being true by inspection.

---

_Reviewed: 2026-07-25_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
