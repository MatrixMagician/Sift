# ADR 0008: `sift report --format json` determinism scope (REPT-03)

**Status:** Accepted (implementation lands in Phase 6 / M6)
**Date:** 2026-07-18 (Phase 6 context; recorded per SPEC §10 open-question rule)
**Answers:** REPT-03 — in what sense is the triage report "reproducible", and what
exactly is excluded from the byte-identical comparison? Cross-refs SPEC.md §5.7
(renderers, reproducibility requirement), SPEC.md §10 (open questions #2
reportlab-vs-weasyprint, resolved by ADR 0002), and Phase 6 RESEARCH Pattern 3 /
Pitfalls 4 and 6.

## Context

REPT-03 requires that "identical case + config + model + seed ⇒ byte-identical
JSON apart from timestamps". Read naively, that sounds like a claim about the
language model producing bit-exact generations — which a local backend does not
reliably guarantee (llama-server multi-slot scheduling and continuous batching
can perturb token sampling even with a fixed seed; `sift doctor` already warns on
determinism-breaking server configs, LLM-03).

The insight that makes REPT-03 both true and honest is that **`sift report` does
zero inference**. It is a pure function of an already-analysed `case.db`: it reads
persisted `hypotheses` rows, `clusters` rows, and `triage_*` meta, and serialises
them. All model non-determinism is upstream, in `sift analyze`. So report
reproducibility reduces to two mechanical properties:

1. **Canonical serialisation** — one stable dump
   (`json.dumps(sort_keys=True, ensure_ascii=False, indent=2)` + trailing
   newline). Key order is stable regardless of insertion order; `query_*` already
   return rows in a documented order; no floats enter the document (cluster stats
   are ints/strings; salience scores are not persisted).
2. **Excluding the inherently-volatile fields** — a small set of values that
   legitimately differ run-to-run even when the analysis is identical.

The determinism *test* (`tests/test_report_determinism.py`) therefore drives the
deterministic **fake** LLM (the injected `httpx.MockTransport` server, EVAL-05):
two independent `analyze` runs over the same seeded case produce identical
`case.db`s, each rendered to JSON, then compared byte-for-byte after normalising
the excluded fields. The whole chain is reproducible in CI without a network.

## Decision

**The reproducibility guarantee is scoped to the report renderer, given an
identical `case.db` (D-07).** It is NOT a claim that a live local backend
generates bit-identical model output. That distinction is documented here so the
guarantee is not overstated (T-06-09).

**The D-06 excluded-field set is:**

| Excluded field | Why it legitimately varies | Where it lives in the JSON |
|----------------|----------------------------|----------------------------|
| generated-at timestamp | wall-clock at analyse time | `run.generated_at` (from `triage_created_at` meta) |
| absolute filesystem paths | depend on the host/user data dir | none by construction — `Event.source_file` is case-relative; dropped defensively if one ever appears |
| wall-clock durations | vary with machine load | none currently emitted; dropped defensively by key name |

**The excluded set is defined in exactly ONE place** (Pitfall 4):
`src/sift/render/json_out.py` —

- `DETERMINISM_EXCLUDED = ("generated_at",)` names the run-level timestamp field;
- `normalise_for_determinism(doc)` removes `run.generated_at`, and — as
  defence-in-depth (T-06-06) — strips any string value that is an absolute path
  and any key naming a wall-clock duration, anywhere in the document, without
  mutating its input.

Both `tests/test_report_determinism.py` and this ADR reference that single helper.
Any future addition to the excluded set is made there and nowhere else.

## Consequences

- REPT-03 is verifiable in a socket-blocked CI suite: the fake LLM makes the
  upstream analysis deterministic, and the renderer's purity makes the report
  byte-stable. The test perturbs only `generated_at` between two runs and proves
  the normalised bytes are equal — so it exercises the exclusion, not luck.
- The claim is honest about live backends: an operator diffing two reports from
  real `llama-server` runs may see differences that originate in model sampling,
  not the renderer. `sift doctor`'s determinism warning (LLM-03) and this ADR are
  where that caveat is recorded; the report's `run` block carries the model and
  prompt hash so a diff's provenance is auditable.
- `report` embeds no absolute path: `render_json` constructs no `--out`/cwd path
  into the document, and `Event.source_file` is already case-relative — so a
  report handed to a colleague leaks no host paths (T-06-06), and the defensive
  path/duration stripping in `normalise_for_determinism` is belt-and-braces.
- Because the exclusion set is single-sourced, drift between "what the test
  normalises" and "what the docs claim is excluded" cannot happen silently.
- Lineage: SPEC §10 open question #2 (reportlab vs weasyprint) is settled by
  ADR 0002 (WeasyPrint behind `sift[pdf]`); this ADR settles the *determinism
  wording* half of §5.7 — reproducibility is a renderer property scoped against
  known backend seed caveats, not an absolute model-output claim.
