# Phase 1: Skeleton, Event Contract & genericlog Adapter - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-16
**Phase:** 1-Skeleton, Event Contract & genericlog Adapter
**Areas discussed:** CLI framework & decision records, Phase-1 event persistence, Case identity & location, Timestamp semantics, genericlog event boundaries, Compressed inputs, Config precedence
**Mode:** `--auto` — all areas auto-selected; recommended option chosen for every question without user prompts.

---

## CLI framework & decision records

| Option | Description | Selected |
|--------|-------------|----------|
| Typer | Research-resolved: active (0.27.x), ergonomic subcommands, on the boring-tech list | ✓ |
| argparse | Zero-dependency stdlib, more boilerplate for 7 subcommands | |

**Choice:** Typer, plus pre-seeded ADRs in `docs/decisions/` (Typer, WeasyPrint-as-extra, hand-rolled masking) per SPEC §10.
**Notes:** [auto] recommended default, evidence-backed by STACK.md.

## Phase-1 event persistence

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal SQLite from day one | events + meta tables, user_version=1; Phase 2 extends via migrations | ✓ |
| Throwaway JSON until Phase 2 | Simpler now, write path built twice later | |

**Choice:** Minimal SQLite owned by `store.py` from the start.
**Notes:** [auto] `sift show events` must query something; avoids rework.

## Case identity & location

| Option | Description | Selected |
|--------|-------------|----------|
| XDG data dir | `~/.local/share/sift/cases/<name>/case.db`, overridable | ✓ |
| Alongside input dir | Pollutes the artefact directory under analysis | |
| CWD | Fragile, not discoverable | |

**Choice:** XDG data dir, `SIFT_DATA_DIR`/config override.
**Notes:** [auto] portable + deletable per SPEC §4.

## Timestamp semantics

| Option | Description | Selected |
|--------|-------------|----------|
| Assume UTC, mark inferred | tz-naive → UTC with `ts_confidence="inferred"`; per-node override | ✓ |
| Assume local timezone | Machine-dependent, non-reproducible | |
| Require explicit config | Hostile UX for the common case | |

**Choice:** Assume UTC + inferred confidence + configurable overrides.
**Notes:** [auto] PITFALLS.md: timezone ambiguity inverts causality in multi-node cases.

## genericlog event boundaries

| Option | Description | Selected |
|--------|-------------|----------|
| Timestamp-starts-event + continuation append, capped | 256 lines / 64 KB cap, overflow splits to unknown event | ✓ |
| Uncapped grouping | Pathological files produce single giant events | |

**Choice:** Capped grouping with never-drop overflow.
**Notes:** [auto] robustness over cleverness per SPEC §5.2.

## Compressed inputs

| Option | Description | Selected |
|--------|-------------|----------|
| Stream-decompress, decompressed offsets | Magic-byte detection; event_id offsets in decompressed stream | ✓ |
| Temp-extract to disk | Doubles disk usage, temp-file lifecycle | |
| Compressed-stream offsets | Meaningless for citation display | |

**Choice:** Stream decompression, decompressed-stream offsets.
**Notes:** [auto] keeps event_id deterministic and file:line provenance meaningful.

## Config precedence

| Option | Description | Selected |
|--------|-------------|----------|
| tomllib + plain Pydantic, hand-rolled precedence | Explicit, testable, no new dependency | ✓ |
| pydantic-settings | Adds a dependency for solved precedence logic | |

**Choice:** Hand-rolled with stdlib tomllib + Pydantic validation.
**Notes:** [auto] boring-tech rule: justify every addition.

## Claude's Discretion

- Timestamp format list and regex structure for genericlog v1
- Coverage fixture design
- `models.py` internal layout (SPEC §5.1 contract is verbatim)

## Deferred Ideas

- Progress feedback (CLI-03) → Phase 2
- `--since/--until` (RAG-06) → Phase 4
