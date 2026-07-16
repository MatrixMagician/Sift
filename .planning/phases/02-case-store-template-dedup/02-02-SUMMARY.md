---
phase: 02-case-store-template-dedup
plan: 02
subsystem: cli-ingest-scale
tags: [perf, progress, streaming, portability, rich]

requires:
  - 02-01 store v2 (template_groups, zstd raw, rebuild_template_groups)
  - Phase 1 genericlog byte_offset/byte_len attrs contract
provides:
  - "M2 scale gate: seeded 100 MB generator + @pytest.mark.perf < 60 s test (measured 19.3 s)"
  - "Batched streaming ingest: itertools.batched(parse, 5000) inside the ONE ingest transaction"
  - "rich Progress on Console(stderr=True), disabled off-terminal; stdout contract unchanged"
  - "STORE-01 portability: explicit store.close() on all ingest paths; case dir == [case.db]"
  - "pytest perf marker + addopts exclusion; pyright executionEnvironment for tests/perf"
affects: [02-03, phase-03-embedding, phase-04-hypotheses]

tech-stack:
  added: ["rich>=15.0.0 (promoted transitive -> explicit; no new package in the environment)"]
  patterns:
    - "Perf gates behind @pytest.mark.perf, excluded via addopts; run explicitly with -m perf"
    - "Progress rendering: stderr-only Console, disable=not console.is_terminal, STATIC description (T-02-06)"
    - "Within-file progress from last batch event's byte_offset+byte_len (uncompressed genericlog); whole-file advance for .gz/.zst"
    - "CLI command bodies that must close resources: thin command wrapper + try/finally store.close() around a _helper"

key-files:
  created:
    - tests/perf/generate_synthetic.py
    - tests/perf/test_perf_ingest.py
  modified:
    - src/sift/cli.py
    - pyproject.toml
    - uv.lock
    - tests/test_cli.py

key-decisions:
  - "Batch size 5000 events per insert_events call, all inside the single BEGIN IMMEDIATE transaction (all-or-nothing preserved)"
  - "Generator writes ASCII-only lines so char count == byte count; volatile tokens whitespace-delimited so <NUM> word-boundary masking fires"
  - "tests/perf has no __init__.py; pytest prepend mode + pyright executionEnvironments (extraPaths=[tests/perf, src]) resolve imports"
  - "Perf test prints the measured seconds (visible via -s) so the M2 evidence is reproducible, not just asserted"
  - "CLI-03 ticked ingest-leg only: embedding/generation progress arrive in Phases 3-4 (RESEARCH open question 1 convention)"

requirements-completed: [STORE-01, CLI-03]

metrics:
  duration: ~9min
  completed: 2026-07-16
  tasks: 2
  tests-before: 132
  tests-after: 137

status: complete
---

# Phase 2 Plan 02: Streaming Ingest at Scale & M2 Perf Gate Summary

100 MB seeded synthetic log ingests end-to-end in a measured **19.3 s** (< 60 s M2 budget, 3× headroom — RESEARCH assumption A4 retired); ingest now streams in 5000-event batches inside one transaction with a rich progress bar on stderr, and a clean close leaves the case directory as exactly `[case.db]` (STORE-01).

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Generator + perf/portability/progress tests + marker config | 62d027e | tests/perf/generate_synthetic.py (new), tests/perf/test_perf_ingest.py (new), tests/test_cli.py, pyproject.toml |
| 2 | Batched streaming ingest + rich progress on stderr | 3c8394b | src/sift/cli.py, pyproject.toml, uv.lock, tests/test_cli.py, tests/perf/test_perf_ingest.py |

## M2 Gate Evidence (A4 retirement)

- `uv run pytest -m perf`: **100 MB ingest took 19.3 s (budget 60 s)** — parse + store + template rebuild, CPU only, this machine. Generation time excluded (the budget is the ingest contract).
- Batch size: 5000 events per `insert_events` call, all batches of all files inside the ONE existing `BEGIN IMMEDIATE` transaction — interrupted ingest leaves the store fully updated or unchanged.
- Default suite runtime unchanged (~0.5 s, 136 tests + 1 deselected perf test); the generator determinism test (1 MB, byte-identical for same seed) runs in the default suite.
- Portability asserted at scale: after the perf ingest returns, the case directory listing is exactly `["case.db"]` — no `-wal`/`-shm` siblings.

## CLI-03 Scope Note (flagged for verifier)

CLI-03's text covers ingest, embedding AND generation progress. This plan delivers the **ingest leg only** — embedding/generation progress arrive in Phases 3–4. REQUIREMENTS.md CLI-03 is ticked with this partial-scope note per the RESEARCH open-question-1 resolution.

## What Changed

**`src/sift/cli.py` ingest** (contracts for later plans):
- `events = list(parse(...))` is gone; `for batch in batched(file_adapter.parse(path, case), 5000)` accumulates `new_count`/`parsed_count` (T-02-05 memory bound).
- `Console(stderr=True)` + `Progress(..., transient=True, disable=not err_console.is_terminal)` — non-TTY runs (CliRunner, CI, pipes) render nothing deterministically; stdout is byte-identical to Phase 1 (per-file coverage lines, ERROR/SKIP lines, `Total:` and `Template groups:` unchanged).
- Progress description is the STATIC string `"Ingesting"` — untrusted filenames never enter rich renderables (T-02-06); names still flow through `_sanitise`'d stdout prints only.
- Within-file advance uses the last batch event's `attrs["byte_offset"] + attrs["byte_len"]` clamped to file size, for uncompressed `GenericLogAdapter` files; `.gz`/`.zst` and non-genericlog files advance whole-file on completion (decompressed offsets do not map to on-disk bytes).
- The `ingest` command is now a thin wrapper around `_ingest(case, config, store)` with `try/finally: store.close()` — the clean close checkpoints WAL on every exit path (success, per-file failure exit 1, adapter-error exit 2), fixing the STORE-01 sidecar gap (Pitfall 4).

**`tests/perf/`** (no `__init__.py` — pytest prepend mode):
- `generate_synthetic.py`: `TEMPLATES` (20 shapes), `generate(path, target_mb=1, seed=42)`, `__main__` via `sys.argv` (`python tests/perf/generate_synthetic.py OUT MB [SEED]`). Deterministic per seed; ASCII-only.
- `test_perf_ingest.py`: `@pytest.mark.perf` timed gate + unmarked determinism test.

**`pyproject.toml`**: perf `markers` + `addopts = "-m 'not perf'"` (explicit CLI `-m perf` overrides it); `rich>=15.0.0` explicit in `[project]` dependencies; `[[tool.pyright.executionEnvironments]]` for `tests/perf`.

**`tests/test_cli.py`**: portability pair (case dir == `[case.db]`; rmtree ⇒ show exits 1 "does not exist"), non-TTY stdout regression guard, name-collision pin (docstring note on the existing WR-03 test — behaviour already covered, no duplicate test).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] pyright could not resolve imports in tests/perf**
- **Found during:** Task 1 verify
- **Issue:** strict pyright reported missing stubs for `sift.cli`/`sift.config` and could not resolve `import generate_synthetic` in the non-package `tests/perf` directory
- **Fix:** `[[tool.pyright.executionEnvironments]]` with `root = "tests/perf"`, `extraPaths = ["tests/perf", "src"]` — mirrors pytest's prepend-mode sys.path at type-check time
- **Files modified:** pyproject.toml
- **Commit:** 62d027e

**2. [Planned mechanism] portability test strict-xfailed during task 1**
- The case-dir-contains-only-case.db assertion failed against pre-task-2 code (ingest never closed the store, `-wal`/`-shm` survived). Marked `xfail(strict=True)` in task 1 exactly as the plan's behavior block prescribes; the marker was removed in task 2 when the explicit close landed. RED→GREEN proven across commits 62d027e → 3c8394b.

**3. [Minor] perf test prints the measured seconds; one repeat run to capture them**
- The plan requires recording the measured seconds in this SUMMARY, but the timed assertion alone doesn't surface them on pass. Added a `print(f"100 MB ingest took {elapsed:.1f} s ...")` to the perf test and ran `-m perf` once more with `-s` to capture **19.3 s** (both runs green: 23.64 s and 23.25 s total wall including generation). The print is permanent evidence tooling, not test logic.

**4. [Reuse over duplication] name-collision pin**
- The plan asked to add a name-collision test; `test_new_refuses_to_overwrite_existing_case` already asserts exit 1 + "already exists" verbatim. Annotated it as the plan 02-02 acceptance pin instead of duplicating it.

## Prohibition Status (flagged items)

- **No network egress:** the autouse socket guard ran green across the whole suite including the perf run; rich renders locally, the generator is pure file I/O. No new imports touch sockets.
- **Progress must not obscure per-file errors:** ERROR/SKIP lines remain plain `print()` on stdout, unchanged and asserted by the existing corrupt-archive and symlink tests (both still green); the progress bar is transient, stderr-only, and disabled off-terminal.

## Human Verification Outstanding (end-of-phase UAT)

Run `uv run sift ingest <case>` on the 100 MB file in a real terminal and observe a live progress bar on stderr — rich TTY rendering cannot be exercised via CliRunner (02-VALIDATION.md manual-only item). Reproduce the input with:
`uv run python tests/perf/generate_synthetic.py /tmp/big.log 100`

## Known Stubs

None introduced. `analyze`, `report`, `eval`, `doctor`, `show hypotheses` remain Phase 1 arrival stubs by design.

## Threat Flags

None — all new surface was in the plan's threat model (T-02-05 batched streaming, T-02-06 static progress description, T-02-07 WAL checkpoint on close, T-02-SC rich promotion with no new package).

## Verification

- `uv run pytest -x -q`: 136 passed, 1 deselected — all Phase 1/02-01 stdout assertions intact
- `uv run pytest -m perf -x -q`: 1 passed, ingest measured 19.3 s < 60 s
- `uv run ruff check` and `uv run pyright` (strict): clean
- Acceptance greps: `batched(` and `Console(stderr=True)` present in cli.py; no `list(file_adapter.parse` on the ingest path; `disable=not err_console.is_terminal` on Progress; `rich` in `[project]` dependencies

## Self-Check: PASSED

Created files (tests/perf/generate_synthetic.py, tests/perf/test_perf_ingest.py) exist on disk; commits 62d027e and 3c8394b present in git log; full gate re-verified green (136 passed + perf gate, ruff, pyright).
