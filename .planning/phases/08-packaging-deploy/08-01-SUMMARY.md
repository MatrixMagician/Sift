---
phase: 08-packaging-deploy
plan: 01
subsystem: packaging
tags: [packaging, cli, testing, uv, offline]
requires: []
provides:
  - packaging-pytest-marker
  - offline-install-smoke-test
  - sift-version-affordance
affects:
  - pyproject.toml
  - src/sift/cli.py
  - tests/test_packaging.py
tech-stack:
  added: []
  patterns:
    - "Opt-in slow integration tests gated behind a pytest marker excluded from addopts"
    - "Offline uv subprocess via --offline + UV_OFFLINE=1 (cache-backed), never --no-index"
    - "Eager Typer Option callback for --version, robust off-tree via importlib.metadata fallback"
key-files:
  created:
    - tests/test_packaging.py
  modified:
    - pyproject.toml
    - src/sift/cli.py
decisions:
  - "Dropped the plan's --no-index from uv tool install: it excludes uv's cache index and demands a full offline wheelhouse that cannot be built here (no `uv pip download`; cache holds unpacked archives, not .whl). --offline / UV_OFFLINE=1 is the actual zero-network guarantee."
  - "The uv subprocesses drop the _isolate_dirs fixture's redirected XDG_DATA_HOME/XDG_CONFIG_HOME so uv resolves deps from its warm cache offline; isolation is preserved by UV_TOOL_DIR/UV_TOOL_BIN_DIR and --data-dir on `sift new`."
  - "sift --version implemented as an eager @app.callback Option callback (fires before subcommand dispatch under no_args_is_help=True)."
metrics:
  duration: ~13m
  completed: 2026-07-19
status: complete
---

# Phase 8 Plan 01: Prove PKG-01 (offline install) Summary

Automated, fully-offline proof that PKG-01 holds: `uv build` + `uv tool install --offline` yields a runnable `sift` console script (`--help`/`--version`/`new`), gated behind an opt-in `packaging` marker so the default fast suite is untouched. Version stays 0.1.0 (D-03).

## What was built

- **`packaging` pytest marker + addopts exclusion** (`pyproject.toml`): `addopts` now reads `-m 'not perf and not live and not packaging'`; the new marker is registered alongside `perf`/`live`. No version bump, no dependency changes (D-02/D-03 carried forward).
- **`sift --version` affordance** (`src/sift/cli.py`): an eager Typer `@app.callback` Option that prints `importlib.metadata.version("sift")`, falling back to `0.1.0` (via `PackageNotFoundError`) when run from an uninstalled checkout. This is the only production-code change (D-04: PKG-01 is proven, not built).
- **Offline install smoke test** (`tests/test_packaging.py`): a single `@pytest.mark.packaging` test that builds a wheel offline, installs it via `uv tool install --offline` into a hermetic `UV_TOOL_DIR`/`UV_TOOL_BIN_DIR` under `tmp_path`, asserts the injected `bin/sift` entry point exists, then runs `--help` (asserts `ingest`), `--version` (asserts `0.1.0`), and a trivial `sift new` with an explicit `--data-dir`.

## Verification

- `uv run pytest -m packaging tests/test_packaging.py -q` → 1 passed (3.21 s).
- `uv run pytest -q` (default suite) → 466 passed, 6 deselected; packaging test NOT collected (`--collect-only` count 0).
- `uv run sift --version` → `0.1.0`.
- `uv run ruff check` clean; `uv run pyright` → 0 errors.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Removed `--no-index` from `uv tool install`**
- **Found during:** Task 2
- **Issue:** The plan's acceptance criteria required `uv tool install --offline --no-index --find-links <dist>`. `--no-index` excludes uv's own cache registry index, so it only resolves packages physically present under `--find-links`. Building a full local wheelhouse offline is impossible in this environment: uv exposes no `pip download`, and the cache stores unpacked archives, not `.whl` files (all 96 cached `.whl` are editable-install artefacts). With `--no-index` the install fails to resolve `httpx`/`scikit-learn`.
- **Fix:** Dropped `--no-index`; kept `--offline` + `UV_OFFLINE=1` (the real zero-network guarantee — uv may only read from its cache) plus `--find-links <dist>` for the freshly-built sift wheel. Runtime deps resolve from the warm cache (RESEARCH A1). RESEARCH Pattern 1's own `uv tool install` example did not use `--no-index`.
- **Files modified:** tests/test_packaging.py
- **Commit:** 98208c3

**2. [Rule 3 - Blocking] Drop redirected `XDG_DATA_HOME`/`XDG_CONFIG_HOME` from the uv subprocess env**
- **Found during:** Task 2
- **Issue:** The autouse `_isolate_dirs` conftest fixture redirects `XDG_DATA_HOME`/`XDG_CONFIG_HOME` to an empty tmp dir. Inherited into the uv subprocess, this starves uv's config/cache resolution and makes offline resolution of binary wheels (scikit-learn) fail with "needs to be downloaded from a registry" — even though the identical command succeeds outside pytest.
- **Fix:** `env.pop("XDG_DATA_HOME")` / `env.pop("XDG_CONFIG_HOME")` for the uv/sift subprocesses. Isolation is still guaranteed by `UV_TOOL_DIR`/`UV_TOOL_BIN_DIR` (tool location) and the explicit `--data-dir` on `sift new`.
- **Files modified:** tests/test_packaging.py
- **Commit:** 98208c3

**3. [Rule 3 - Blocking] `# pyright: ignore[reportUnusedFunction]` on the callback**
- **Found during:** Task 1
- **Issue:** Under strict pyright the decorator-registered `@app.callback` `_main` (leading underscore → treated as private) is flagged `reportUnusedFunction`.
- **Fix:** Scoped `# pyright: ignore[reportUnusedFunction]` — the same pattern conftest uses for autouse fixtures.
- **Files modified:** src/sift/cli.py
- **Commit:** a305520

## Threat surface

No new security-relevant surface. Threat register dispositions honoured: T-08-02 (info disclosure via uv subprocess) is mitigated by `--offline` + `UV_OFFLINE=1` on every subprocess; T-08-03 (wheel/dep tampering) holds — no new deps, wheel built only from checked-out source via the native `uv_build` backend; T-08-SC (package installs) — zero new packages installed.

## Known Stubs

None.

## Self-Check: PASSED
- tests/test_packaging.py — FOUND
- src/sift/cli.py, pyproject.toml — modified, FOUND
- Commit a305520 (feat) — FOUND
- Commit 98208c3 (test) — FOUND
