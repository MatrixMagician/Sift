---
phase: 11-mcm-facts-into-sift-analyze-golden-eval-case
reviewed: 2026-07-20T00:00:00Z
depth: deep
files_reviewed: 8
files_reviewed_list:
  - src/sift/pipeline/mcm_facts.py
  - src/sift/pipeline/hypothesise.py
  - src/sift/cli.py
  - src/sift/prompts/mcm_facts.md
  - src/sift/prompts/triage.md
  - eval/cases/mcm-denial/truth.yaml
  - eval/cases/mcm-denial/README.md
  - eval/cases/mcm-denial/input/hartford_deny_slice.log
findings:
  critical: 0
  warning: 1
  info: 3
  total: 4
status: issues_found
---

# Phase 11: Code Review Report

**Reviewed:** 2026-07-20
**Depth:** deep (cross-file: traced `render_mcm_facts` -> `analyse_mcm` model tree, `_assemble` citation union, `PromptBudget`)
**Files Reviewed:** 8
**Status:** issues_found (no blockers)

## Summary

Phase 11 injects deterministic MCM facts into the triage prompt and makes them
citable. I traced every load-bearing invariant end-to-end and all hold:

- **Citation invariant (`cited ⊆ prompted ⊆ store`): SOUND.** The
  `prompted_ids` union (`hypothesise.py:271`) adds exactly the ids the renderer
  printed as `[evt:]` tokens. Each `ids.add(x)` in `render_mcm_facts` is paired
  1:1 with a `lines.append(f"[evt:{x}] ...")` using the same id — no id enters
  the set that was not printed, and none is printed without entering the set.
  Provenance is real: `ep.denial_event_id` is a real store row (`McmEpisode`
  docstring / boundary invariant), flag ids are `cite = (ep.denial_event_id,)`
  (`mcm.py:639`), and attribution row ids come from the dsserrors event stream
  (`mcm.py:930`). A hostile log field smuggling a fake `[evt:deadbeef]` into a
  rendered line does **not** break the gate — `deadbeef` is never unioned into
  `prompted_ids`, so a citation of it is correctly FLAGGED.
- **No IndexError on `[0]` access.** `flag.event_ids` is always
  `(denial_event_id,)` (non-empty by construction); `row.event_ids` is always
  ≥1 because a bucket entry is only created alongside an appended `eid`
  (`mcm.py:927-930`). Both `[0]` reads are safe.
- **Byte-identical additivity: SOUND.** `_MCM_BLOCK_RE` (`hypothesise.py:87`)
  is anchored, non-greedy and DOTALL and captures the trailing `\n`, so the
  no-MCM strip returns the template to its pre-phase `...Evidence:\n` bytes
  with no residue. Verified against `triage.md` lines 48-50.
- **Numbers computed, never authored.** `value_pct` is passed through verbatim
  (`{flag.value_pct:.1f}`), identical to the report renderer. `granted_bytes`
  is the authoritative figure; MB is a display derivation.
- **Sanitisation.** Every log-derived string reaching the prompt (`key`,
  `message`, `label`, `severity`, `dimension`, `denial_ts`) is routed through
  `render._util.sanitise`; event ids (sha256 hex) are safe unsanitised. The
  fragment also frames the block as untrusted data (V5 defence).
- Type hints complete; `X | None` used; no mutable defaults; frozen Pydantic
  models; `McmThresholdsConfig()` default is a real instance, not a shared
  mutable; no new dependencies. British English throughout user-facing strings.
- The README's claimed sensitivity test `test_mcm_denial_citation_validity_is_mcm_sensitive`
  exists (`tests/test_eval_cases.py:233`).

Findings below are all robustness/consistency notes, none blocking.

## Warnings

### WR-01: MCM fact block is not counted against `PromptBudget`; unbounded in episode count

**File:** `src/sift/pipeline/hypothesise.py:369-380`, `src/sift/llm/budget.py:49-57`
**Issue:** `PromptBudget.fit(excerpts)` budgets only the cluster-excerpt list
against `ctx_tokens - reserve_out`; the template prefix — which now carries the
spliced MCM fact block — is not subtracted. This mirrors the pre-existing KB
block, but MCM differs in one way that matters: KB is bounded upstream by
top-k retrieval, whereas the MCM block grows with the **number of denial
episodes** (`for ea in analysis.episodes:`), each contributing ~1 denial line +
up to 5 flag lines + up to 15 attribution lines (top-5 × 3 dimensions). D-19
bounds rows *per dimension per episode* but nothing bounds episode count. A case
with many denial episodes can therefore inflate the un-budgeted prefix and push
the assembled prompt past the model context, causing a server-side error or
silent truncation of the fact block the citation gate depends on.
**Fix:** Reserve the resolved-template token cost (KB + MCM prefix) from the
budget before `fit`, e.g. subtract `budget.count(template)` from the excerpt
allowance, or cap total MCM lines (e.g. top-N episodes). Confidence: medium —
real denial-episode counts per case are usually small, so exposure is bounded
in practice.

## Info

### IN-01: Two derivation paths for granted-MB (renderer vs report)

**File:** `src/sift/pipeline/mcm_facts.py:107`
**Issue:** `render_mcm_facts` computes `granted_mb = row.granted_bytes / 1024**2`
then formats `:,.1f`, while `render/mcm_report.py:79-81` computes
`round(granted_bytes / 1024**2, 3)` then formats `:,.1f`. Same divisor and same
1-dp display, so real byte counts agree — but the double-round in the report
path is a second, divergent derivation of the same figure. The review's
"never round differently" guard is satisfied in practice; the risk is drift if
one path is later edited.
**Fix:** Share one `_mb_bytes` helper between the two modules so there is a
single source of truth for the byte→MB display conversion.

### IN-02: Block-strip correctness depends on the START sentinel never containing `-->`

**File:** `src/sift/pipeline/hypothesise.py:87-90`
**Issue:** `_MCM_BLOCK_RE`'s `<!-- MCM_BLOCK_START.*?-->` relies (correctly, non-
greedily) on the first `-->` being the START comment's own terminator. If the
long parenthetical inside the START marker in `triage.md:48` is ever edited to
include a literal `-->`, the strip truncates early and the no-MCM byte-identity
invariant silently breaks. There is no guard/test asserting the stripped output
equals the pre-phase template bytes.
**Fix:** Add a one-line regression asserting `_apply_mcm_block(triage_template,
None)` reproduces the pre-MCM template bytes, so a future comment edit that
reintroduces `-->` fails loudly.

### IN-03: `re.DOTALL` on `_MCM_MARKER_RE` is redundant; MCM-present path emits a double newline

**File:** `src/sift/pipeline/hypothesise.py:90`, `:106`
**Issue:** `_MCM_MARKER_RE` matches single-line markers, so `re.DOTALL` is
inert (no `.` needs to cross a newline). Separately, on the MCM-present path the
loaded fragment already ends in `\n` and it replaces the `<<MCM_FACTS>>` line
(also `\n`-terminated), yielding a blank line before the appended excerpts.
Cosmetic only — it does not affect the no-MCM byte-identity path, the prompt
hash of the MCM path (which is a new prompt anyway), or citation behaviour.
**Fix:** Drop the unused `re.DOTALL` flag; optionally trim one trailing newline
from the fragment or the splice if the blank line is undesirable.

---

_Reviewed: 2026-07-20_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
