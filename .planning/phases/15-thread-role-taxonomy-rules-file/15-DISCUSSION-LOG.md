# Phase 15: Thread-Role Taxonomy & Rules File - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-25
**Phase:** 15-thread-role-taxonomy-rules-file
**Areas discussed:** Frame-matching strategy, Symbol normalisation, Rules-file schema, Phase 15 output surface

---

## Frame-matching strategy

### Q1 — Which loop is the outer one, i.e. what decides precedence?

| Option | Description | Selected |
|--------|-------------|----------|
| Rule-major, file order | For each rule in file order, scan every frame; first rule matching anywhere wins. File order is the precedence knob | ✓ |
| Frame-major, leaf outward | For each frame `#0`→`#N`, test every rule; deepest matching frame wins. Leaf-priority — `pthread_cond_timedwait` at `#0` beats the application frame at `#8` | |
| Deepest-application-frame first | Walk past non-application frames, match rules against the deepest MicroStrategy frame only. Requires an `is_app_frame()` predicate — a hidden second taxonomy in Python | |

**User's choice:** Rule-major, file order (recommended)
**Notes:** The only option under which success criterion 2 is predictable, and the only one where a curator can order `MSIQTask::GetNextPreferredJob → idle-parked` above a libc-wait rule.

### Q2 — Is `running` rule-matched or the residual fallback?

| Option | Description | Selected |
|--------|-------------|----------|
| Rule-matched, like the rest | `running` needs its own rules; `unclassified` is the sole residual | ✓ |
| Residual default | Anything matching no wait-shaped rule is `running`; `unclassified` only for unresolvable symbols | |

**User's choice:** Rule-matched (recommended)
**Notes:** A residual `running` would silently label unrecognised stacks as working — the guess EUS-02 forbids — and would drive the unclassified rate to near-zero, hiding the drift signal.

### Q3 — What exactly is a signature?

| Option | Description | Selected |
|--------|-------------|----------|
| Full ordered symbol tuple | Every frame's normalised symbol, full depth, addresses excluded. 93 signatures | ✓ |
| Depth-capped symbol tuple | Truncated at a fixed depth (~20). Bounds memory; cap is an authored number | |
| Leading-N-frames tuple | First N frames only. Collapses stacks differing below the cap — where the role lives | |

**User's choice:** Full ordered symbol tuple (recommended)
**Notes:** Addresses excluded because Phase 19 criterion 3 requires surviving cosmetic mutation. The same tuple feeds Phase 16's EUS-06 signature collapse.

### Q4 — What does classifying one signature return?

| Option | Description | Selected |
|--------|-------------|----------|
| Role + matched pattern + frame index | Plus subsystem. Pattern text, not row index, so reordering the file does not change meaning | ✓ |
| Role only | Smallest surface; an engineer cannot confirm which rule fired | |
| Role + full match trace | Every rule that would have matched. Loses the early exit; nothing downstream consumes it | |

**User's choice:** Role + matched pattern + frame index (recommended)

---

## Symbol normalisation

Measured against the real capture during the discussion: 3,552 frames carry `@@GLIBC` suffixes across only 3 distinct symbols; 2,962 carry template arguments; 0 carry a ` - <lib> <src>:<line>` tail; 0 are unresolved. Signature counts: raw 93, GLIBC-stripped 93, templates-stripped 88, both 88.

### Q1 — What does `normalise(symbol)` strip?

| Option | Description | Selected |
|--------|-------------|----------|
| Version + lib suffixes, keep templates | Strip `@@GLIBC_x.y.z` and ` - <lib> <src>:<line>`. Preserves 93 signatures | ✓ |
| Also strip template argument lists | More build-stable, shorter to curate. Measured cost: 93→88 signatures, 374→363 symbols | |
| No normalisation — match raw | Perfectly faithful; a different-glibc host silently drops every libc rule to unclassified | |

**User's choice:** Version + lib suffixes, keep templates (recommended)
**Notes:** Template variance is already handled by a `contains` rule on the pre-`<` prefix, so no lossy transform is needed.

### Q2 — What happens to an un-normalised pattern at load?

| Option | Description | Selected |
|--------|-------------|----------|
| Reject loudly at load | Error names the canonical form. Matches the `extra="forbid"` house discipline | ✓ |
| Normalise silently | Tolerates copy-paste; lets two spellings of one rule coexist | |
| Match patterns raw | Simplest loader; a pasted `@@GLIBC` pattern is silently dead | |

**User's choice:** Reject loudly at load (recommended)

### Q3 — How does an unresolvable (`??` / bare-address) frame behave?

| Option | Description | Selected |
|--------|-------------|----------|
| Skip as candidate, count separately | Stays in the signature; all-unresolvable threads counted apart from "matched no rule" | ✓ |
| One unresolved frame condemns the thread | Maximally conservative; throws away stacks with a clear application frame | |
| Drop unresolved frames entirely | Simplest; collapses signatures and hides how much of the capture lacked symbols | |

**User's choice:** Skip as candidate, count separately (recommended)
**Notes:** Two different problems with two different fixes — curate a rule, versus obtain symbols. `PITFALLS.md:120-122` asks for exactly this split.

### Q4 — Where does the frame-splitting regex live?

| Option | Description | Selected |
|--------|-------------|----------|
| Share the adapter's regex | Expose `iter_frames(raw)` from `adapters/eustack.py` on the existing `_FRAME_RE` | ✓ |
| Classifier owns its own regex | Smaller diff, shipped adapter untouched; two regexes for one format | |
| Adapter stores frames in `attrs` | No re-parse at analysis time; changes shipped output shape, forces re-ingest | |

**User's choice:** Share the adapter's regex (recommended)
**Notes:** Precedent is in that same file — `byte_lines` is imported from `genericlog` explicitly "to avoid a drifting verbatim copy" (`eustack.py:45-46`).

---

## Rules-file schema

### Q1 — Which match kinds, and what is the default?

| Option | Description | Selected |
|--------|-------------|----------|
| All three, `exact` is the default | `exact`/`prefix`/`contains`; omitting `match` means `exact`, so looseness is always typed and greppable | ✓ |
| All three, `contains` is the default | Shortest rules; every terse rule is silently the loosest kind | |
| `exact` and `prefix` only | ADR 0013 class structurally impossible; awkward for 2,962 template-bearing frames | |

**User's choice:** All three, `exact` is the default (recommended)
**Notes:** ADR 0013's `"MCM"` was 3 chars against 64 KB of arbitrary content; a pattern here is matched against one symbol of tens of characters — real risk, smaller. `fnmatch` stays a documented escape hatch, not added now.

### Q2 — What does a rule carry beyond role and pattern?

| Option | Description | Selected |
|--------|-------------|----------|
| One required `subsystem` field | Phase 16 groups by `(role, subsystem)` for both occupancy and dependency splits | ✓ |
| Two fields: `pool` and `dependency` | More precise; each null for most roles, curation question on every rule | |
| Role only — Phase 16 adds the label | Smallest schema now; Phase 16 backfills every rule | |

**User's choice:** One required `subsystem` field (recommended)

### Q3 — What provenance lands in Phase 15?

| Option | Description | Selected |
|--------|-------------|----------|
| File `[meta]` now, store write in Phase 17 | `version` + `validated_against` in the file; loader computes `sha256(text)[:16]` | ✓ |
| File `[meta]` and store write, both now | Whole chain done; Phase 15 gains a store dependency with no reader until 17 | |
| No file metadata — git history is the version | Nothing to bump; a `rules_path` copy has no git history at all | |

**User's choice:** File `[meta]` now, store write in Phase 17 (recommended)

### Q4 — How strict is the loader?

| Option | Description | Selected |
|--------|-------------|----------|
| Strict Pydantic, `unclassified` illegal as a rule role | `extra="forbid"`, role Literal of four buckets, empty patterns and duplicate `(match, pattern)` rejected | ✓ |
| Strict fields, free-form role string | Allows an experimental sixth bucket; the five stop partitioning the population | |
| Permissive parse | A misspelt key silently yields a rule that never fires | |

**User's choice:** Strict Pydantic, `unclassified` illegal as a rule role (recommended)
**Notes:** A rule asserting `unclassified` would be a rule that matches and then claims not to have matched.

---

## Phase 15 output surface

### Q1 — What is the deliverable surface?

| Option | Description | Selected |
|--------|-------------|----------|
| Library + fixture tests, no command | `pipeline/eustack.py` returning a summary object; Phase 9 / Phase 12 precedent | ✓ |
| Minimal `sift eustack` now, grown in 16–17 | Directly demonstrable at the terminal; three phases editing one command | |
| Surface through an existing command | No new command; puts analysis where Phase 17 must move it from | |

**User's choice:** Library + fixture tests, no command (recommended)
**Notes:** v1.1 split Phase 9 (MCM detection) from Phase 10 (`sift mcm`); v1.2 split Phase 12 from Phase 13. Same shape.

### Q2 — What does CI run against?

| Option | Description | Selected |
|--------|-------------|----------|
| Signature-preserving derivative + real capture at verify | ~80 KB fixture with all 93 signatures, thread counts capped; full capture measured at verification, ADR 0013 style | ✓ |
| Commit the full capture | Every literal number asserted in CI; 2.4 MB and a customer environment identifier | |
| Hand-authored synthetic fixture only | Tiny and controlled; a fixture authored to match the detector — the named `PITFALLS.md` failure mode | |

**User's choice:** Signature-preserving derivative + real capture at verify (recommended)
**Notes:** Largest committed fixture in the repo today is 13 KB. Filename and PID to be sanitised; frames are C++ symbols and carry no identifiers.

### Q3 — At what granularity is unclassified reported?

| Option | Description | Selected |
|--------|-------------|----------|
| Per unclassified signature, ranked by thread count | Full list, not top-N; capping is Phase 17's visible rendering decision | ✓ |
| Aggregate count plus one example frame | Exactly criterion 3 and nothing more; hides all but one shape | |
| Per unmatched frame symbol | Answers "what vocabulary is missing"; mixes real gaps with noise | |

**User's choice:** Per unclassified signature, ranked by thread count (recommended)

### Q4 — How do the new files lay out?

| Option | Description | Selected |
|--------|-------------|----------|
| One pipeline module + rules data package | `sift/rules/` pure data mirroring `sift/prompts/`; all code in `pipeline/eustack.py` | ✓ |
| Split loader out into `sift/rules/loader.py` | Self-describing rules package; would be the first mixed package | |
| Everything in `pipeline/eustack.py`, TOML beside it | Fewest paths; breaks the data/code split Phase 8's packaging settled | |

**User's choice:** One pipeline module + rules data package (recommended)

---

## Claude's Discretion

No area was delegated with "you decide". Three questions were surfaced and explicitly not taken up — left to the planner's normal judgement:

- How many rules the initial curated `eustack_roles.toml` carries, and which subsystems it must cover on day one
- Whether `[eustack] rules_path` needs a path-traversal or containment guard
- Whether an ADR is written this phase for the rule-major/first-match-wins and normalisation decisions, or folded into a single v1.3 eu-stack ADR later

## Deferred Ideas

None raised during the discussion — it stayed inside the phase boundary throughout. Pre-existing deferrals relevant to this phase (EUSV2-02 `/proc/<tid>/stat` state codes, EUSV2-03 graded saturation thresholds, symbol re-demangling as a permanent non-goal) are recorded in CONTEXT.md.

Two pending todos matched Phase 15 on keywords and were reviewed but **not** folded:

- `2026-07-21-embedding-batch-composition-determinism.md` — already carries `resolves_phase: 20` (DET-01 / SEED-002)
- `2026-07-21-generation-context-unset.md` — matched on the word "toml" alone; concerns `generation.context` and the prompt budget
