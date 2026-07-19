# Phase 8: Packaging & Deploy - Pattern Map

**Mapped:** 2026-07-19
**Files analyzed:** 6 (4 new, 2 modified)
**Analogs found:** 5 / 6 (one file — the Quadlet units — has no in-repo analog; ground it in RESEARCH skeletons)

This is a docs + config + one test phase, not a runtime-code phase. Only `tests/test_packaging.py` is real Python, and it copies its opt-in-marker mechanics wholesale from the existing `perf`/`live` pattern. The two Quadlet `.container` files have no analog in the tree (first `deploy/` files) — use the RESEARCH skeletons verbatim.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `tests/test_packaging.py` | test | batch (subprocess integration) | `tests/perf/test_perf_ingest.py` | exact (marker-gated slow integration test) |
| `pyproject.toml` (MODIFY) | config | — | itself — `[tool.pytest.ini_options]` block (lines 44-53) | exact (in-place extension) |
| `docs/decisions/0011-quadlet-loopback-guard.md` | config (ADR) | — | `docs/decisions/0010-eval-exit-codes.md` | exact (numbered-ADR template) |
| `README.md` (REWRITE) | config (docs) | — | RESEARCH D-09 outline (no prose analog in tree) | role-match |
| `deploy/sift.container` | config (Quadlet unit) | request-response (env→base_url) | RESEARCH skeleton (§Code Examples) | no analog |
| `deploy/llama-server.container.example` | config (Quadlet example) | request-response | RESEARCH skeleton (§Code Examples) | no analog |

## Pattern Assignments

### `tests/test_packaging.py` (test, marker-gated subprocess integration)

**Analog:** `tests/perf/test_perf_ingest.py`

This is the load-bearing analog. The new module needs THREE things and the perf test + conftest supply all three patterns:

**1. Opt-in marker + module docstring convention** (`tests/perf/test_perf_ingest.py:1-6`, `:31`):
```python
"""M2 scale gate: 100 MB synthetic ingest < 60 s + STORE-01 portability.

The perf-marked test runs explicitly via ``uv run pytest -m perf`` — the
default suite excludes it (addopts, Pitfall 5). ...
"""

@pytest.mark.perf
def test_100mb_ingest_under_60s(tmp_path: Path) -> None:
```
New module mirrors this: module docstring stating "runs explicitly via `uv run pytest -m packaging`", and `@pytest.mark.packaging` on each slow test. `tmp_path` gives the throwaway env/scratch dir (fixture is auto-isolated via conftest `_isolate_dirs`).

**2. The subprocess-offline carve-out — critical.** The autouse `_no_network` guard patches `socket.socket.connect` **in the pytest process only**; it does NOT reach `uv`/`sift` subprocesses (`tests/conftest.py:34-60`, RESEARCH Pitfall 1). So the smoke test's `subprocess.run([...uv build/install...])` runs OUTSIDE the guard — offline-ness must be forced with uv's own flags (`--offline` / `--no-index --find-links dist/`), NOT relied upon from the socket patch. Unlike the `live` marker, `packaging` does NOT need a conftest exemption: the guard never touches subprocesses, and no in-process socket is opened. Do NOT add a `packaging` branch to `_no_network`.

The `live`-marker exemption in `tests/conftest.py:44-52` is the *pattern the marker mirrors* for pyproject wiring, but the mechanism differs — spell this out in the module docstring so no future agent adds a needless conftest branch:
```python
if node.get_closest_marker("live") is not None:
    return
```

**3. Core smoke-test shape** (RESEARCH §Pattern 1 / Code Examples, lines 149-164):
```python
import subprocess, tempfile
from pathlib import Path

subprocess.run(["uv", "build", "--offline", "--wheel", "-o", dist], check=True)
wheel = next(Path(dist).glob("sift-*.whl"))
subprocess.run(["uv", "venv", venv], check=True)
subprocess.run(["uv", "pip", "install", "--offline", "--no-index",
                "--find-links", dist, str(wheel), "--python", f"{venv}/bin/python"], check=True)
out = subprocess.run([f"{venv}/bin/sift", "--help"], capture_output=True, text=True, check=True)
assert "ingest" in out.stdout
```
Set `env={"UV_OFFLINE": "1", **os.environ}` on each subprocess as belt-and-braces (RESEARCH Pitfall 1).

**4. Guard-acceptability assertion (PKG-02, always runs, no podman).** Parse `deploy/sift.container`, extract the `SIFT_*_BASE_URL` env values, feed each to `_assert_local` and assert no raise. The guard is `src/sift/llm/client.py:54-84`:
```python
def _assert_local(base_url: str, allow_public: bool) -> None:
    host = urlsplit(base_url).hostname or ""
    if host == "localhost" or host.endswith(".localhost"):
        return
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    ok = ip is not None and (ip.is_loopback or ip.is_private)
    if not ok and not allow_public:
        raise ValueError(...)
```
`_assert_local` is module-private — the test imports it via `from sift.llm.client import _assert_local`. The assertion is: `_assert_local(url, allow_public=False)` returns None (no raise) for every base_url shipped in `deploy/sift.container`. This is the regression lock that the deploy default (`http://127.0.0.1:<port>/v1`) stays guard-clean and never smuggles in `host.containers.internal`.

**5. Quadlet generator dry-run — graceful skip (D-07).** No in-repo analog for skip-on-missing-binary; use `shutil.which` / `pytest.skip`:
```python
generator = "/usr/lib/systemd/system-generators/podman-system-generator"
if not Path(generator).exists():
    pytest.skip("podman quadlet generator absent; dry-run validation is best-effort (D-07)")
# QUADLET_UNIT_DIRS=deploy <generator> --user --dryrun ; assert returncode 0, deploy/*.container on stdout
```
(RESEARCH Pitfall 2 — the generator dry-run is the linter, NOT `podman quadlet install --dry-run`.)

---

### `pyproject.toml` (config — in-place extension)

**Analog:** itself, `[tool.pytest.ini_options]` block (lines 44-53). Two-line edit, mirror the existing entries exactly.

**Current** (lines 49-53):
```toml
addopts = "-m 'not perf and not live'"
markers = [
    "perf: 100 MB-scale gates, run explicitly via -m perf",
    "live: real-inference-server integration tests, run explicitly via -m live",
]
```
**Change to:**
```toml
addopts = "-m 'not perf and not live and not packaging'"
markers = [
    "perf: 100 MB-scale gates, run explicitly via -m perf",
    "live: real-inference-server integration tests, run explicitly via -m live",
    "packaging: offline install smoke + Quadlet dry-run, run explicitly via -m packaging",
]
```
Nothing else in `pyproject.toml` changes: `[project.scripts]` (37-38), `uv_build` backend (40-42), `[project.optional-dependencies] pdf` (26-27) are all carried forward unchanged (D-02, D-03).

---

### `docs/decisions/0011-quadlet-loopback-guard.md` (ADR)

**Analog:** `docs/decisions/0010-eval-exit-codes.md`

Copy the exact ADR skeleton — header block, then `## Context` / `## Decision` / `## Consequences` (`docs/decisions/0010-eval-exit-codes.md:1-11`):
```markdown
# ADR 0011: Quadlet host-reachability under the DNS-free loopback guard

**Status:** Accepted (implemented in Phase 8 / M8, Plan 08-xx)
**Date:** 2026-07-19
**Answers:** PKG-02 / D-06 (corrected) — how does an in-container Sift reach a
host-side llama-server without tripping the LLM-02 SSRF guard or needing
--i-know-what-im-doing? Cross-refs SPEC.md §7 (deploy tree) / §8 (M8), and the
guard at src/sift/llm/client.py:54-84.

## Context
...
## Decision
...
## Consequences
...
```
Content the ADR MUST record (RESEARCH §D-06 Correction, lines 309-321): (a) `_assert_local` is DNS-free by design (anti-TOCTOU) — inspects the literal hostname string, never resolves; (b) therefore `host.containers.internal` (the mechanism D-06 originally named) is REJECTED — not `*.localhost`, not a literal IP; (c) the deploy default instead uses `Network=host` + literal `127.0.0.1` (guard accepts `ip.is_loopback`), backend-agnostic across pasta/slirp4netns; (d) alternative for isolated networks is a `*.localhost` `AddHost=…:host-gateway` alias (guard accepts `*.localhost` without resolving); (e) the guard is unchanged — deploy adapts to the guard, out of scope to touch it. Match ADR 0010's prose register and the "each ADR cites the SPEC section it resolves" convention.

---

### `README.md` (docs rewrite)

**Analog:** none in-tree (current file is a 2-line stub, `wc -l README.md` → 2). Use the D-09 ordered outline (CONTEXT.md:37, RESEARCH lines 19). Section order: (1) `uv tool install .` / `git+https://…` (PKG-01); (2) start a backend — llama.cpp `llama-server` (Vulkan default on gfx1151, ROCm 7.2+ alt) AND Lemonade (:13305, embeddings-recipe caveat: `llamacpp`/`flm` only, not ONNX/OGA), two-instance setup (`SIFT_GENERATION_BASE_URL` + separate `--embeddings` server → `SIFT_EMBEDDINGS_BASE_URL`); (3) `sift doctor`; (4) `sift new → ingest → analyze → report`; (5) optional `sift[pdf]` extra + `dnf install pango` (cite ADR 0002). British English throughout (D-10). The two-instance env-var names and the pango note are the load-bearing accuracy points (RESEARCH Pattern 3, Pitfall 4).

---

### `deploy/sift.container` & `deploy/llama-server.container.example` (Quadlet units)

**Analog:** NONE — first files under `deploy/`. Use the RESEARCH skeletons verbatim (RESEARCH §Code Examples, lines 236-273). The load-bearing invariant: `sift.container` MUST use `Network=host` + `Environment=SIFT_*_BASE_URL=http://127.0.0.1:<port>/v1` (guard-clean literal loopback, RESEARCH Pattern 2). Never ship `host.containers.internal` in a base_url — it is guard-rejected (RESEARCH anti-pattern, line 182). These two files are the targets the `test_packaging.py` guard-acceptability assertion and generator dry-run read, so they must exist before those tests run (RESEARCH Wave 0 Gaps).

## Shared Patterns

### Opt-in pytest marker (perf/live → packaging)
**Source:** `pyproject.toml:49-53` + `tests/perf/test_perf_ingest.py:31`
**Apply to:** `tests/test_packaging.py` (marker on each slow test) and the `pyproject.toml` `addopts`/`markers` edit. Default suite stays fast; `uv run pytest -m packaging` runs the gate.

### Zero-network invariant across a subprocess boundary
**Source:** `tests/conftest.py:34-60` (autouse `_no_network`, patches in-process socket only)
**Apply to:** `tests/test_packaging.py`. The autouse guard does NOT cover subprocesses — enforce offline with `uv --offline`/`--no-index --find-links` + `UV_OFFLINE=1` env, per RESEARCH Pitfall 1. No conftest change needed (unlike `live`).

### SSRF loopback guard as a test oracle
**Source:** `src/sift/llm/client.py:54-84` `_assert_local`
**Apply to:** the PKG-02 guard-acceptability assertion — import `_assert_local`, feed it the shipped `deploy/sift.container` base_urls, assert no raise. Locks the deploy default guard-clean without touching the guard.

### Numbered-ADR template
**Source:** `docs/decisions/0010-eval-exit-codes.md:1-11` (header + Context/Decision/Consequences)
**Apply to:** `docs/decisions/0011-quadlet-loopback-guard.md`. Existing ADRs run 0001–0010; 0011 is next.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `deploy/sift.container` | config (Quadlet) | request-response | First `deploy/` file; no `.container` unit exists in tree. Use RESEARCH §Code Examples skeleton (lines 236-257). |
| `deploy/llama-server.container.example` | config (Quadlet) | request-response | Same — use RESEARCH skeleton (lines 259-273). |

README.md has no in-tree prose analog (stub only); planner uses the D-09 outline, not a codebase pattern.

## Metadata

**Analog search scope:** `tests/`, `tests/perf/`, `docs/decisions/`, `src/sift/llm/`, `pyproject.toml`, `tests/conftest.py`
**Files scanned:** 6 (client.py, conftest.py, test_perf_ingest.py, pyproject.toml, 0010-eval-exit-codes.md, CONTEXT/RESEARCH)
**Pattern extraction date:** 2026-07-19
