# Phase 8: Packaging & Deploy - Context

**Gathered:** 2026-07-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 8 delivers the **packaging and deployment surface** so a stranger on Fedora can go from a clean checkout to their first triage report using only the README. Two requirements:

- **PKG-01** — `uv tool install` from a clean checkout yields a working `sift` (pipx-compatible).
- **PKG-02** — Optional Podman Quadlet deployment files ship with a llama-server example, documented for Fedora/gfx1151 (Vulkan and ROCm notes), including how `host.containers.internal` interacts with the loopback guard.

**In scope:** finalise `pyproject.toml` packaging metadata; rewrite the stub `README.md` into a working quickstart; add `deploy/` Quadlet files (`sift.container` + `llama-server.container.example`); an offline packaging/install smoke test proving PKG-01; a new ADR recording the Quadlet↔loopback-guard decision.

**Out of scope (new capabilities → other phases / backlog):** publishing to PyPI or a container registry; Homebrew/AUR/Windows/macOS packaging; model download/serving (that is llama.cpp's / Lemonade's job, per SPEC); release-automation / version-bump tooling; any change to the inference client's guard behaviour.
</domain>

<decisions>
## Implementation Decisions

### Distribution & install
- **D-01:** Distribution is **local + VCS `uv tool install` only** — `uv tool install .` from a clean checkout and `uv tool install git+https://…` from the repo. **No PyPI / registry publish this phase.** Rationale: the SPEC M8 acceptance criterion is explicitly "from a clean checkout"; publishing is scope creep and is deferred. pipx-compatibility (PKG-01) comes free from a standard wheel.
- **D-02:** Keep the existing `uv_build` build-backend and the `[project.scripts] sift = "sift.cli:app"` console-script entry point — already present in `pyproject.toml` and working. **Carried forward, not re-decided.**
- **D-03:** **Do not bump the package version in this phase**; leave it at `0.1.0`. The v1.0 release tag / version bump is a separate, explicitly-authorised release action (consistent with the project's local-branch-only, each-step-separately-authorised convention). `uv tool install` works regardless of the version string, so this does not block PKG-01.

### Install verification (PKG-01 proof)
- **D-04:** Prove PKG-01 with an **offline packaging smoke test**: `uv build` a wheel, install it into an **isolated throwaway environment**, then assert the real `sift` console script runs (e.g. `sift --help` and a trivial `sift new`). Fully offline — respects the zero-network-in-tests invariant. Gate it behind an opt-in pytest marker (like the existing `perf` / `live` markers with the `addopts` filter) so the default suite stays fast; exact marker name is the planner's call.

### Podman Quadlet deployment (PKG-02)
- **D-05:** Ship `deploy/sift.container` (Podman Quadlet unit) and `deploy/llama-server.container.example`, matching the SPEC §7 directory tree. **Rootless Podman is the documented default.**
- **D-06:** **Loopback-guard interaction (load-bearing — CORRECTED after research, 2026-07-19).** The original mechanism was wrong. `_assert_local` (`src/sift/llm/client.py:54-84`) inspects the **literal hostname string and never performs DNS**: it accepts `localhost` / `*.localhost` and literal loopback / RFC1918 / link-local **IPs**, and refuses everything else unless `allow_public`. Because `host.containers.internal` is a bare hostname (not `*.localhost`, not a literal IP), the guard would **REJECT** it — the RFC1918-resolution reasoning does not apply (the guard never resolves). To preserve the goal (**no `--i-know-what-im-doing` from inside the container**), the Quadlet uses **`Network=host` and points Sift at `http://127.0.0.1:<port>/v1`** — a loopback literal the guard accepts, and backend-agnostic. **Alternative** (only if network isolation is required): a `*.localhost` `AddHost` alias (e.g. `llama.localhost` → host address) pointed at via `http://llama.localhost:<port>/v1`, since the guard accepts `*.localhost`. Document the guard's literal-string behaviour and the chosen mechanism. Recorded in ADR 0011 (D-08) and `08-RESEARCH.md`.
- **D-07:** Validate the Quadlet files against the `podman quadlet` dry-run docs. Because Podman may be absent on a CI runner, **any automated validation must skip gracefully** when `podman` / the quadlet generator is unavailable — this is documentation + best-effort dry-run, **not a hard CI gate** that fails on a Podman-less machine.
- **D-08:** Record the Quadlet ↔ loopback-guard deployment decision as a **new ADR (`docs/decisions/0011-*.md`)**, following the project's numbered-ADR convention (each ADR cites the SPEC section / requirement it resolves).

### README quickstart (PKG-01 / PKG-02 docs)
- **D-09:** Rewrite `README.md` (currently a ~2-line stub) into a **quickstart** covering, in order: (1) install via `uv tool install`; (2) start an inference backend — two documented paths: **llama.cpp `llama-server`** (Vulkan as the default/robust backend on gfx1151, ROCm 7.2+ as the alternative) **and Lemonade Server** (port 13305; note the embeddings-recipe caveat — embeddings work only for `llamacpp`/`flm` recipe models, not ONNX/OGA); note the **two-instance setup** (generation + a separate `--embeddings` server); (3) `sift doctor`; (4) first-case walkthrough `sift new → ingest → analyze → report`; (5) the optional `sift[pdf]` extra with the Fedora `dnf install pango` note (per ADR 0002).
- **D-10:** British English throughout, per project convention.

### Claude's Discretion
- Exact pytest marker name/mechanism for the packaging smoke test.
- README section ordering and prose.
- Whether `llama-server.container.example` uses Vulkan or ROCm in its example command (recommend Vulkan as the default).
- Whether a `sift --version` affordance is added if not already present (nice-to-have, not required by PKG-01).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & acceptance
- `.planning/REQUIREMENTS.md` — PKG-01, PKG-02 (definitions of done).
- `SPEC.md` §8 "M8 — Packaging + deploy" — acceptance criteria (uv tool install, Quadlet dry-run validation, README quickstart scope).
- `SPEC.md` §7 (directory tree) — canonical `deploy/sift.container` + `deploy/llama-server.container.example` layout.
- `SPEC.md` §1 / hardware table — Strix Halo gfx1151, Vulkan is the "more robust default", ROCm 7.2+; Sift never touches the GPU (only the inference server does).

### Load-bearing code (Quadlet decision)
- `src/sift/llm/client.py:54-84` `_assert_local(base_url, allow_public)` — the SSRF guard; inspects the **literal hostname**, never resolves DNS. Accepts `localhost` / `*.localhost` and literal loopback / RFC1918 / link-local IPs; refuses everything else (including bare hostnames like `host.containers.internal`) unless `allow_public`.
- `tests/test_llm_client.py` `test_assert_local_accepts_loopback_and_rfc1918` — proves literal RFC1918 **IPs** pass; it does NOT cover bare hostnames, so it does not license `host.containers.internal` (see corrected D-06).
- `src/sift/cli.py` — `--i-know-what-im-doing` flag on `doctor`/`analyze`/`eval` ("Allow a non-loopback/non-RFC1918 inference endpoint (LLM-02)").

### Packaging assets & prior decisions
- `pyproject.toml` — existing `[project.scripts]`, `[project.optional-dependencies] pdf`, `uv_build` backend, `[tool.pytest.ini_options]` markers (`perf`, `live`) + `addopts` filter (the smoke-test marker follows this pattern).
- `docs/decisions/0002-weasyprint-pdf-extra.md` — `sift[pdf]` extra + pango system dep (README documents this).
- `docs/decisions/0001-typer-over-argparse.md` — CLI framework (context for the console script).
- `CLAUDE.md` (project) — stack constraints, zero-egress invariant, British English, ADR convention.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `[project.scripts] sift = "sift.cli:app"` — console entry point already wired; PKG-01 only needs to verify it installs and runs.
- `[project.optional-dependencies] pdf = ["markdown==3.10.2", "weasyprint==69.0"]` — the `sift[pdf]` extra already exists; README documents its install path.
- `uv_build>=0.11,<0.12` build backend already configured — produces the wheel the smoke test builds.
- pytest marker + `addopts` pattern (`perf`, `live`) — the offline packaging smoke test reuses this opt-in mechanism.

### Established Patterns
- Loopback/RFC1918 guard (`_assert_local`) + `--i-know-what-im-doing` escape hatch — the Quadlet doc explains why the escape hatch is NOT needed via `host.containers.internal`.
- Numbered ADRs in `docs/decisions/` (0001–0010), each resolving a SPEC question — D-08 adds 0011.

### Integration Points
- `deploy/` is a new directory (does not exist yet).
- `README.md` is a stub to be fully replaced.
- No change expected to `src/sift/` for PKG-01 beyond an optional `--version` affordance.
</code_context>

<specifics>
## Specific Ideas

- The Quadlet story must make the loopback-guard interaction explicit and correct (D-06, corrected): `Network=host` + `http://127.0.0.1:<port>/v1` (loopback literal → guard-permitted, no override flag) — NOT `host.containers.internal`, which the literal-hostname guard rejects. This is the single most error-prone point of the deploy docs and is a named SPEC acceptance criterion.
- Vulkan is the recommended default backend for gfx1151 (SPEC calls it "the more robust default on this APU"); ROCm 7.2+ is the documented alternative.
</specifics>

<deferred>
## Deferred Ideas

- Publishing to PyPI or a container registry — own phase / backlog.
- Homebrew / AUR / Windows / macOS packaging — Fedora is the reference platform for v1.0.
- Release-automation / semantic-version-bump tooling — the v1.0 tag is a separate authorised release step.
- Bundling or serving models — explicitly out of scope per SPEC ("no model management").
- None of the above are blockers for PKG-01/PKG-02.
</deferred>

---

*Phase: 8-Packaging & Deploy*
*Context gathered: 2026-07-19*
