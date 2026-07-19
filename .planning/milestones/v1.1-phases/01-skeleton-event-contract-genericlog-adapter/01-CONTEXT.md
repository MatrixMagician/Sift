# Phase 1: Skeleton, Event Contract & genericlog Adapter - Context

**Gathered:** 2026-07-16
**Status:** Ready for planning

<domain>
## Phase Boundary

A user can run `sift new <case> --input <dir>` then `sift ingest <case>` on a directory of ordinary timestamped logs (including gzip/zstd-compressed) and get a queryable case of canonical, deterministic Event records — nothing dropped silently — then inspect them with `sift show <case> events`. Delivers: project skeleton (uv, ruff, pyright, pytest), frozen Event schema, Adapter protocol + registry with sniff-based auto-detection, the genericlog fallback adapter, per-file parse-coverage reporting, idempotent re-ingest, UTC timestamp normalisation with `ts_confidence`, and CLI config precedence. Maps to SPEC.md milestone M1.

Not in this phase: template dedup and 100 MB-scale performance (Phase 2), embeddings/clustering/LLM anything (Phase 3+), domain adapters journald/dsserrors/eustack (Phase 5).

</domain>

<decisions>
## Implementation Decisions

### CLI framework & decision records
- **D-01:** Typer (0.27.x) for the CLI — research-resolved over argparse (active project, ergonomic subcommands, already on the SPEC's boring-tech list). [auto: recommended]
- **D-02:** Pre-seed `docs/decisions/` ADRs during this phase for the three research-resolved SPEC open questions: Typer over argparse; WeasyPrint behind a `sift[pdf]` optional extra (deferred to Phase 6 implementation); hand-rolled volatile-token masking over drain3 (dormant, Python ≤ 3.11). SPEC §10 requires decisions recorded in `docs/decisions/`. [auto: recommended]

### Phase-1 event persistence
- **D-03:** Minimal SQLite store lands in Phase 1 (events + meta tables, `PRAGMA user_version = 1`), owned by `store.py` from day one. `sift show events` queries it. Phase 2 extends the same store with migrations (chunks/clusters, zstd compression, sqlite-vec comes later still, lazily at first embed). No throwaway JSON intermediate. [auto: recommended — avoids building the write path twice]

### Case identity & location
- **D-04:** Cases live at `~/.local/share/sift/cases/<case-name>/case.db` (XDG data dir; respect `XDG_DATA_HOME`). Case name is the user-facing identifier; the case records the absolute input dir it was created from. Location overridable via config/`SIFT_DATA_DIR`. Deleting the case directory deletes the case. [auto: recommended]

### Timestamp semantics
- **D-05:** Timezone-naive timestamps assume UTC and are recorded with `ts_confidence="inferred"`; only explicit-offset timestamps get `"exact"`. Per-node/per-glob timezone overrides configurable (mechanism must exist in Phase 1 config schema; dsserrors multi-node use arrives Phase 5). Year-less syslog timestamps infer year from file mtime, `ts_confidence="inferred"`. Assumptions disclosed in ingest coverage output. [auto: recommended — prevents silent causality inversion (PITFALLS)]

### genericlog event boundaries
- **D-06:** A line with a parseable timestamp starts a new event; indented or timestamp-less lines append to the preceding event (continuation). Safety cap per event: 256 lines or 64 KB — on overflow, split into a new `severity="unknown"` event rather than dropping or unbounded growth. Leading unparseable region of a file becomes its own `unknown` event. [auto: recommended]

### Compressed inputs
- **D-07:** gzip (stdlib) and zstd (zstandard, already a SPEC dependency) inputs are stream-decompressed during parse; `byte_offset` for `event_id` refers to the **decompressed** stream; `source_file` records the compressed file's relative path. Detection by magic bytes, not extension. [auto: recommended — keeps event_id deterministic and citation display consistent]

### Config precedence
- **D-08:** Hand-rolled precedence (flags > `SIFT_*` env > `~/.config/sift/config.toml` > defaults) using stdlib `tomllib` + a plain Pydantic model for validation. No pydantic-settings dependency. Config module exposes one resolved, typed settings object. [auto: recommended — one fewer dependency, explicit and testable]

### Claude's Discretion
- Exact timestamp format list for genericlog v1 (ISO 8601 variants, syslog, epoch s/ms) and regex structure — planner/executor decide, guided by SPEC §5.2.
- Fixture design for the ≥ 99% parse-coverage acceptance test.
- Internal layout of `models.py` (frozen dataclass per SPEC §5.1 — verbatim contract).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Specification (authoritative)
- `SPEC.md` §5.1 — canonical Event schema (frozen dataclass, field-by-field contract; verbatim)
- `SPEC.md` §5.2 — Adapter protocol, sniff auto-detection rules, genericlog behaviour
- `SPEC.md` §5.8 — CLI design, config precedence
- `SPEC.md` §8 M1 — acceptance criteria for this phase
- `SPEC.md` §10 — open questions to record in `docs/decisions/`

### Research (constraints & pitfalls for this phase)
- `.planning/research/STACK.md` — validated versions (Typer 0.27.x, zstandard); what not to use (drain3)
- `.planning/research/PITFALLS.md` — timezone/causality pitfall, multi-line record handling, encoding edge cases
- `.planning/research/ARCHITECTURE.md` — component boundaries, build-order notes (frozen Protocol enables Phase 5 parallelism)

### Project
- `.planning/REQUIREMENTS.md` — INGST-01..06, INGST-10, INGST-11, CLI-01 (this phase's scope)
- `CLAUDE.md` — repo conventions (British English, boring tech, zero network in tests, uv workflow)

</canonical_refs>

<code_context>
## Existing Code Insights

Greenfield — no code exists yet (repo contains SPEC.md, README.md, planning docs only).

### Established Patterns
- Repository layout is prescribed by SPEC.md §7 (`src/sift/…`, `tests/`, `eval/`, `deploy/`) — follow it exactly.
- Quality gate: `ruff check`, `pyright`, `pytest` clean is part of "done" (CLAUDE.md).

### Integration Points
- The Event schema and Adapter protocol frozen here are the contract every later phase builds on (store, dedup, adapters, RAG citations). Treat schema changes after this phase as breaking.

</code_context>

<specifics>
## Specific Ideas

- Adapter modules must be self-contained: adding a fifth adapter must require zero changes outside a new module + registration (SPEC §5.2) — the registry design in this phase must honour that.
- Parse coverage is a first-class metric surfaced by `sift ingest` output, not a hidden log line.
- `event_id = sha256(source_file, byte_offset)[:16]` — idempotency test is "second ingest adds zero events".

</specifics>

<deferred>
## Deferred Ideas

- Progress feedback on long ingest (CLI-03) — Phase 2 scope per roadmap fold-in.
- `--since/--until` time filters (RAG-06) — Phase 4 (analysis scoping).
- None others — discussion stayed within phase scope.

</deferred>

---

*Phase: 1-Skeleton, Event Contract & genericlog Adapter*
*Context gathered: 2026-07-16*
