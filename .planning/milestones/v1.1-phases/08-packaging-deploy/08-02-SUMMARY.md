---
phase: 08-packaging-deploy
plan: 02
subsystem: packaging
tags: [packaging, deploy, quadlet, podman, ssrf-guard, adr]
requires:
  - sift-ssrf-guard          # src/sift/llm/client.py:_assert_local (Phase 3)
  - packaging-pytest-marker  # 08-01
provides:
  - quadlet-deploy-files
  - guard-clean-loopback-default
  - adr-0011-quadlet-loopback-guard
affects:
  - deploy/sift.container
  - deploy/llama-server.container.example
  - docs/decisions/0011-quadlet-loopback-guard.md
  - tests/test_packaging.py
tech-stack:
  added: []
  patterns:
    - "Guard-clean deploy default: Network=host + literal 127.0.0.1 base_urls, no --i-know-what-im-doing"
    - "Quadlet linting via the systemd podman-system-generator --dryrun (NOT podman quadlet install)"
    - "Graceful-skip integration test: pytest.skip when the generator binary is absent (D-07)"
key-files:
  created:
    - deploy/sift.container
    - deploy/llama-server.container.example
    - docs/decisions/0011-quadlet-loopback-guard.md
  modified:
    - tests/test_packaging.py
decisions:
  - "Deploy default ships Network=host + literal 127.0.0.1 (guard-clean); host.containers.internal is rejected by the DNS-free guard and documented as the anti-pattern in ADR 0011 (D-06 corrected)."
  - "ADR 0011 records the guard is DNS-free by design (anti-TOCTOU); the deploy adapts to the guard, altering _assert_local is out of scope."
  - "Guard-acceptability test imports the module-private _assert_local under a scoped `# pyright: ignore[reportPrivateUsage]` — the lock must exercise the real guard, not a stub."
metrics:
  duration: ~12m
  completed: 2026-07-19
status: complete
---

# Phase 8 Plan 02: PKG-02 Quadlet Deploy + Guard-Clean Loopback Summary

Ships the optional Podman Quadlet deploy files and locks the single load-bearing invariant of the phase: an in-container Sift reaches a host-side `llama-server` through the DNS-free SSRF guard (LLM-02) with **no** `--i-know-what-im-doing` override. The deploy default is `Network=host` + literal `127.0.0.1`, regression-locked by a guard-acceptability test, with the corrected mechanism recorded in ADR 0011.

## What was built

- **`deploy/sift.container`** (NEW, first file under `deploy/`): rootless Podman Quadlet unit with `Network=host` and two `Environment=SIFT_*_BASE_URL=http://127.0.0.1:<port>/v1` entries. `127.0.0.1` is `ip.is_loopback`, so `_assert_local` returns without raising — no break-glass. `Image=localhost/sift:latest` is a user-provided placeholder (a preceding comment notes image build/publish is out of scope for M8), plus `Volume=%h/.local/share/sift:/data:Z`, `[Service] Restart=on-failure`, `[Install] WantedBy=default.target`. British-English prose.
- **`deploy/llama-server.container.example`** (NEW): example Vulkan generation backend (`ghcr.io/ggml-org/llama.cpp:server-vulkan`, robust default on gfx1151 per SPEC §3), `PublishPort=8080:8080`, user-supplied model, and a header note that a SECOND `--embeddings` instance on `:8081` is required (generation + embeddings cannot share one server). Clearly marked as an example to adapt.
- **`docs/decisions/0011-quadlet-loopback-guard.md`** (NEW ADR, follows the 0010 template): records that `_assert_local` is DNS-free by design; `host.containers.internal` (D-06's original proposal) is therefore **rejected** (not `localhost`/`*.localhost`, not a literal IP); the deploy uses `Network=host` + `127.0.0.1` instead (backend-agnostic across pasta/slirp4netns); the `*.localhost` `AddHost=…:host-gateway` alias is the isolated-network alternative; the guard stays unchanged (out of scope). Cites PKG-02, D-06, SPEC §7/§8, and `src/sift/llm/client.py:54-84`.
- **PKG-02 tests appended to `tests/test_packaging.py`**:
  - *Test A — guard-acceptability lock* (always runs, no podman): parses every `SIFT_*_BASE_URL` from `deploy/sift.container`, calls `_assert_local(url, allow_public=False)` (asserts no raise), and pins each host to `127.0.0.1`. This is the regression lock against any future edit smuggling in a bare hostname.
  - *Test B — Quadlet dry-run* (graceful skip, D-07): resolves the systemd `podman-system-generator` (legacy `/usr/libexec/podman/quadlet` fallback); runs `--user --dryrun` with `QUADLET_UNIT_DIRS=deploy` and asserts returncode 0 + `sift` in stdout; `pytest.skip` when the generator is absent.

## Verification

- `uv run pytest -m packaging -k "guard or quadlet" tests/test_packaging.py -q` → 2 passed. Test B **ran** (not skipped) — the generator is present on this box and the units lint clean.
- `uv run pytest -m packaging -q` → 3 passed (includes 08-01's offline-install smoke test).
- `uv run pytest -q` (default suite) → 466 passed, 8 deselected — no regression.
- `uv run ruff check tests/test_packaging.py` → clean; `uv run pyright tests/test_packaging.py` → 0 errors.
- Task 1 automated check: both deploy base_urls resolve to host `127.0.0.1`, `Network=host` present, example publishes 8080 and mentions 8081, neither file contains a `--i-know-what-im-doing` token.
- Task 2 automated check: ADR 0011 starts `# ADR 0011`, has Context/Decision/Consequences, cites PKG-02/D-06/127.0.0.1/`src/sift/llm/client.py`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Reworded `sift.container` header to drop the literal `--i-know-what-im-doing` token**
- **Found during:** Task 1
- **Issue:** The explanatory header comment named the `--i-know-what-im-doing` override by its literal string, tripping the acceptance check "Neither file contains a `--i-know-what-im-doing` token".
- **Fix:** Reworded to "with no break-glass override needed" — same meaning, no forbidden literal.
- **Files modified:** deploy/sift.container
- **Commit:** 645f82e

**2. [Rule 3 - Blocking] Scoped `# pyright: ignore[reportPrivateUsage]` on the `_assert_local` import**
- **Found during:** Task 3
- **Issue:** The plan mandates importing the module-private `_assert_local` so the lock exercises the real guard. Under strict pyright this raises `reportPrivateUsage`.
- **Fix:** Scoped `# pyright: ignore[reportPrivateUsage]` on the import (the same suppression pattern 08-01 used for the `@app.callback`), with a comment explaining why the direct import is deliberate.
- **Files modified:** tests/test_packaging.py
- **Commit:** 40d2501

## Threat surface

Threat register dispositions honoured. T-08-01 (elevation/tampering via `deploy/sift.container` base_url) is **mitigated**: the shipped default is guard-clean (`Network=host` + literal `127.0.0.1`), Test A locks `_assert_local(allow_public=False)` no-raise on the shipped base_urls, ADR 0011 documents the DNS-free guard, and no break-glass override is baked into the deploy. T-08-04 (info disclosure via `deploy/*.container`) is **mitigated**: env values are localhost URLs only — no credentials or tokens — and the backend unit ships as `.example`, not an enabled unit. No new security-relevant surface beyond the threat register.

## Known Stubs

None. `Image=localhost/sift:latest` and the example image/model are documented user-supplied placeholders (image build/publish explicitly out of scope for M8), not stubs blocking the plan goal.

## Self-Check: PASSED
- deploy/sift.container — FOUND
- deploy/llama-server.container.example — FOUND
- docs/decisions/0011-quadlet-loopback-guard.md — FOUND
- tests/test_packaging.py — modified, FOUND
- Commit 645f82e (feat, Task 1) — FOUND
- Commit 5394991 (docs, Task 2) — FOUND
- Commit 40d2501 (test, Task 3) — FOUND
