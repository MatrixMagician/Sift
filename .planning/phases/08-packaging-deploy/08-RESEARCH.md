# Phase 8: Packaging & Deploy - Research

**Researched:** 2026-07-19
**Domain:** Python packaging (`uv tool install`), Podman Quadlet rootless deployment, Fedora/gfx1151 inference-backend docs
**Confidence:** HIGH (packaging), MEDIUM (Quadlet/networking — verified against Podman docs, one load-bearing correction to D-06)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Distribution is **local + VCS `uv tool install` only** (`uv tool install .` and `uv tool install git+https://…`). No PyPI / registry publish this phase.
- **D-02:** Keep the existing `uv_build` backend and `[project.scripts] sift = "sift.cli:app"`. Carried forward, not re-decided.
- **D-03:** Do not bump the package version; leave it at `0.1.0`.
- **D-04:** Prove PKG-01 with an **offline packaging smoke test**: `uv build` a wheel, install into an isolated throwaway env, assert the real `sift` console script runs. Fully offline; gate behind an opt-in pytest marker (like `perf`/`live`). Exact marker name is the planner's call.
- **D-05:** Ship `deploy/sift.container` + `deploy/llama-server.container.example`, matching SPEC §7. Rootless Podman is the documented default.
- **D-06:** **Loopback-guard interaction (load-bearing).** In-container the inference endpoint is reached via `http://host.containers.internal:<port>/v1`. CONTEXT asserts `host.containers.internal` resolves to an RFC1918 address which `_assert_local` already permits, so no `--i-know-what-im-doing` is needed. **⚠ See "D-06 Correction" below — the stated MECHANISM is wrong (the guard never resolves DNS), though the GOAL (no override needed) is achievable via a corrected recipe.**
- **D-07:** Validate Quadlet files against the `podman quadlet` dry-run docs; **automated validation must skip gracefully** when podman/the generator is unavailable (documentation + best-effort dry-run, not a hard CI gate).
- **D-08:** Record the Quadlet ↔ loopback-guard decision as a new ADR `docs/decisions/0011-*.md`.
- **D-09:** Rewrite `README.md` into a quickstart: (1) `uv tool install`; (2) start a backend — llama.cpp `llama-server` (Vulkan default on gfx1151, ROCm 7.2+ alternative) AND Lemonade Server (port 13305, embeddings-recipe caveat), two-instance setup (generation + separate `--embeddings`); (3) `sift doctor`; (4) first-case walkthrough `new → ingest → analyze → report`; (5) optional `sift[pdf]` extra + `dnf install pango` (per ADR 0002).
- **D-10:** British English throughout.

### Claude's Discretion
- Exact pytest marker name/mechanism for the packaging smoke test.
- README section ordering and prose.
- Whether `llama-server.container.example` uses Vulkan or ROCm in its example command (recommend Vulkan default).
- Whether a `sift --version` affordance is added if not already present (nice-to-have, not required by PKG-01).

### Deferred Ideas (OUT OF SCOPE)
- Publishing to PyPI / a container registry.
- Homebrew / AUR / Windows / macOS packaging.
- Release-automation / semver-bump tooling; the v1.0 tag is a separate authorised step.
- Bundling or serving models.
- **Any change to the inference client's guard behaviour** (`_assert_local`) — the deploy must adapt to the guard, not vice versa.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PKG-01 | `uv tool install` from a clean checkout yields a working `sift` (pipx-compatible) | Standard Stack (uv build/install mechanics), Validation Architecture (offline smoke test), README quickstart |
| PKG-02 | Optional Podman Quadlet deploy files ship with a llama-server example, documented for Fedora/gfx1151 (Vulkan + ROCm) | Architecture Patterns (Quadlet units), D-06 Correction (guard-compatible host reachability), Validation Architecture (graceful-skip dry-run) |
</phase_requirements>

## Summary

This is a **docs + deploy-files phase**, not a code phase. The wheel already builds (`uv_build` backend + `[project.scripts] sift = "sift.cli:app"` are wired and working), so PKG-01 is proven, not built: `uv build` a wheel, install it offline into a throwaway env, run `sift --help`/`sift new`. No new runtime dependencies are added. The only optional code change is a `sift --version` affordance (Typer callback), which PKG-01 does not require.

PKG-02 is three deliverables: `deploy/sift.container`, `deploy/llama-server.container.example`, and a README quickstart — plus ADR 0011. The **single load-bearing risk** is the SSRF guard. CONTEXT decision **D-06's mechanism is incorrect**: `_assert_local` (`src/sift/llm/client.py:70`) **never performs DNS resolution** — it inspects the literal hostname string. The hostname `host.containers.internal` is not `localhost`, not `*.localhost`, and not a literal IP, so the guard **rejects it** and demands `--i-know-what-im-doing`. The test D-06 cites (`test_assert_local_accepts_loopback_and_rfc1918`) only proves *literal RFC1918 IPs* and `localhost` pass — it does **not** test the `host.containers.internal` hostname. The GOAL of D-06 (no override in the deploy default) is still achievable, but the recipe must use a literal loopback IP (`Network=host` + `127.0.0.1`) or the `*.localhost` name rule — never the `host.containers.internal` hostname in the base_url. This correction is the substance ADR 0011 must record.

**Primary recommendation:** Prove PKG-01 with an offline subprocess smoke test behind a new `packaging` marker (and extend `addopts` to exclude it). For PKG-02, make `deploy/sift.container` use `Network=host` and document `SIFT_*_BASE_URL=http://127.0.0.1:<port>/v1` (loopback literal → guard-clean, backend-agnostic across pasta/slirp4netns). Validate Quadlet files with the systemd-generator dry-run, skipping gracefully when podman is absent.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Wheel build + console script | Build backend (`uv_build`) | — | Already produces `sift`; nothing to author |
| Offline install proof (PKG-01) | Test harness (pytest, opt-in marker) | `uv` CLI subprocess | Runs `uv build`/install in a throwaway env, asserts `sift` runs |
| Host→container reachability (PKG-02) | Podman networking (pasta/slirp4netns) | `_assert_local` guard (unchanged) | Deploy config must yield a guard-acceptable literal address |
| Quadlet unit definition | systemd + Quadlet generator | Podman | `.container` files generate `.service` units at boot |
| Backend setup guidance | README docs | llama.cpp / Lemonade (external) | Sift never touches the GPU; it documents, not manages, the server |
| PDF extra path | `sift[pdf]` optional-dependency (existing) | pango system lib | Documented in README per ADR 0002 |

## Standard Stack

No new packages. Everything needed is already in the toolchain or the OS.

### Core (already present — carried forward, D-02)
| Tool | Version | Purpose | Why Standard |
|------|---------|---------|--------------|
| uv | latest (self-updating) | `uv build` (wheel/sdist), `uv tool install` | SPEC constraint; `uv_build` is uv's native backend — no PEP 517 frontend fetch needed `[CITED: docs.astral.sh/uv]` |
| uv_build | `>=0.11,<0.12` | Build backend | Already in `[build-system]`; bundled in uv, so `uv build` needs no network for the build step itself `[VERIFIED: pyproject.toml]` |
| Podman | 5.x (Fedora current) | Rootless Quadlet runtime | Fedora reference platform; pasta is the default rootless backend since Podman 5.x `[CITED: sanj.dev / eriksjolund docs]` |
| systemd generator | `/usr/lib/systemd/system-generators/podman-system-generator` | Quadlet dry-run validation | Canonical Quadlet validator (see Pitfall 2) `[CITED: oneuptime, podman discussions #24891]` |

### Supporting (documented, not depended-on)
| Item | Purpose | When |
|------|---------|------|
| llama.cpp `llama-server` (Vulkan / ROCm build) | Generation + embeddings backend | README quickstart (D-09) |
| Lemonade Server (:13305) | Alternative backend | README quickstart; embeddings only via `llamacpp`/`flm` recipe (not ONNX/OGA) — per project CLAUDE.md finding #7 |
| pango (Fedora system lib) | WeasyPrint dep for `sift[pdf]` | README `dnf install pango` note (ADR 0002) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `Network=host` + `127.0.0.1` | slirp4netns `10.0.2.2` literal | Only works if you pin the (non-default) slirp4netns backend; `Network=host` is backend-agnostic and guard-clean |
| systemd-generator `--dryrun` | `podman quadlet install --dry-run` | The `podman quadlet` subcommand (Podman 5.6+) is install/list/print/rm; its `--dry-run` previews *what would be updated*, it is not the syntax validator. The generator dry-run is the real linter `[CITED: docs.podman.io/podman-quadlet.1]` |

**Installation:** none — no new packages. `uv build` and `uv tool install` are already available.

**Version verification:** No package versions to verify (D-03 freezes at 0.1.0; no new deps). The build toolchain (`uv_build>=0.11,<0.12`) is already pinned in `pyproject.toml`.

## Package Legitimacy Audit

**No new packages are installed by this phase.** Deploy files and README are plain text/config; the offline smoke test uses only stdlib `subprocess`/`tempfile` + the already-present `uv`. Nothing to audit.

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
  Developer / stranger on Fedora
            │
            │  uv tool install .   (or git+https://…)   [PKG-01]
            ▼
   ┌──────────────────┐   uv_build backend
   │  clean checkout   │──────────────► sift-0.1.0-*.whl ──► isolated tool env
   └──────────────────┘                                          │
                                                     $ sift new/ingest/analyze/report
                                                                 │
                                       ┌─────────────────────────┴─────────────────┐
                                       │  DEPLOY MODE (optional, PKG-02)            │
                                       │                                           │
  ┌────────────────────────┐          │   deploy/sift.container (Quadlet)          │
  │ host: llama-server      │          │     Network=host                          │
  │  :GEN  (generation)     │◄─────────┼── SIFT_GENERATION_BASE_URL=                │
  │  :EMB  (--embeddings)   │◄─────────┼── http://127.0.0.1:GEN/v1  (loopback)     │
  └────────────────────────┘  literal  │   http://127.0.0.1:EMB/v1                 │
        ▲ RFC1918/loopback IP           │        │ passes _assert_local, NO         │
        │ passes guard                  │        │ --i-know-what-im-doing needed    │
        │                               │   deploy/llama-server.container.example  │
        └───────────────────────────────┴──────────────────────────────────────────┘
```

### Recommended Project Structure (new files only)
```
deploy/
├── sift.container                    # Quadlet unit: runs sift, Network=host, env → 127.0.0.1
└── llama-server.container.example    # Quadlet example: llama-server (Vulkan default)
docs/decisions/
└── 0011-quadlet-loopback-guard.md    # ADR (D-08) — records the D-06 CORRECTION
README.md                             # rewritten quickstart (D-09)
tests/
└── test_packaging.py                 # offline install smoke test, @pytest.mark.packaging (D-04)
```

### Pattern 1: Offline install smoke test (PKG-01 proof, D-04)
**What:** Build a wheel, install it into a throwaway env with network disabled, run the real console script.
**When to use:** The one automated proof that PKG-01 holds end-to-end.
**Key mechanics:**
- The conftest `_no_network` autouse fixture patches `socket.socket.connect` **in the pytest process only** — it does **not** reach `uv`/`sift` subprocesses. Offline-ness of the subprocesses must be enforced explicitly with uv's own flags.
- Force offline on every uv subprocess: `uv build --offline` and `uv tool install --offline <wheel>` (or `uv pip install --no-index --find-links dist/`). `--offline` == `UV_OFFLINE=1`; `--no-index` ignores PyPI; `--find-links` points at local wheels. `[CITED: docs.astral.sh/uv/reference/environment, settings]`
- Runtime deps (httpx, pydantic, scikit-learn, sqlite-vec, typer, zstandard, pyyaml, rich) must already be in the uv cache (they are, after `uv sync`), so `--offline` resolves them from cache.
- Install into a `tempfile.mkdtemp()` env (e.g. `uv tool install --offline --tool-dir <tmp> …`, or a throwaway `uv venv` + `uv pip install`), then `subprocess.run([<env>/bin/sift, "--help"])` and a trivial `sift new` in a scratch case dir. Assert exit 0 and expected output.
**Example:**
```python
# Source: pattern derived from docs.astral.sh/uv + tests/conftest.py socket note
import subprocess, sys, tempfile, os
from pathlib import Path

# 1. build wheel offline
subprocess.run(["uv", "build", "--offline", "--wheel", "-o", dist], check=True)
wheel = next(Path(dist).glob("sift-*.whl"))
# 2. throwaway venv, offline install from the local wheel only
subprocess.run(["uv", "venv", venv], check=True)
subprocess.run(["uv", "pip", "install", "--offline", "--no-index",
                "--find-links", dist, str(wheel), "--python", f"{venv}/bin/python"], check=True)
# 3. the real console script runs
out = subprocess.run([f"{venv}/bin/sift", "--help"], capture_output=True, text=True, check=True)
assert "ingest" in out.stdout
```

### Pattern 2: Guard-compatible host reachability (PKG-02, corrects D-06)
**What:** Make the in-container base_url a literal loopback/RFC1918 address so `_assert_local` accepts it with no override.
**When to use:** Any Quadlet that points Sift at a host-side (or sibling-container) llama-server.
**Recommended (robust, backend-agnostic):**
```ini
# deploy/sift.container  →  [Container]
Network=host
Environment=SIFT_GENERATION_BASE_URL=http://127.0.0.1:8080/v1
Environment=SIFT_EMBEDDINGS_BASE_URL=http://127.0.0.1:8081/v1
```
`127.0.0.1` is a literal loopback IP → `_assert_local` returns immediately (`ip.is_loopback`), no `--i-know-what-im-doing`. Works identically under pasta and slirp4netns because host networking shares the host's loopback.
**Alternative (isolated container, `.localhost` name-rule trick):** if `Network=host` is undesirable, add a host alias and target it — the guard accepts any `*.localhost` name **without resolving it**, and Podman resolves the alias at connect time:
```ini
AddHost=infra.localhost:host-gateway     # Podman 5.3.0+; host-gateway → the host
Environment=SIFT_GENERATION_BASE_URL=http://infra.localhost:8080/v1
```
**Anti-pattern (what D-06 literally proposes):** `SIFT_*_BASE_URL=http://host.containers.internal:8080/v1` → **REJECTED** by the guard (hostname, not a literal IP, not `*.localhost`; guard does no DNS). Do not ship this as the default.

### Pattern 3: Two-instance backend (README, D-09)
llama.cpp's `--embeddings`/`--embedding` flag makes a server **embedding-only**, so generation and embeddings need **two `llama-server` instances** (or Lemonade managing both). README documents both `SIFT_GENERATION_BASE_URL` and `SIFT_EMBEDDINGS_BASE_URL` pointing at the two ports. (Per project CLAUDE.md findings #6/#7.)

### Anti-Patterns to Avoid
- **Baking `--i-know-what-im-doing` into a Quadlet default:** it is a break-glass for genuinely public endpoints, not a deploy convenience. If the deploy needs it for localhost, the address is wrong.
- **Relying on `host.containers.internal` in the base_url:** guard-rejected by design (no DNS). See Pattern 2.
- **Assuming `podman quadlet install --dry-run` lints syntax:** it previews what would be *updated*, not whether the unit parses. Use the generator dry-run.
- **Hard-failing CI when podman is absent:** D-07 requires graceful skip.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Wheel build | Custom setup.py / build script | Existing `uv_build` backend + `uv build` | Already wired and working (D-02) |
| Isolated install env | Manual venv bookkeeping | `uv venv` / `uv tool install --tool-dir` | uv manages the throwaway env; delete the tmpdir to clean up |
| Quadlet syntax check | Regex/hand parser for `.container` | systemd-generator `--dryrun` | Authoritative; catches unsupported keys and parse errors |
| Host-reachability address | New guard exception / DNS logic | `Network=host` + `127.0.0.1` | Zero code; guard already accepts loopback (out-of-scope to touch the guard anyway) |

**Key insight:** This phase writes *config and prose*, not code. Every "problem" already has an existing tool; the only real design decision is the guard-compatible address (Pattern 2).

## Common Pitfalls

### Pitfall 1: The offline smoke test isn't actually offline
**What goes wrong:** The pytest `_no_network` fixture blocks sockets in-process, but `uv build`/`uv tool install` run as subprocesses and can hit PyPI for index metadata, silently violating the zero-network rule.
**Why it happens:** subprocess network access bypasses the in-process monkeypatch.
**How to avoid:** pass `--offline` (or `--no-index --find-links dist/`) to every uv subprocess; assert the commands succeed purely from cache. Consider setting `env={"UV_OFFLINE": "1", **os.environ}` on the subprocess.
**Warning signs:** test passes on a networked dev box but the command logs "Resolving…"/index fetches; would fail in an air-gapped CI.

### Pitfall 2: `podman quadlet` subcommand ≠ Quadlet linter
**What goes wrong:** Planner writes a validation step around `podman quadlet` expecting a `validate`/`dryrun` subcommand; there isn't one (subcommands are install/list/print/rm).
**Why it happens:** SPEC/CONTEXT wording "validate per `podman quadlet` dry-run docs" is loose.
**How to avoid:** validate with the generator dry-run, pointing `QUADLET_UNIT_DIRS` at `deploy/`:
```bash
QUADLET_UNIT_DIRS=deploy \
  /usr/lib/systemd/system-generators/podman-system-generator --user --dryrun
# legacy fallback (older Podman): /usr/libexec/podman/quadlet --user --dryrun
```
Errors go to stderr, generated units to stdout. `[CITED: oneuptime, podman discussions #24891]`
**Warning signs:** validation "passes" because the nonexistent subcommand no-ops.

### Pitfall 3: pasta vs slirp4netns changes host reachability
**What goes wrong:** Docs written for slirp4netns (`10.0.2.2`) silently mislead on Podman 5.x where **pasta is the default**; `host.containers.internal` is added to `/etc/hosts` but its exact target and host-loopback reachability differ, and reaching host loopback under pasta may need `--map-gw`.
**Why it happens:** the default backend flipped to pasta in Podman 5.x.
**How to avoid:** sidestep the whole backend question — `Network=host` + `127.0.0.1` reaches host services identically under both. Document the pasta/`--map-gw` and slirp4netns/`10.0.2.2` details only as an aside for isolated-network users. `[CITED: eriksjolund/podman-networking-docs, sanj.dev]`
**Warning signs:** "works on my machine (slirp4netns)" but fails on a stock Podman 5.x box.

### Pitfall 4: Lemonade embeddings on the wrong recipe
**What goes wrong:** README tells users to use Lemonade for embeddings, but `/v1/embeddings` works **only** for `llamacpp`/`flm`-recipe models, not ONNX/OGA — the common Strix Halo chat default.
**How to avoid:** README must name this failure mode and tell users to run `sift doctor` (which round-trips a real embedding call). Per project CLAUDE.md finding #7.

## Code Examples

### Quadlet: `deploy/sift.container` (skeleton)
```ini
# Source: docs.podman.io/podman-systemd.unit.5 + Pattern 2
[Unit]
Description=Sift incident triage (rootless)
After=network-online.target

[Container]
Image=localhost/sift:latest
Network=host
Environment=SIFT_GENERATION_BASE_URL=http://127.0.0.1:8080/v1
Environment=SIFT_EMBEDDINGS_BASE_URL=http://127.0.0.1:8081/v1
# case data on the host:
Volume=%h/.local/share/sift:/data:Z
Exec=--help

[Service]
Restart=on-failure

[Install]
WantedBy=default.target
```

### Quadlet: `deploy/llama-server.container.example` (Vulkan default, D discretion)
```ini
# Source: llama.cpp server README + SPEC §3 (Vulkan is the robust default on gfx1151)
[Unit]
Description=llama-server generation backend (example)

[Container]
Image=ghcr.io/ggml-org/llama.cpp:server-vulkan   # example tag; user supplies model
PublishPort=8080:8080
Exec=-m /models/model.gguf --host 0.0.0.0 --port 8080
# embeddings: a SECOND instance with --embeddings on :8081

[Install]
WantedBy=default.target
```

### Optional `sift --version` (D discretion)
```python
# Source: Typer callback pattern; app is typer.Typer(no_args_is_help=True) at cli.py:42
from importlib.metadata import version as _pkg_version

@app.callback()
def _main(version: bool = typer.Option(False, "--version", is_eager=True)) -> None:
    if version:
        typer.echo(_pkg_version("sift"))
        raise typer.Exit()
```
Not required by PKG-01; add only if cheap.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| slirp4netns default rootless net | **pasta** default | Podman 5.x | Host-reachability docs must not assume `10.0.2.2`; use `Network=host` |
| `/usr/libexec/podman/quadlet --dryrun` | `/usr/lib/systemd/system-generators/podman-system-generator --dryrun` | Podman 5.x layout | Validation script tries the generator first, legacy path as fallback |
| (no user-facing quadlet CLI) | `podman quadlet {install,list,print,rm}` | Podman 5.6+ | Install convenience only — NOT a validator |

**Deprecated/outdated:** none introduced by this phase.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `uv build`/`uv tool install --offline` resolve all runtime deps from the local cache after a prior `uv sync`, needing zero network | Standard Stack / Pattern 1 | Smoke test needs a one-off cache-warm step, or must vendor wheels into `dist/` via `--find-links`; still fully offline, just a small plan tweak |
| A2 | `uv_build` (bundled in uv) needs no network for the build step, so `uv build --offline` succeeds | Standard Stack | If uv tries to fetch a build frontend, pre-seed it; low risk — uv_build is native |
| A3 | `Network=host` + `127.0.0.1` reaches a host `llama-server` under both pasta and slirp4netns | Pattern 2 | If host networking is disabled in a hardened setup, fall back to the `*.localhost` `AddHost` trick (also guard-clean) |
| A4 | Example llama.cpp container tag `server-vulkan` exists on ghcr.io | Code Examples | It's an *example* file; user supplies the real image/model. Cosmetic only |

**Note:** A1/A2 are the only assumptions that could affect the smoke-test plan shape; both have documented offline fallbacks (`--find-links dist/`).

## D-06 Correction (load-bearing — ADR 0011 must record this)

**Verified against `src/sift/llm/client.py:70-84` and `src/sift/config.py` (base_url flows verbatim to `_assert_local`, no DNS):**

`_assert_local(base_url, allow_public)` accepts a host **iff** it is:
1. the name `localhost` or any `*.localhost`, **or**
2. a **literal** IP that is loopback / RFC1918 / link-local.

It **explicitly refuses DNS resolution** (docstring: "never performs a DNS lookup … so there is no TOCTOU egress"). Therefore the *hostname* `host.containers.internal` — the mechanism named in D-06 — is **rejected** (`ipaddress.ip_address("host.containers.internal")` → `ValueError` → `ip=None` → `ok=False` → raises). The cited test `tests/test_llm_client.py:49` proves only literal RFC1918 IPs and `localhost`/`*.localhost` pass; it does **not** exercise `host.containers.internal`.

**The GOAL of D-06 stands** (no `--i-know-what-im-doing` in the deploy default) **via the corrected recipe** in Pattern 2: use `Network=host` + literal `127.0.0.1`, or a `*.localhost` `AddHost` alias. `[VERIFIED: src/sift/llm/client.py, tests/test_llm_client.py]`

ADR 0011 should state: (a) the guard is DNS-free by design (anti-TOCTOU); (b) hence deploy uses a literal loopback/`*.localhost` address, not `host.containers.internal`; (c) this keeps the guard unchanged (out of scope) while shipping a guard-clean default.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | PKG-01 build/install + smoke test | ✓ | present | — |
| uv cache (runtime deps) | offline smoke test | ✓ (after `uv sync`) | — | `--find-links dist/` with vendored wheels |
| podman | PKG-02 Quadlet dry-run | ✗ in CI (likely) | — | **graceful skip (D-07)** |
| systemd generator | Quadlet dry-run | host-only | — | skip when absent |
| pango | `sift[pdf]` (docs only) | N/A this phase | — | README `dnf install pango` |

**Missing dependencies with no fallback:** none block PKG-01.
**Missing dependencies with fallback:** podman/generator absent in CI → Quadlet validation skips gracefully (documented, best-effort), never a hard gate.

## Validation Architecture

> nyquist_validation is enabled (config.json). This section seeds VALIDATION.md.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest` (default suite; excludes `perf`/`live`) |
| Full suite command | `uv run pytest -m 'perf or live or packaging'` for the opt-in gates + `uv run pytest` for the rest |
| Milestone gate | `ruff check`, `pyright`, `pytest` all clean (SPEC §8) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PKG-01 | `uv build` → offline install into throwaway env → `sift --help` exits 0 | integration (offline subprocess) | `uv run pytest -m packaging tests/test_packaging.py` | ❌ Wave 0 |
| PKG-01 | Installed `sift new <case>` creates a case (real console script) | integration | (same test module) | ❌ Wave 0 |
| PKG-02 | `deploy/*.container` parse via generator dry-run | integration, **graceful-skip** | `uv run pytest -m packaging -k quadlet` (skips if generator/podman absent) | ❌ Wave 0 |
| PKG-02 | Deploy default uses a guard-acceptable literal address (no `--i-know-what-im-doing`) | unit (assert on the shipped file's env values via `_assert_local`) | parse `deploy/sift.container`, feed base_url to `_assert_local(...)`, assert no raise | ❌ Wave 0 |
| PKG-02 | README documents Vulkan/ROCm + Lemonade recipe caveat + two-instance + pdf extra | manual/human-verify | — (prose review) | manual |

### Sampling Rate
- **Per task commit:** `uv run pytest` (fast default suite stays green).
- **Per wave merge:** add `uv run pytest -m packaging` (the offline smoke + Quadlet dry-run).
- **Phase gate:** `ruff check` + `pyright` + full `pytest` (incl. `-m packaging`) green before `/gsd-verify-work`; README quickstart walked manually on a clean checkout.

### Automatable vs Manual
- **Automatable:** offline install smoke (PKG-01); the guard-acceptability assertion on the shipped `deploy/sift.container` env values (parse the file, call `_assert_local` on the literal base_url — no podman needed, always runs in CI).
- **Graceful-skip (podman/generator may be absent):** the Quadlet generator dry-run — `pytest.importorskip`-style guard on the generator binary; skip with a clear reason, never fail CI (D-07).
- **Manual/human-verify:** README prose accuracy (Vulkan/ROCm/Lemonade/pdf), and a true clean-checkout `uv tool install .` walkthrough on a Fedora box.

### Wave 0 Gaps
- [ ] `tests/test_packaging.py` — offline install smoke (PKG-01) + generator dry-run (graceful-skip) + guard-acceptability assertion on `deploy/sift.container`.
- [ ] New `packaging` pytest marker in `pyproject.toml` **and** extend `addopts` to `-m 'not perf and not live and not packaging'` (else the new marker runs in the default fast suite — regression risk).
- [ ] `deploy/sift.container`, `deploy/llama-server.container.example` (test targets must exist before the dry-run test).

## Security Domain

> security_enforcement enabled, ASVS level 1, block_on high.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | no | No new input surface (docs/config only) |
| V6 Cryptography | no | — |
| V14 Configuration / Deployment | **yes** | Quadlet ships a guard-clean default (loopback literal); no secrets baked in; rootless Podman |
| V1 Architecture (trust boundary) | **yes** | The SSRF guard (LLM-02) trust boundary must not be weakened by deploy docs — no `--i-know-what-im-doing` default |

### Known Threat Patterns for this phase
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Deploy docs teach users to pass `--i-know-what-im-doing`, normalising SSRF-guard bypass | Elevation of Privilege / Tampering | Ship a guard-clean default (Pattern 2, `127.0.0.1`); mention the override only as a genuinely-remote break-glass |
| Smoke test reaches the network, breaking zero-egress invariant | Information Disclosure | `--offline`/`--no-index` on all uv subprocesses (Pitfall 1) |
| Supply-chain: new/unpinned deps enter via packaging | Tampering | No new deps this phase; deps stay pinned; wheel built from the checked-out source only |
| Quadlet baking a secret/token into a shipped `.container` | Information Disclosure | Env values are localhost URLs only; no credentials; `.example` for the backend unit |

**Note:** The load-bearing security item is V1/V14 — the deploy must **not** erode the LLM-02 SSRF guard. Pattern 2 + ADR 0011 are the mitigation. No high-severity findings expected; no guard code changes (out of scope).

## Sources

### Primary (HIGH confidence)
- `src/sift/llm/client.py:70-84` `_assert_local` — guard logic, DNS-free by design (read this session)
- `tests/test_llm_client.py:36-64` — proves literal RFC1918/`localhost` pass; does NOT test `host.containers.internal`
- `src/sift/config.py:29-95`, `src/sift/cli.py:732-1133` — base_url flows verbatim to `Endpoint`→`_assert_local`, no resolution
- `pyproject.toml` — `uv_build` backend, `[project.scripts]`, `perf`/`live` markers + `addopts`
- `docs/decisions/0002-weasyprint-pdf-extra.md` — `sift[pdf]` + pango
- `SPEC.md` §3/§7/§8 — Fedora/gfx1151, Vulkan default/ROCm 7.2+, deploy layout, M8 acceptance

### Secondary (MEDIUM confidence)
- docs.astral.sh/uv (environment, settings, troubleshooting) — `--offline`/`--no-index`/`--find-links`, `uv build`/`uv tool install`
- docs.podman.io/podman-quadlet.1, podman-systemd.unit.5 — subcommands (install/list/print/rm), unit keys
- github.com/eriksjolund/podman-networking-docs — pasta vs slirp4netns, `host.containers.internal`, `--map-gw`, `10.0.2.2`, `AddHost=…:host-gateway` (5.3.0+)
- oneuptime Quadlet-validation post + github.com/containers/podman discussions #24891 — generator `--dryrun`, `systemd-analyze verify`

### Tertiary (LOW confidence)
- sanj.dev pasta-vs-slirp4netns (fetch 403'd; corroborated via search snippet only) — pasta default since Podman 5.x, `--map-gw`

## Metadata

**Confidence breakdown:**
- Standard stack / packaging: HIGH — mechanics verified against uv docs + existing working `pyproject.toml`.
- Quadlet / networking: MEDIUM — Podman docs + community docs; pasta default corroborated; the D-06 correction is HIGH (verified directly against the guard code + test).
- Pitfalls: HIGH — grounded in the actual conftest socket behaviour and the guard code.

**Research date:** 2026-07-19
**Valid until:** ~2026-08-18 (uv/Podman move fast; re-verify pasta default and `podman quadlet` subcommands if Podman minor bumps).
