# Walking Skeleton — Sift (Local-LLM Incident Triage Engine)

**Phase:** 1
**Generated:** 2026-07-16

## Capability Proven End-to-End

A user can run `sift new <case> --input <dir>` then `sift ingest <case>` on a directory containing an ordinary timestamped log and read the resulting canonical, deterministic events back with `sift show <case> events` — all from a clean checkout via `uv sync && uv run sift`.

The CLI command surface IS the interaction layer for this project — there is no web UI; "dev deployment" = `uv run sift` working from a clean checkout.

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| CLI framework | Typer 0.27.x, one flat `typer.Typer()` app, seven `@app.command()` functions | D-01; typed params pyright checks; SPEC §5.8 has no command groups; ADR 0001 |
| Data layer | stdlib `sqlite3`, one portable `case.db` per case, `PRAGMA user_version` migrations owned by `store.py` | D-03; Phase 2 extends the same store (no throwaway intermediate); Alembic is overkill for embedded per-case DBs |
| Case location | `$XDG_DATA_HOME/sift/cases/<name>/case.db` (fallback `~/.local/share`), overridable via `SIFT_DATA_DIR`/config/flag | D-04; deleting the case directory deletes the case |
| Config | Hand-rolled precedence flags > `SIFT_*` env > `~/.config/sift/config.toml` > defaults; stdlib `tomllib` + plain Pydantic `SiftConfig`; no pydantic-settings | D-08; one resolved typed settings object, testable without a TTY |
| Auth | None — local single-user CLI; filesystem permissions are the boundary | SPEC §3; no auth surface exists in the product |
| Deployment target | `uv run sift` from a clean checkout (Phase 1); `uv tool install` is the M8 target | SPEC §8 M1/M8 |
| Directory layout | SPEC §7 `src/sift/` subset: `cli.py`, `config.py`, `models.py`, `store.py`, `adapters/{__init__,base,genericlog}.py`; later phases add `pipeline/`, `llm/`, `render/`, `prompts/` when they have content | SPEC §7 is a map, not a day-one checklist — no empty scaffolding |
| Test isolation | Autouse pytest fixtures: XDG env redirect to tmp_path + socket-connect guard | Zero-network-in-tests and no-real-home-dir are mechanical from day one |

## Frozen Contracts (breaking after Phase 1 = breaking the project)

- **Event schema** — `models.Event`, frozen dataclass, 16 fields verbatim from SPEC §5.1. Every adapter, the store, dedup, RAG citations, and reports consume it.
- **event_id** — `sha256(source_file + "\x00" + str(byte_offset))[:16]`; `source_file` is the case-relative POSIX path (the compressed file's own path for `.gz`/`.zst`), `byte_offset` is 0-based on the DECOMPRESSED stream. Golden value pinned by test: `event_id("app.log", 12345) == "f7fdcb4b3de90265"`. Never add case_id, time, or randomness to the hash.
- **Adapter Protocol** — `base.Adapter`: `name: str`, `sniff(path) -> float`, `parse(path, case_id) -> Iterator[Event]`, verbatim from SPEC §5.2. Frozen so Phase 5's domain adapters can be built in parallel with Phase 4.
- **Adapter instance-configuration convention** — because the Protocol signature is frozen, per-run configuration travels as instance attributes set by the ingest orchestrator before `parse`: `input_root: Path | None` (for case-relative paths), `tz_overrides: dict[str, str]` (glob → IANA zone, D-05), and results come back via `last_stats: ParseStats`. Phase 5 adapters follow the same convention (e.g. dsserrors multi-node timezone overrides).
- **Registry rule** — `adapters/__init__.py` holds `REGISTRY` (insertion-ordered) + `detect()`. Adding adapter #5 = one new module + one registration line, nothing else (SPEC §5.2 hard rule).
- **Coverage formula** — `1 − unknown_fallback_bytes / total_decompressed_bytes`, where unknown-fallback events are those with `ts is None`; every decompressed byte belongs to exactly one event (span-partition invariant).

## Stack Touched in Phase 1

- [x] Project scaffold (uv src layout, Typer, ruff + DTZ rules, pyright strict, pytest) — plan 01-01
- [x] Routing equivalent — seven CLI subcommands (`new`, `ingest`, `analyze`, `report`, `show`, `eval`, `doctor`) — plan 01-01
- [x] Database — real write (`insert_events` INSERT OR IGNORE in one transaction) AND real read (`query_events`, `sift show events`) — plan 01-02
- [x] Interaction — `new` → `ingest` → `show events` end-to-end CliRunner test (RED in 01-01, GREEN in 01-02) — plans 01-01/01-02
- [x] Deployment — documented local full-stack run: `uv sync && uv run sift …` from a clean checkout — plan 01-01

## Out of Scope (Deferred to Later Slices)

- Template dedup, 100 MB-scale performance, zstd-compressed `raw` column, `show clusters`, progress feedback (CLI-03) — Phase 2
- sqlite-vec, embeddings, HDBSCAN clustering, inference client, `doctor`, prompt template files — Phase 3
- Salience, RAG, `analyze`, citation validation, `--hint`, `--since/--until`, exit-code contract (CLI-04) — Phase 4
- journald / dsserrors / eustack adapters — Phase 5 (the Protocol they implement is frozen here)
- Renderers (`report`), KB retrieval, PDF extra — Phase 6; eval harness — Phase 7; packaging/Quadlet — Phase 8
- `show events --filter` — arrives with STORE-04 in Phase 2

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this skeleton without altering its architectural decisions:

- Phase 2: 100 MB log → inspectable template groups in one portable `case.db` (`show clusters`)
- Phase 3: health-checked local inference + embeddings + semantic clusters with LLM labels
- Phase 4: `sift analyze` → ranked, citation-gated root-cause hypotheses (core value)
- Phase 5: journald / dsserrors / eustack domain adapters through the proven pipeline
- Phase 6: reviewable Markdown/JSON/PDF reports + KB retrieval
- Phase 7: golden-case eval harness with CI thresholds
- Phase 8: `uv tool install` + Podman Quadlet deployment
