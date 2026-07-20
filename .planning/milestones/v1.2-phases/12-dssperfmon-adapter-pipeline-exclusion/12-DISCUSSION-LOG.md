# Phase 12: `dssperfmon` Adapter & Pipeline Exclusion - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-20
**Phase:** 12-dssperfmon-adapter-pipeline-exclusion
**Mode:** `--auto` — no interactive prompts; every question resolved to the recommended option and logged below
**Areas discussed:** Event shape & granularity, Pipeline exclusion seam, Timezone & UTC normalisation, Nothing-disappears fallback, Sniffing & CSV parsing

---

## Event shape & granularity

| Option | Description | Selected |
|--------|-------------|----------|
| Compact short-name `message`, full row in `attrs`, verbatim line in `raw` | Human-readable and citable without repeating the `\\host\Category\` prefix 13,596 times | ✓ |
| Full PDH column paths in `message` | Faithful but enormously redundant per row | |
| One event per counter per sample | Would multiply 13,596 rows into ~313,000 events and break "one event per sample row" (criterion 1) | |

**Selected:** compact short-name rendering (D-02/D-03).
**Notes:** Roadmap criterion 1 already locks one event per sample row, so the only live question was
message/attrs content. Severity fixed at `info` for parsed rows — the adapter never infers severity
from counter magnitude; threshold judgement belongs to Phase 13's correlator (D-05).

---

## Pipeline exclusion seam (PERF-03 — the phase's main hazard)

| Option | Description | Selected |
|--------|-------------|----------|
| Filter inside `store.iter_event_summaries()` | Scouting proved this is the SOLE read seam for dedup, cluster, hypothesise and eval/runner; salience inherits it transitively via clusters. One edit covers all four stages. | ✓ |
| Add a filter to each of `dedup.py`, `cluster.py`, `salience.py` | Four near-identical predicates that can drift apart — exactly what the roadmap note warns against | |
| Filter at ingest (don't store perfmon events in `events`) | Would violate criterion 5 — samples must stay individually citable by `event_id` | |

**Selected:** the single `iter_event_summaries` seam (D-06/D-07).
**Notes:** Evidence gathered this session — `grep` for the seam's callers returned exactly
`dedup.py:102`, `cluster.py:113`, `hypothesise.py:191`, `eval/runner.py:63`; `salience.rank_clusters`
takes `Cluster`/`TemplateGroup` and never reads events. Two guards recorded because they are the
places this can silently go wrong: `iter_event_rows` must stay unfiltered (D-08, and it sits
adjacent to the filtered method reading almost identically — a "tidy into a shared helper" refactor
would break citation), and criterion 4 must land as an automated byte-identity test rather than a
manual check (D-09).

---

## Timezone & UTC normalisation

| Option | Description | Selected |
|--------|-------------|----------|
| Trust the declared numeric bias (`(300)` → UTC = local + 300 min) | The artefact declares it; no mapping table, no inference | ✓ |
| Map the Windows zone name to IANA and resolve DST per-sample | Needs a mapping table and makes Sift *infer* an alignment | |
| Infer the offset by maximising CSV/log window overlap | Explicitly forbidden by REQUIREMENTS.md § Out of Scope | |

**Selected:** declared bias, verbatim (D-10/D-11/D-12).
**Notes:** One unresolved risk was raised and recorded rather than assumed away (D-13): PDH's declared
bias is the *standard-time* bias (300 = EST), but the reference file spans 2026-04-02 → 04-07, which
is EDT (240). If PDH writes local wall-clock while declaring the standard bias, every sample lands an
hour off and Phase 13's correlation breaks silently. The roadmap's own "ends 6 s before the denial
banner" claim implies the current reading aligns, but that is an inference from a summary, not a
verification against the artefacts — flagged for the researcher to confirm before the parser freezes.
Resolution rule if it fails: disclose and flag loudly, never silently DST-correct.

---

## Nothing-disappears fallback (PERF-02 / criterion 3)

| Option | Description | Selected |
|--------|-------------|----------|
| Row-level `severity="unknown"` when any cell is blank/non-numeric | Matches criterion 3's wording literally; keeps one-event-per-row | ✓ |
| Cell-level tolerance, row stays `info` with bad cells nulled | Contradicts criterion 3 | |
| Skip malformed rows | Violates "nothing disappears silently" outright | |

**Selected:** row-level unknown, bytes counted into `unknown_fallback_bytes` (D-14/D-15/D-16).
**Notes:** Verified against the real artefact — the deny CSV has **zero** blank or non-numeric cells
across all 13,596 rows, so these paths cannot be exercised by reference data and need synthetic
fixtures (D-17). Column-count drift is *survived* here; *flagging* it is Phase 13's PERF-05.

---

## Sniffing & CSV parsing

| Option | Description | Selected |
|--------|-------------|----------|
| Sniff the literal `(PDH-CSV 4.0)` token; stdlib `csv` for fields, byte-lines for offsets | Unambiguous signal, no new dependency, preserves offset determinism | ✓ |
| Hand-rolled comma splitting | Breaks on the quoted fields containing backslashes, parens and commas | |
| Let `csv.reader` own the file read loop | Loses byte-offset accounting and breaks `event_id` determinism | |

**Selected:** stdlib `csv` per decoded row, byte-lines owning the read loop (D-18/D-19/D-20).
**Notes:** Mirrors how `dsserrors` reuses `genericlog.byte_lines`. Registration is one `REGISTRY` line
subclassing `ConfigurableAdapter` per ADR 0006.

---

## Claude's Discretion

Auto mode selected the recommended option for every question above. Left open for the planner:
internal decomposition of `adapters/dssperfmon.py`; exact `attrs` key spellings; fixture naming;
whether the `EXCLUDED_FROM_RANKING` constant lives in `store.py` or a small shared module.

## Todos Reviewed

- `2026-07-20-phase11-code-review-info.md` matched at score 0.9 (auto-fold threshold 0.4) but was
  **not folded** — its frontmatter carries `resolves_phase: 14` and both items touch `mcm_facts.py`
  and `hypothesise.py` MCM-splice code that Phase 12 does not modify. The high score was a keyword
  false positive on the shared word "pipeline". Left for Phase 14 as tagged.

## Deferred Ideas

Nothing new surfaced beyond the milestone's existing phase split — deferrals recorded in CONTEXT.md
`<deferred>` are all pre-existing Phase 13/14 scope (correlation figures, hazard flags,
`sift perfmon`, fact injection, golden eval case, perfmon fact-block size cap).
