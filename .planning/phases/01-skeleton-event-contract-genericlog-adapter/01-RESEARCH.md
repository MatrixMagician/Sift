# Phase 1: Skeleton, Event Contract & genericlog Adapter - Research

**Researched:** 2026-07-16
**Domain:** Python CLI scaffolding (uv/Typer), deterministic log parsing, timestamp normalisation, SQLite persistence
**Confidence:** HIGH (stdlib behaviour verified by execution this session; package versions verified against PyPI JSON API; Typer/zstandard APIs from official docs via Context7)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### CLI framework & decision records
- **D-01:** Typer (0.27.x) for the CLI — research-resolved over argparse (active project, ergonomic subcommands, already on the SPEC's boring-tech list). [auto: recommended]
- **D-02:** Pre-seed `docs/decisions/` ADRs during this phase for the three research-resolved SPEC open questions: Typer over argparse; WeasyPrint behind a `sift[pdf]` optional extra (deferred to Phase 6 implementation); hand-rolled volatile-token masking over drain3 (dormant, Python ≤ 3.11). SPEC §10 requires decisions recorded in `docs/decisions/`. [auto: recommended]

#### Phase-1 event persistence
- **D-03:** Minimal SQLite store lands in Phase 1 (events + meta tables, `PRAGMA user_version = 1`), owned by `store.py` from day one. `sift show events` queries it. Phase 2 extends the same store with migrations (chunks/clusters, zstd compression, sqlite-vec comes later still, lazily at first embed). No throwaway JSON intermediate. [auto: recommended — avoids building the write path twice]

#### Case identity & location
- **D-04:** Cases live at `~/.local/share/sift/cases/<case-name>/case.db` (XDG data dir; respect `XDG_DATA_HOME`). Case name is the user-facing identifier; the case records the absolute input dir it was created from. Location overridable via config/`SIFT_DATA_DIR`. Deleting the case directory deletes the case. [auto: recommended]

#### Timestamp semantics
- **D-05:** Timezone-naive timestamps assume UTC and are recorded with `ts_confidence="inferred"`; only explicit-offset timestamps get `"exact"`. Per-node/per-glob timezone overrides configurable (mechanism must exist in Phase 1 config schema; dsserrors multi-node use arrives Phase 5). Year-less syslog timestamps infer year from file mtime, `ts_confidence="inferred"`. Assumptions disclosed in ingest coverage output. [auto: recommended — prevents silent causality inversion (PITFALLS)]

#### genericlog event boundaries
- **D-06:** A line with a parseable timestamp starts a new event; indented or timestamp-less lines append to the preceding event (continuation). Safety cap per event: 256 lines or 64 KB — on overflow, split into a new `severity="unknown"` event rather than dropping or unbounded growth. Leading unparseable region of a file becomes its own `unknown` event. [auto: recommended]

#### Compressed inputs
- **D-07:** gzip (stdlib) and zstd (zstandard, already a SPEC dependency) inputs are stream-decompressed during parse; `byte_offset` for `event_id` refers to the **decompressed** stream; `source_file` records the compressed file's relative path. Detection by magic bytes, not extension. [auto: recommended — keeps event_id deterministic and citation display consistent]

#### Config precedence
- **D-08:** Hand-rolled precedence (flags > `SIFT_*` env > `~/.config/sift/config.toml` > defaults) using stdlib `tomllib` + a plain Pydantic model for validation. No pydantic-settings dependency. Config module exposes one resolved, typed settings object. [auto: recommended — one fewer dependency, explicit and testable]

### Claude's Discretion
- Exact timestamp format list for genericlog v1 (ISO 8601 variants, syslog, epoch s/ms) and regex structure — planner/executor decide, guided by SPEC §5.2.
- Fixture design for the ≥ 99% parse-coverage acceptance test.
- Internal layout of `models.py` (frozen dataclass per SPEC §5.1 — verbatim contract).

### Deferred Ideas (OUT OF SCOPE)
- Progress feedback on long ingest (CLI-03) — Phase 2 scope per roadmap fold-in.
- `--since/--until` time filters (RAG-06) — Phase 4 (analysis scoping).
- None others — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INGST-01 | `sift new` + `sift ingest` produce canonical Events with deterministic IDs `sha256(source_file, byte_offset)[:16]` | Event-ID canonical serialisation (Pattern 3); byte-offset-on-raw-bytes streaming parse (Pattern 4); SQLite schema (Pattern 6) |
| INGST-02 | Re-ingest adds zero events | `INSERT OR IGNORE` on `event_id` PRIMARY KEY inside one transaction (Pattern 6); deterministic file walk order |
| INGST-03 | `sniff()` on first 64 KB, ≥ 0.5 wins, genericlog fallback, `--adapter glob=name` override | Adapter registry design (Pattern 2); sniff-on-decompressed-bytes rule (Pitfall 4); Typer repeated `list[str]` option (Code Example 1) |
| INGST-04 | genericlog parses ISO 8601 / syslog / epoch, groups continuation lines | Timestamp detection ladder (Pattern 5, verified `fromisoformat` behaviour); D-06 grouping algorithm |
| INGST-05 | Unparseable regions → `severity="unknown"` events; per-file parse-coverage metric | Coverage formula defined so it cannot trivially read 100% (Pattern 7) |
| INGST-06 | Multi-line records are one event | Continuation grouping + 256-line/64 KB cap (D-06, Pattern 5) |
| INGST-10 | gzip/zstd ingest without manual decompression | Magic-byte detection (verified: gzip `1f 8b`, zstd `28 b5 2f fd`); `gzip` stdlib multi-member verified; `zstandard.stream_reader(read_across_frames=True)` (Code Example 3) |
| INGST-11 | UTC normalisation, per-node tz override, `ts_confidence` | `zoneinfo` attach-then-convert pattern (verified); D-05 semantics; config `timezones` mapping (Pattern 8) |
| CLI-01 | 7 subcommands; flags > `SIFT_*` env > config.toml > defaults | Typer single-app multi-command structure (Code Example 1); layered-dict config resolution (Code Example 4) |
</phase_requirements>

## Summary

This phase is greenfield scaffolding plus one genuinely tricky component: a deterministic, byte-offset-tracking, encoding-aware, multi-line-grouping log parser. Everything else — Typer CLI, config precedence, SQLite events table — is boring, well-trodden ground with stdlib or one small dependency. The stack for this phase is only **three runtime packages** (typer, pydantic, zstandard) plus dev tooling; everything else is stdlib (`sqlite3`, `gzip`, `tomllib`, `zoneinfo`, `hashlib`, `datetime`, `re`, `io`, `fnmatch`).

The load-bearing insight from research: **every byte-offset decision must be made on the raw (decompressed) byte stream, never on decoded text**. `event_id` determinism, parse coverage, and idempotent re-ingest all hang off this. The recommended parse loop splits lines at the byte level using encoding-specific newline byte patterns (verified this session: UTF-8/cp1252 `b"\n"`, UTF-16-LE `b"\n\x00"`, UTF-16-BE `b"\x00\n"`), tracks a running offset, and decodes each record individually with `errors="replace"` only *after* offsets are fixed. `.tell()` on text wrappers is never used.

Two stdlib traps were verified live this session and must be encoded into the plan: (1) the `sqlite3` default datetime adapter raises `DeprecationWarning` on Python 3.12+ — store timestamps as explicit ISO 8601 UTC strings, never pass `datetime` objects to `execute()`; (2) `zstandard`'s `stream_reader` stops after the first frame by default — pass `read_across_frames=True`. Both would otherwise surface as confusing mid-implementation failures.

**Primary recommendation:** Build in this order: pyproject/skeleton → `models.py` (frozen Event, verbatim SPEC §5.1) → `config.py` → `store.py` (events+meta, `user_version=1`) → `adapters/base.py` (Protocol + registry + shared decompression helper) → `adapters/genericlog.py` → `cli.py` wiring → fixtures/tests throughout. The Event schema and Adapter protocol frozen here are permanent contracts — treat their reviews as the phase's highest-stakes checkpoint.

## Architectural Responsibility Map

Sift is a single-process local CLI; "tiers" here are module layers, not network tiers.

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Subcommand parsing, flag handling | `cli.py` (CLI layer) | — | Thin wiring only; no business logic (SPEC §7 boundary rule) |
| Config resolution (flags/env/toml/defaults) | `config.py` | `cli.py` passes flag overrides in | One resolved typed settings object exposed; testable without a TTY |
| Event/Adapter contracts | `models.py` + `adapters/base.py` | — | Contract layer imports nothing from other layers; everything imports it |
| File-format detection, decompression, parsing | `adapters/` | — | Only code that reads raw artefacts; zero knowledge of store or CLI |
| Persistence, idempotency, migrations, meta | `store.py` | — | Only code that writes SQL; `PRAGMA user_version` owned here |
| Ingest orchestration (walk dir → sniff → parse → insert → coverage report) | `cli.py` ingest command calling a small orchestrator | `adapters/`, `store.py` | Orchestration is procedural glue; keep in one function, not a framework |
| Case layout on disk (XDG) | `config.py` (paths) + `store.py` (db creation) | — | D-04: `$XDG_DATA_HOME/sift/cases/<name>/case.db` |

## Project Constraints (from CLAUDE.md)

The planner MUST honour these repo directives (same authority as locked decisions):

- **SPEC.md is authoritative** — read the relevant section before implementing any component.
- **Commands:** `uv sync`, `uv run pytest`, `uv run ruff check`, `uv run pyright`, `uv run sift <subcommand>`. "Done" = all three gates clean.
- **Milestone gate:** do not start M(n+1) while M(n) tests are red.
- **Boring technology only:** stdlib, httpx, Pydantic, sqlite-vec, scikit-learn/hdbscan, Typer, zstandard. Justify anything beyond these.
- **Zero network egress; never call the network in tests.**
- **Nothing disappears silently:** unparseable regions → `severity="unknown"` events; per-file parse-coverage metric; multi-line records are one event.
- **Determinism is load-bearing:** `event_id = sha256(source_file, byte_offset)[:16]`; idempotent re-ingest.
- **British English** in docs and user-facing strings (e.g. "normalise", "artefact", "licence").
- **Type hints everywhere;** ruff + pyright clean is part of "done".
- **Config precedence:** CLI flags > `SIFT_*` env > `~/.config/sift/config.toml` > defaults.
- **Record SPEC §10 open-question decisions in `docs/decisions/`** (D-02 covers this).
- **Licence: Apache-2.0** (pyproject `license` field; add `LICENSE` file if absent).

## Standard Stack

Phase 1 installs **only what Phase 1 uses**. httpx, sqlite-vec, scikit-learn etc. are validated in `.planning/research/STACK.md` but belong to Phases 2–3; adding them now just creates an unused-lockfile surface.

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | ≥ 3.12 (`requires-python = ">=3.12"`) | Language floor | SPEC constraint. Local interpreter is 3.14.6 — fine (floor, not pin) [VERIFIED: local `python3 --version`] |
| typer | 0.27.0 (released 2026-07-15) | CLI framework, 7 subcommands | D-01 locked; version current [VERIFIED: PyPI JSON API, fetched 2026-07-16] |
| pydantic | 2.13.4 (released 2026-05-06) | Config model validation (D-08) | Already a SPEC dependency for Phase 4; used here only for the settings model [VERIFIED: PyPI JSON API] |
| zstandard | 0.25.0 (released 2025-09-14) | zstd stream decompression (INGST-10) | Canonical binding; stdlib `compression.zstd` needs 3.14 floor, project floor is 3.12 [VERIFIED: PyPI JSON API; rationale CITED: .planning/research/STACK.md §4] |
| stdlib: `sqlite3`, `gzip`, `tomllib`, `zoneinfo`, `hashlib`, `datetime`, `re`, `io`, `fnmatch`, `json`, `os`, `pathlib` | 3.12+ | Store, gzip, config parse, tz, event_id, timestamp parse, glob match | Zero-dependency coverage of everything else this phase needs [VERIFIED: executed locally this session] |

### Supporting (dev-only)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | 9.1.1 (2026-06-19) | Test runner | All tests [VERIFIED: PyPI JSON API] |
| ruff | 0.15.22 (2026-07-16) | Lint + format | Quality gate [VERIFIED: PyPI JSON API] |
| pyright | 1.1.411 (2026-06-25) | Type checking (strict recommended from day one per STACK.md) | Quality gate [VERIFIED: PyPI JSON API] |

`respx` (0.23.1) is NOT needed in Phase 1 — there is no HTTP client yet. Add in Phase 3.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled timestamp regex ladder | `python-dateutil` / `dateparser` | Explicitly ruled out by phase hints ("without heavy dependencies") and boring-tech rule; `datetime.fromisoformat` on 3.11+ covers all ISO variants including `Z` [VERIFIED: executed on 3.14.6; behaviour added in 3.11 per CPython docs] |
| stdlib XDG env lookup (2 lines) | `platformdirs` | Target platform is Fedora (SPEC §3); `os.environ.get("XDG_DATA_HOME", "~/.local/share")` suffices — no new dependency |
| Plain Pydantic model + layered dicts (D-08) | `pydantic-settings` | Locked out by D-08 |

**Installation:**
```bash
uv init --package .            # if pyproject absent; src layout
uv add typer pydantic zstandard
uv add --dev pytest ruff pyright
```

**Version verification:** all versions above confirmed against the PyPI JSON API on 2026-07-16 (`curl https://pypi.org/pypi/<pkg>/json`), matching `.planning/research/STACK.md` where overlapping.

## Package Legitimacy Audit

Seam check run: `gsd-tools query package-legitimacy check --ecosystem pypi typer pydantic zstandard pytest ruff pyright respx httpx`.

The seam returned `SUS` for **all** packages with reason `unknown-downloads` — the seam has no PyPI download telemetry (its download signal is npm-only). All identity signals it *could* check are clean: every package exists, none deprecated, and each resolves to its known official source repo (fastapi/typer, pydantic/pydantic, indygreg/python-zstandard, pytest-dev/pytest). Typer additionally got `too-new` because its *latest release* (0.27.0) is one day old — the package itself dates to 2019.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| typer | PyPI | pkg since 2019; 0.27.0 released 2026-07-15 | seam: unknown (PyPI) | github.com/fastapi/typer | [SUS: too-new release, unknown-downloads] | Approved — identity confirmed via official repo URL + PyPI JSON + prior STACK.md verification; pin `typer==0.27.*` |
| pydantic | PyPI | ~9 yrs; 2.13.4 (2026-05-06) | seam: unknown | github.com/pydantic/pydantic | [SUS: unknown-downloads] | Approved — telemetry gap only |
| zstandard | PyPI | ~9 yrs; 0.25.0 (2025-09-14) | seam: unknown | github.com/indygreg/python-zstandard | [SUS: unknown-downloads] | Approved — telemetry gap only |
| pytest | PyPI | ~15 yrs; 9.1.1 (2026-06-19) | seam: unknown | github.com/pytest-dev/pytest | [SUS: unknown-downloads] | Approved — telemetry gap only |
| ruff | PyPI | 0.15.22 (2026-07-16) | seam: unknown | astral-sh/ruff | [SUS: unknown-downloads] | Approved — telemetry gap only |
| pyright | PyPI | 1.1.411 (2026-06-25) | seam: unknown | microsoft/pyright | [SUS: unknown-downloads] | Approved — telemetry gap only |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** all, formally — but every `SUS` traces to the seam's missing PyPI download data, not to genuine risk. All packages here are named explicitly in SPEC.md §9's boring-tech allowlist and were independently version-verified against the PyPI registry with matching official repos. Recommendation to planner: **no `checkpoint:human-verify` needed** for these installs; the SPEC allowlist + registry verification supersedes the telemetry-gap flags. Pin exact versions in `uv.lock` (uv does this automatically).

## Architecture Patterns

### System Architecture Diagram

```
 sift new <case> --input <dir>          sift ingest <case>                    sift show <case> events
        │                                      │                                      │
        ▼                                      ▼                                      ▼
 ┌─────────────┐                    ┌────────────────────┐                  ┌──────────────────┐
 │ config.py    │  resolved settings │ ingest orchestrator │                  │ store.query_events│
 │ flags>env>   │───────────────────▶│ walk input dir      │                  │ (--filter)        │
 │ toml>defaults│                    │ (sorted, recursive) │                  └────────┬─────────┘
 └─────────────┘                    └─────────┬──────────┘                            │
        │ SIFT_DATA_DIR / XDG                  │ per file                              ▼
        ▼                                      ▼                                 stdout table
 ┌──────────────────────┐          ┌───────────────────────┐
 │ case dir + case.db    │          │ open_bytes(path)       │  magic bytes: 1f 8b → gzip
 │ meta: input_dir, name │          │ (decompression seam)   │  28 b5 2f fd → zstd, else raw
 └──────────────────────┘          └─────────┬─────────────┘
                                              │ decompressed byte stream
                                              ▼
                                   ┌───────────────────────┐   --adapter glob=name override
                                   │ registry.detect()      │◀── (fnmatch on relative path)
                                   │ every adapter.sniff()  │
                                   │ on first 64 KB;        │
                                   │ max conf ≥ 0.5 wins;   │
                                   │ else genericlog        │
                                   └─────────┬─────────────┘
                                              ▼
                                   ┌───────────────────────┐
                                   │ adapter.parse()        │  byte-offset tracking on raw bytes
                                   │ → Iterator[Event]      │  ts → UTC via zoneinfo (D-05)
                                   │ (genericlog: ts-line   │  continuation grouping (D-06)
                                   │ starts event; caps)    │  unparsed → severity="unknown"
                                   └─────────┬─────────────┘
                                              ▼
                                   ┌───────────────────────┐
                                   │ store.insert_events()  │  INSERT OR IGNORE (event_id PK)
                                   │ one txn per ingest     │  → idempotent re-ingest
                                   └─────────┬─────────────┘
                                              ▼
                                   per-file parse-coverage report → stdout (first-class output)
                                   coverage stats + tz assumptions → meta table
```

### Recommended Project Structure (Phase 1 subset of SPEC §7)

```
sift/
├── pyproject.toml           # uv-managed; [project.scripts] sift = "sift.cli:app"; ruff+pyright+pytest config
├── LICENSE                  # Apache-2.0
├── docs/decisions/          # D-02: three ADRs seeded this phase
│   ├── 0001-typer-over-argparse.md
│   ├── 0002-weasyprint-pdf-extra.md
│   └── 0003-hand-rolled-masking-over-drain3.md
├── src/sift/
│   ├── __init__.py
│   ├── cli.py               # Typer app, 7 subcommands (analyze/report/eval/doctor stubbed → exit with "not implemented until Phase N")
│   ├── config.py            # SiftConfig (Pydantic), load_config(flag_overrides) → resolved object
│   ├── models.py            # Event frozen dataclass (SPEC §5.1 verbatim) + event_id() function
│   ├── store.py             # CaseStore: create/open case.db, migrations, insert_events, query_events, meta
│   └── adapters/
│       ├── __init__.py      # REGISTRY + detect(path, overrides) — registration point (SPEC §5.2 self-containment rule)
│       ├── base.py          # Adapter Protocol (verbatim), open_bytes() decompression helper, sniff_bytes() helper
│       └── genericlog.py    # the fallback adapter
└── tests/
    ├── conftest.py          # fixture builders (write fixture logs, gzip/zstd variants, tmp XDG dirs)
    ├── test_models.py       # event_id determinism
    ├── test_config.py       # precedence matrix
    ├── test_store.py        # idempotency, schema
    ├── test_adapters_detect.py
    ├── test_genericlog.py   # formats, continuation, caps, encodings, coverage
    └── test_cli.py          # CliRunner end-to-end: new → ingest → show events
```

Do **not** scaffold empty `pipeline/`, `llm/`, `render/` packages — later phases create them at SPEC §7's prescribed positions when they have content. Unimplemented subcommands (`analyze`, `report`, `eval`, `doctor`) exist in `cli.py` so CLI-01's "exposes 7 subcommands" is satisfied, each printing a clear "arrives in Phase N" message and exiting non-zero.

### Pattern 1: Single Typer app, one `@app.command()` per subcommand

**What:** One `typer.Typer()` instance; seven flat `@app.command()` functions. No `add_typer` nesting — the SPEC's CLI (§5.8) has no command groups.
**When to use:** Exactly this CLI shape. [CITED: typer.tiangolo.com via Context7]
**Example:** See Code Example 1.

### Pattern 2: Adapter registry as a module-level ordered mapping

**What:** `adapters/__init__.py` holds `REGISTRY: dict[str, Adapter]` (insertion-ordered) and a `detect(relpath, first_64kb, overrides) -> Adapter` function. Adding adapter #5 = new module + one registration line — nothing else changes (SPEC §5.2 hard rule, CONTEXT specifics).
**Detection algorithm (INGST-03):** (1) if any `--adapter glob=name` override's glob `fnmatch`es the file's relative path, that adapter wins unconditionally; (2) else run every registered adapter's `sniff()` on the first 64 KB of **decompressed** content; (3) highest confidence wins if ≥ 0.5; (4) ties or all-below-threshold → `genericlog`. genericlog's own `sniff` returns a low-but-nonzero score (e.g. 0.1 if it finds any parseable timestamp in the sample) so it never outcompetes a domain adapter but the fallback rule still applies.
**Boundary:** the Protocol in `base.py` is copied verbatim from SPEC §5.2 (`sniff(self, path: Path) -> float`, `parse(self, path: Path, case_id: str) -> Iterator[Event]`) — it is frozen after this phase to enable Phase 5 parallelism [CITED: .planning/research/ARCHITECTURE.md]. Since it takes `Path`, decompression lives in a shared helper (`base.open_bytes`) that every adapter calls — one decompression code path, adapters stay self-contained.

### Pattern 3: Canonical event_id serialisation — freeze it in writing

**What:** `event_id = sha256(source_file + "\x00" + str(byte_offset))[:16]`. The NUL separator prevents ambiguity (`("a1", 1)` vs `("a", 11)`). `source_file` is the case-relative path in **POSIX form** (`as_posix()`) so IDs are platform-stable; `byte_offset` is the 0-based offset of the event's first byte in the **decompressed** stream (D-07).
**Why it matters:** this exact serialisation is permanent — citations, idempotency, and every stored case depend on it (PITFALLS 10 recovery cost: HIGH). Document it in a `models.py` docstring and pin it with a golden-value test (`event_id("app.log", 12345) == "f7fdcb4b3de90265"` — value verified by execution this session) [VERIFIED: local hashlib run].

### Pattern 4: Streaming byte-offset parse loop (the heart of the phase)

**What:** All offset arithmetic happens on raw decompressed bytes; text decoding happens per-record, after offsets are fixed.

Algorithm (verified building blocks executed this session):
1. `open_bytes(path)` reads first 4 bytes: `1f 8b` → wrap `gzip.open(path, "rb")` (stdlib gzip reads multi-member/concatenated files transparently — [VERIFIED: executed]); `28 b5 2f fd` → `zstandard.ZstdDecompressor().stream_reader(fh, read_across_frames=True)` wrapped in `io.BufferedReader`; else the plain file. [CITED: python-zstandard autodocs via Context7]
2. BOM sniff on the first 4 decompressed bytes: `ef bb bf` → utf-8-sig, `ff fe` → utf-16-le, `fe ff` → utf-16-be; else default utf-8 with cp1252 as per-record decode fallback. The BOM bytes count towards offsets (they are part of the stream); the first event's offset is after the BOM.
3. Newline byte pattern per encoding [VERIFIED: executed]: utf-8/cp1252 `b"\n"`; utf-16-le `b"\n\x00"`; utf-16-be `b"\x00\n"`. Read chunks, split on the pattern, maintain `offset += len(line_bytes_including_newline)`. Handle `\r` (strip from decoded message; bytes still counted).
4. Decode each record with the detected encoding, `errors="replace"` — replacement can never corrupt offsets because offsets were fixed at byte level (PITFALLS 10).
5. Never call `.tell()` on any text wrapper; never slurp (memory bound is per-event: 64 KB cap from D-06).

**Anti-requirement:** `zstandard`'s `reader.tell()` does return the decompressed offset, but manual counting is used uniformly across all three stream types — one code path, no per-backend semantics to reason about.

### Pattern 5: Timestamp detection ladder (Claude's-discretion recommendation)

Format list for genericlog v1, tried in order against a candidate prefix extracted by regex from the line start (bounded scan — do not run `fromisoformat` on arbitrary substrings, since even `"20260716"` parses as a date [VERIFIED: executed]):

| # | Format | Detection | ts_confidence |
|---|--------|-----------|---------------|
| 1 | ISO 8601 (all variants: `T` or space separator, fractional seconds, `Z`, `±HH:MM`) | regex candidate `^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}...` → `datetime.fromisoformat` (3.11+ accepts `Z`) [VERIFIED: executed on 3.14.6; 3.11 change CITED: docs.python.org/3/library/datetime.html] | offset present → `"exact"`; naive → tz-override else UTC, `"inferred"` |
| 2 | syslog RFC3164 `Mon dd HH:MM:SS` | regex `^[A-Z][a-z]{2}\s+\d{1,2}\s\d{2}:\d{2}:\d{2}` → `strptime("%b %d %H:%M:%S")`; year from file mtime; if result > mtime + 1 day, subtract one year (December logs read in January) | `"inferred"` always |
| 3 | epoch seconds `^\d{10}(\.\d+)?\b` / millis `^\d{13}\b` at line start, plausibility window 2001–2100 (0.946e9–4.1e9) | int/float parse → `datetime.fromtimestamp(v, tz=timezone.utc)` | `"exact"` (epoch is UTC by definition) |
| 4 | Common app format `dd/Mon/yyyy:HH:MM:SS ±zzzz` (Apache CLF) — optional, one regex | `strptime("%d/%b/%Y:%H:%M:%S %z")` | `"exact"` (offset present) |

**Per-file format lock-in:** detect the format on the first matching line, then try the locked format first for the rest of the file (fast path), falling back to the full ladder on a miss. Deterministic and typically 1 regex/line instead of 4.

**Grouping (D-06, verbatim):** timestamped line starts an event; timestamp-less/indented line appends to the current event (`line_end` advances, bytes accrue to that event); caps 256 lines / 64 KB → overflow splits into a new `severity="unknown"` continuation event; leading unparseable region becomes its own `unknown` event with `ts=None, ts_confidence="missing"`.

**Severity extraction (recommendation, discretionary):** case-insensitive token scan after the timestamp: `FATAL|CRIT(ICAL)?`→fatal, `ERR(OR)?`→error, `WARN(ING)?`→warn, `INFO|NOTICE`→info, `DEBUG|TRACE|FINE`→debug. A timestamped line with no recognised token gets `severity="unknown"` — never fabricate a severity. Unparsed-region events are distinguishable from these by `ts_confidence="missing"`/`ts=None`. Flagged in Assumptions Log (A2) — planner may prefer `"info"` default; confirm at plan review.

### Pattern 6: Minimal SQLite schema, designed for Phase 2 extension

```sql
PRAGMA user_version = 1;   -- set by migration runner, not in DDL text
CREATE TABLE events (
    event_id      TEXT PRIMARY KEY,        -- 16 hex chars
    case_id       TEXT NOT NULL,
    ts            TEXT,                    -- ISO 8601 UTC ("...+00:00") or NULL
    ts_confidence TEXT NOT NULL CHECK (ts_confidence IN ('exact','inferred','missing')),
    source        TEXT NOT NULL,           -- adapter name
    source_file   TEXT NOT NULL,           -- case-relative POSIX path (compressed name for gz/zst)
    line_start    INTEGER NOT NULL,
    line_end      INTEGER NOT NULL,
    severity      TEXT NOT NULL CHECK (severity IN ('fatal','error','warn','info','debug','unknown')),
    component     TEXT,
    thread        TEXT,
    session       TEXT,
    message       TEXT NOT NULL,
    attrs         TEXT NOT NULL DEFAULT '{}',  -- JSON object, str→str
    raw           TEXT NOT NULL             -- Phase 2 migration adds zstd >4KB (STORE-02)
);
CREATE INDEX idx_events_ts ON events(ts);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- input_dir, created_at, coverage JSON, tz assumptions
```

- **Idempotency (INGST-02):** `INSERT OR IGNORE` via `executemany` in one explicit transaction per ingest; WAL mode + `synchronous=NORMAL` on open (PITFALLS perf table).
- **Timestamps as strings:** the `sqlite3` default datetime adapter is deprecated since 3.12 and warns [VERIFIED: DeprecationWarning reproduced this session]. Store `dt.isoformat()` explicitly; ISO strings sort correctly, so the ts index works for Phase 4's `--since/--until` later.
- **Migration runner:** ~20 lines — read `PRAGMA user_version`, apply numbered migration functions > current inside a transaction, set new version [CITED: .planning/research/ARCHITECTURE.md Pattern 3]. Phase 1 has exactly migration 1.
- **Phase-2 note:** SQLite type affinity permits BLOB values in a TEXT column, and zstd frames are self-identifying by magic bytes — so STORE-02's compression can land later without a table rebuild. Do not implement any of that now.

### Pattern 7: Parse-coverage metric that cannot trivially read 100%

Since *everything* becomes an event (unknown-fallback included), "bytes attributed to events / total bytes" would always be 100%. Define instead:

```
coverage(file) = 1 − (bytes attributed to unknown-fallback events / total decompressed bytes)
```

where **unknown-fallback events** = events created from unparseable regions (leading regions, cap-overflow spills — i.e. events with `ts=None`). Continuation lines inside a timestamped event count as covered. Every decompressed byte (including newlines and BOM) is attributed to exactly one event, so `sum(event byte spans) == file size` is a checkable invariant. Report per file on `sift ingest` stdout (first-class, per CONTEXT specifics) and persist the stats JSON into `meta`.

### Pattern 8: Config resolution (D-08)

Layered plain dicts merged in precedence order, validated once:

```
defaults dict → config.toml (tomllib, if exists) → SIFT_* env vars → CLI flag overrides
                                    ↓ merge (later wins, per-key)
                          SiftConfig.model_validate(merged)
```

Phase 1 config keys: `data_dir` (default `$XDG_DATA_HOME/sift` → `~/.local/share/sift`; env `SIFT_DATA_DIR`), `timezones` (mapping glob-pattern → IANA tz name, the D-05 override mechanism — consumed by genericlog for naive timestamps; env form can be deferred, TOML + flag suffice for the mechanism to "exist"), `adapters` (mapping glob → adapter name, same semantics as `--adapter`). Config file path: `$XDG_CONFIG_HOME/sift/config.toml` → `~/.config/sift/config.toml`. `zoneinfo.ZoneInfo` validates tz names for free at config-validation time [VERIFIED: executed].

### Anti-Patterns to Avoid

- **Offsets from decoded text or `.tell()` on text wrappers:** breaks event_id determinism — the phase's cardinal sin (Pitfall 1).
- **`errors="replace"` before offset fixing:** same corruption, subtler (PITFALLS 10).
- **Scaffolding Phases 2–6 module stubs now:** empty packages, unused deps, dead `raise NotImplementedError` files — the SPEC layout is a map, not a day-one checklist.
- **Passing `datetime` objects to sqlite3:** deprecated adapter path [VERIFIED]. ISO strings only.
- **Sniffing compressed bytes:** a gzipped syslog must sniff as genericlog; always sniff the decompressed head (Pitfall 4).
- **`pydantic-settings` / `platformdirs` / `python-dateutil`:** each locked out by D-08 / boring-tech / phase hints respectively.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CLI parsing, help, completion | argparse wrapper layers | Typer 0.27 (D-01) | Typed params pyright checks; repeated options free via `list[str]` |
| zstd decompression | frame parser | `zstandard.ZstdDecompressor.stream_reader` | Multi-frame, streaming, C-speed [CITED: Context7] |
| gzip (incl. concatenated members) | anything | stdlib `gzip` | Multi-member transparent [VERIFIED] |
| TOML parsing | regex config parser | stdlib `tomllib` | 3.11+ stdlib |
| Timezone database | offset tables | stdlib `zoneinfo` | IANA db, validates names [VERIFIED] |
| ISO 8601 parsing | strptime format zoo | `datetime.fromisoformat` (3.11+) | Handles Z, space sep, fractional, offsets [VERIFIED] |
| Glob matching for `--adapter`/`timezones` | custom pattern language | stdlib `fnmatch.fnmatch` | Exactly the `glob=name` semantics needed |
| SHA-256 | — | stdlib `hashlib` | — |
| Schema migrations | Alembic | ~20-line `PRAGMA user_version` runner | Embedded per-case DB; Alembic is overkill [CITED: ARCHITECTURE.md] |

**Key insight:** Phase 1's only genuinely custom code is the byte-offset parse loop and the timestamp ladder — both custom *because determinism over raw bytes is the product requirement*, not because libraries are missing. Everything around them is stdlib or one of three vetted packages.

## Common Pitfalls

### Pitfall 1: Byte offsets computed on decoded text
**What goes wrong:** `event_id` changes between runs/platforms; idempotency and citations silently break.
**Why it happens:** text-mode iteration is the natural way to read logs; `.tell()` on `TextIOWrapper` returns opaque cookies, and `errors="replace"` changes character counts.
**How to avoid:** Pattern 4 — split lines at byte level with encoding-specific newline patterns; decode per record afterwards.
**Warning signs:** idempotency test passes on ASCII fixtures but fails on the UTF-16/invalid-byte fixtures; offsets differ between gzip and plain variants of the same content.

### Pitfall 2: Naive/aware datetime mixing
**What goes wrong:** `TypeError` at comparison time, or worse, silent wrong ordering (PITFALLS 6 — causality inversion).
**How to avoid:** normalise at the adapter boundary: every `Event.ts` is aware UTC or `None`, no exceptions. Enforce with a test that parses mixed fixtures and asserts `all(e.ts.tzinfo is not None for e in events if e.ts)`.
**Warning signs:** pyright complaints around datetime arithmetic; any `datetime.now()` without `tz=` in the codebase (ruff rule DTZ — enable `flake8-datetimez` in ruff config).

### Pitfall 3: `zstandard.stream_reader` stops at the first frame
**What goes wrong:** multi-frame `.zst` files (produced by parallel compressors / appends) silently truncate — events vanish, violating "nothing dropped silently".
**How to avoid:** always `stream_reader(fh, read_across_frames=True)` [CITED: python-zstandard API docs via Context7]. Fixture: a two-frame zst file (two `compress()` outputs concatenated) must yield all events.
**Warning signs:** zst fixture coverage < plain-text fixture coverage for identical content.

### Pitfall 4: Sniffing the compressed bytes
**What goes wrong:** every `.gz`/`.zst` file sniffs as garbage → falls back to genericlog → genericlog also sees binary → whole file becomes one unknown blob; coverage craters.
**How to avoid:** detection order is decompress-then-sniff: `open_bytes()` first, `sniff` on the first 64 KB of decompressed content. Magic bytes: gzip `1f 8b` [VERIFIED], zstd `28 b5 2f fd` [VERIFIED via RFC 8878 value; magic constant is stable].
**Warning signs:** `--adapter '*.gz=genericlog'` needed to make compressed fixtures work.

### Pitfall 5: Epoch false positives and greedy ISO parsing
**What goes wrong:** any 10-digit number at line start (an ID, a size) becomes a timestamp; `fromisoformat` accepts bare `"20260716"` as a date [VERIFIED] — arbitrary tokens parse as timestamps and shred event grouping.
**How to avoid:** regex-anchor candidates to line start, require a following delimiter, and bound epoch values to 2001–2100. Never feed unanchored substrings to `fromisoformat`.
**Warning signs:** fixture with numeric-prefixed data lines produces absurd event counts or years like 1970/2609.

### Pitfall 6: Idempotency broken by nondeterministic iteration
**What goes wrong:** second ingest adds events because file walk order or dict ordering changed relative paths/offsets attribution (or because a `case_id`/uuid crept into the hash).
**How to avoid:** `sorted(input_dir.rglob("*"))` for the walk; event_id depends ONLY on `(source_file, byte_offset)` — resist adding case_id to the hash; the acceptance test is literally "second ingest adds zero events", run it as a test on every fixture.
**Warning signs:** flaky idempotency test.

### Pitfall 7: CRLF and BOM byte accounting
**What goes wrong:** `\r` stripped before counting, or BOM skipped without attributing its 2–3 bytes → all subsequent offsets shift by a constant; coverage sums ≠ file size.
**How to avoid:** count every byte (BOM attributed to first event's span or tracked as file preamble — pick one, test the invariant `sum(spans) == total_bytes`); strip `\r`/BOM only from decoded text.
**Warning signs:** the span-sum invariant test fails on the CRLF fixture.

### Pitfall 8: Typer option parsing for `--adapter glob=name`
**What goes wrong:** trying to make Typer parse the `glob=name` pair natively (dict options) — unsupported; or splitting on every `=` breaks globs containing `=`.
**How to avoid:** accept `Annotated[list[str], typer.Option("--adapter")]`, split each on the **first** `=` (`s.split("=", 1)`), validate the adapter name against the registry with a helpful error. [CITED: Typer multiple-options docs via Context7]

## Code Examples

### 1. Typer app skeleton with repeated `--adapter` option
```python
# Source: https://typer.tiangolo.com/ + /tutorial/options-autocompletion (via Context7)
from typing import Annotated
import typer

app = typer.Typer(no_args_is_help=True)

@app.command()
def new(
    case_name: str,
    input: Annotated[str, typer.Option("--input", help="Directory of artefacts")],
    adapter: Annotated[list[str], typer.Option("--adapter", help="glob=name override")] = [],
) -> None:
    ...

@app.command()
def ingest(case: str) -> None: ...

# show/analyze/report/eval/doctor likewise; unimplemented ones exit(1) with "arrives in Phase N"
```
Testing: `from typer.testing import CliRunner; CliRunner().invoke(app, ["new", "mycase", "--input", str(d)])` — assert `exit_code` and output. [CITED: typer.tiangolo.com/tutorial/testing via Context7]

### 2. event_id (canonical, frozen)
```python
# Verified this session: event_id("app.log", 12345) == "f7fdcb4b3de90265"
import hashlib

def event_id(source_file: str, byte_offset: int) -> str:
    """Canonical event identity. FROZEN — changing this invalidates every stored case.
    source_file: case-relative POSIX path (compressed file's own path for .gz/.zst).
    byte_offset: 0-based offset of the event's first byte in the DECOMPRESSED stream.
    """
    return hashlib.sha256(f"{source_file}\x00{byte_offset}".encode()).hexdigest()[:16]
```

### 3. Decompression seam with magic-byte detection
```python
# Source: python-zstandard autodocs via Context7; gzip multi-member verified locally
import gzip, io
from pathlib import Path
import zstandard

GZIP_MAGIC = b"\x1f\x8b"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

def open_bytes(path: Path) -> io.BufferedIOBase:
    head = path.open("rb").read(4)
    if head[:2] == GZIP_MAGIC:
        return gzip.open(path, "rb")          # handles concatenated members
    if head == ZSTD_MAGIC:
        fh = path.open("rb")
        dctx = zstandard.ZstdDecompressor()
        return io.BufferedReader(dctx.stream_reader(fh, read_across_frames=True))  # type: ignore[arg-type]
    return path.open("rb")
```

### 4. Config precedence (D-08)
```python
# stdlib tomllib + plain Pydantic; layered merge, later wins
import os, tomllib
from pathlib import Path
from pydantic import BaseModel

class SiftConfig(BaseModel):
    data_dir: Path
    timezones: dict[str, str] = {}   # glob -> IANA name (D-05 override mechanism)
    adapters: dict[str, str] = {}    # glob -> adapter name

def load_config(flag_overrides: dict[str, object]) -> SiftConfig:
    xdg_data = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser()
    layers: dict[str, object] = {"data_dir": xdg_data / "sift"}
    cfg_path = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / "sift" / "config.toml"
    if cfg_path.exists():
        layers |= tomllib.loads(cfg_path.read_text())
    if v := os.environ.get("SIFT_DATA_DIR"):
        layers["data_dir"] = v
    layers |= {k: v for k, v in flag_overrides.items() if v is not None}
    return SiftConfig.model_validate(layers)
```

### 5. UTC normalisation with confidence (D-05)
```python
# zoneinfo attach-then-convert verified this session
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def to_utc(dt: datetime, override_tz: str | None) -> tuple[datetime, str]:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc), "exact"
    tz = ZoneInfo(override_tz) if override_tz else timezone.utc
    return dt.replace(tzinfo=tz).astimezone(timezone.utc), "inferred"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `python-dateutil` for ISO parsing | `datetime.fromisoformat` full ISO 8601 (incl. `Z`) | Python 3.11 (2022) | Zero-dep timestamp ladder viable [VERIFIED on 3.14.6] |
| sqlite3 implicit datetime adapters | Explicit ISO string storage | Deprecated Python 3.12 | Must store strings; adapters warn now, removed later [VERIFIED] |
| `pytz` | stdlib `zoneinfo` | Python 3.9 | No tz dependency |
| setup.py/pip workflows | uv (`uv init --package`, `uv add`, `[project.scripts]`) | 2024+ | `uv run sift` works immediately; `uv tool install` is the M8 target |
| Typer `x: str = typer.Option(...)` style | `Annotated[str, typer.Option(...)]` style | Typer 0.9+ (both supported) | Annotated form is docs-preferred and plays better with pyright strict [CITED: Context7] |

**Deprecated/outdated:**
- `drain3` for template mining: dormant since 2022, Python ≤ 3.11 — already ruled out (D-02 ADR #3) [CITED: STACK.md].
- sqlite3 default adapters/converters: deprecated 3.12 [VERIFIED].

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Apache CLF (`%d/%b/%Y:%H:%M:%S %z`) is worth including in the v1 ladder | Pattern 5 | Low — one regex; omitting only lowers coverage on web-server logs (Claude's-discretion area anyway) |
| A2 | Timestamped lines with no recognised severity token should get `severity="unknown"` rather than `"info"` | Pattern 5 | Low-medium — affects Phase 4 salience weighting later; flag at plan review, trivially changeable now, breaking later |
| A3 | Syslog year inference: file-mtime year, minus 1 if the resulting ts is > mtime + 1 day | Pattern 5 | Low — D-05 already mandates mtime inference; the minus-1 rule is the year-boundary refinement |
| A4 | Context7's Typer docs (unversioned docs site) match Typer 0.27.0 behaviour | Patterns 1, 8 | Low — `@app.command()`/`Annotated`/`CliRunner` are years-stable core API |
| A5 | Epoch plausibility window 2001–2100 is acceptable | Pattern 5 | Low — configurable constant; false negatives only outside the window |
| A6 | zstd magic bytes `28 b5 2f fd` (RFC 8878) — not executed against a real zst file this session (zstandard not yet installed) | Pitfall 4, Code Example 3 | Very low — standardised constant; the gzip/zstd fixture tests verify it mechanically in Wave 0 |

## Open Questions (RESOLVED)

1. **RESOLVED — `raw` column: compress-in-Phase-2 strategy** → implemented as `raw TEXT` + STORE-02 pointer comment in `store.py` (plan 01-02 T2)
   - What we know: STORE-02 (Phase 2) zstd-compresses `raw` > 4 KB; SQLite type affinity accepts BLOBs in TEXT columns; zstd frames are magic-byte self-identifying.
   - What's unclear: whether Phase 2 will prefer a clean `raw BLOB` + flag column via migration 2.
   - Recommendation: ship `raw TEXT` now; leave a one-line comment in `store.py` pointing at STORE-02. No Phase 1 action.
2. **RESOLVED — Re-ingest semantics when the input dir has changed** (rotated/re-collected files) → snapshot semantics documented in `sift ingest` help + README (plan 01-05 T1)
   - What we know: PITFALLS 10 — idempotency is defined for the *same snapshot*; cross-collection identity is v2 territory.
   - Recommendation: document in `sift ingest` help + README: "a case is one snapshot of artefacts; re-collect into a new case". New files in the dir simply add events (fine); renamed files add duplicates (documented limitation).
3. **RESOLVED — Should `sift new` fail or warn when the input dir is empty?** → warn and create the case anyway; `sift ingest` on an empty dir reports 0 files, exit 0 (plan 01-04 T3)

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python ≥ 3.12 | everything | ✓ | 3.14.6 (system) | — |
| uv | project management, `uv run` gates | ✓ | 0.11.25 | — |
| git | phase workflow, commits | ✓ | 2.55.0 | — |
| PyPI reachability | `uv add` installs | ✓ (verified via PyPI JSON fetches this session) | — | — |
| zstd CLI | ✗ not needed | n/a | — | Fixtures generated with the `zstandard` package itself in `conftest.py` — no system tool required |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none — this phase needs no external services (no inference server until Phase 3).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 |
| Config file | none yet — `[tool.pytest.ini_options]` in pyproject.toml, created in Wave 0 |
| Quick run command | `uv run pytest -x -q` |
| Full suite command | `uv run pytest && uv run ruff check && uv run pyright` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INGST-01 | new+ingest fixture → events with expected deterministic IDs | integration (CliRunner) | `uv run pytest tests/test_cli.py -x -q` | ❌ Wave 0 |
| INGST-02 | second ingest adds zero events | integration | `uv run pytest tests/test_store.py::test_reingest_idempotent -x` | ❌ Wave 0 |
| INGST-03 | sniff auto-detect, ≥0.5 threshold, fallback, `--adapter` override | unit | `uv run pytest tests/test_adapters_detect.py -x` | ❌ Wave 0 |
| INGST-04 | ISO/syslog/epoch parsing + continuation grouping | unit | `uv run pytest tests/test_genericlog.py -x` | ❌ Wave 0 |
| INGST-05 | unknown events for unparseable regions; coverage formula; ≥99% on fixture | unit | `uv run pytest tests/test_genericlog.py -k coverage -x` | ❌ Wave 0 |
| INGST-06 | stack-trace fixture → one event; 256-line/64 KB caps | unit | `uv run pytest tests/test_genericlog.py -k multiline -x` | ❌ Wave 0 |
| INGST-10 | gzip/zstd fixtures (incl. multi-member gz, multi-frame zst) yield identical events & offsets to plain variant | unit | `uv run pytest tests/test_genericlog.py -k compressed -x` | ❌ Wave 0 |
| INGST-11 | naive→UTC inferred, offset→exact, glob tz override applied | unit | `uv run pytest tests/test_genericlog.py -k timezone -x` | ❌ Wave 0 |
| CLI-01 | 7 subcommands exist; precedence matrix flags>env>toml>defaults | unit | `uv run pytest tests/test_config.py tests/test_cli.py -x` | ❌ Wave 0 |

Encoding edge cases (PITFALLS "Looks Done" checklist): the coverage fixtures MUST include UTF-16LE-with-BOM, cp1252, an invalid-byte file, and a CRLF file — not just UTF-8.

### Sampling Rate
- **Per task commit:** `uv run pytest -x -q`
- **Per wave merge:** `uv run pytest && uv run ruff check && uv run pyright`
- **Phase gate:** full suite green (this is also the SPEC §8 M1 gate) before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `pyproject.toml` — uv project, `[project.scripts]`, ruff/pyright/pytest config; `uv add` of the three runtime + three dev packages
- [ ] `tests/conftest.py` — fixture builders: write fixture logs (parametrised encodings), gzip/zstd compressors (using stdlib gzip + zstandard), tmp `XDG_DATA_HOME`/`XDG_CONFIG_HOME` monkeypatch fixture so tests never touch the real home dir
- [ ] All test files listed in the map (greenfield — everything is Wave 0)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Local single-user CLI, no auth surface |
| V3 Session Management | no | — |
| V4 Access Control | no | Filesystem permissions are the boundary |
| V5 Input Validation | yes | Pydantic for config; case-name validation; log bytes treated strictly as data |
| V6 Cryptography | yes (non-secret) | `hashlib.sha256` for identity only — no security claim, no hand-rolling |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via case name (`sift new ../../evil`) | Tampering | Validate case name: `^[A-Za-z-0-9_.-]+$`, reject `.`/`..`; resolve final path and assert it is inside `data_dir/cases` |
| SQL injection via filenames/log content in queries | Tampering | Parameterised queries only (`?` placeholders); no f-string SQL — `store.py` is the single SQL owner, easy to review |
| Decompression bomb (tiny .zst → huge stream) | DoS | Streaming parse + 64 KB/event cap bounds memory (D-06); nothing is written decompressed to disk; optionally cap total decompressed bytes per file with a loud error |
| Terminal escape injection: log lines containing ANSI/control sequences echoed by `sift show events` | Tampering/Spoofing | Sanitise control characters (except `\n`/`\t`) when rendering raw/message to the terminal |
| Network egress | Info disclosure | This phase adds zero network code; keep it that way — no HTTP dependency installed until Phase 3. The PITFALLS-recommended socket-guard pytest fixture ("from M1") is cheap: an autouse fixture that patches `socket.socket.connect` to raise for non-loopback — recommend adding it in Wave 0 so the zero-network-in-tests rule is mechanical from day one |

## Sources

### Primary (verified by execution this session)
- Local Python 3.14.6 run: `fromisoformat` variants, encoding newline byte patterns, BOM constants, gzip magic + multi-member read, `zoneinfo` conversion, event_id golden value, sqlite3 datetime-adapter DeprecationWarning
- PyPI JSON API (fetched 2026-07-16): typer 0.27.0, pydantic 2.13.4, zstandard 0.25.0, pytest 9.1.1, ruff 0.15.22, pyright 1.1.411, respx 0.23.1
- `gsd-tools query package-legitimacy check` (pypi): existence + repo URLs for all phase packages

### Secondary (official docs via Context7 — seam-classified MEDIUM)
- `/websites/typer_tiangolo` — multi-command apps, `list[str]` repeated options, `CliRunner` testing
- `/indygreg/python-zstandard` — `stream_reader`, `read_across_frames`, `ZstdDecompressionReader` API

### Project ground truth
- `SPEC.md` §5.1/§5.2/§5.8/§7/§8-M1/§9/§10 — verbatim contracts and gates
- `.planning/research/STACK.md`, `PITFALLS.md` (esp. Pitfalls 6, 10), `ARCHITECTURE.md` (build order, migration pattern) — all dated 2026-07-16
- `01-CONTEXT.md` D-01…D-08

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every version verified against PyPI this session; three-package surface
- Architecture: HIGH — SPEC-prescribed layout + patterns cross-validated by prior ARCHITECTURE.md research; byte-level parse building blocks executed
- Pitfalls: HIGH for the verified ones (sqlite3 adapters, zstd frames, fromisoformat greediness); MEDIUM for parse-loop edge-case coverage (fixtures will prove it)

**Research date:** 2026-07-16
**Valid until:** ~2026-08-15 (stable domain; stdlib facts durable; re-check Typer minor version at execution)
