---
phase: 08-packaging-deploy
verified: 2026-07-19T00:00:00Z
status: passed
score: 11/11 must-haves verified
behavior_unverified: 0
overrides_applied: 0
requirements_verified: [PKG-01, PKG-02]
---

# Phase 8: Packaging & Deploy Verification Report

**Phase Goal:** A stranger on Fedora can go from clean checkout to first triage report using only the README
**Verified:** 2026-07-19
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

The phase goal is achieved. The three roadmap success criteria and all eleven
plan-level must-have truths hold in the codebase, verified by running the real
quality gates and the opt-in packaging suite (not by trusting SUMMARY.md). The
load-bearing behaviours were exercised, not merely grepped: the offline
`uv tool install` proof actually builds a wheel, installs it offline, and runs
the console script; the SSRF guard was called live against the shipped deploy
addresses; the Quadlet generator dry-run ran clean on this box.

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | (SC1) `uv build` + offline `uv tool install` yields a working `sift` console script (`--help`/`--version`/`new`), pipx-compatible | ✓ VERIFIED | `test_offline_wheel_install_yields_working_console_script` PASSED (real subprocess build+install+run into hermetic UV_TOOL_DIR/UV_TOOL_BIN_DIR). `[project.scripts] sift = "sift.cli:app"` + `uv_build` backend present in pyproject.toml; `from sift.cli import app` imports cleanly. `uv run sift --version` → `0.1.0` |
| 2 | Build + install are fully offline — zero PyPI/index fetch across the uv/sift subprocess boundary | ✓ VERIFIED | Every uv subprocess carries `--offline` + `UV_OFFLINE=1`; test passed with warm cache, no `--no-index` (documented deviation, cache-backed resolution). Zero-egress invariant preserved |
| 3 | Packaging test excluded from the default fast suite; runs only via `-m packaging` | ✓ VERIFIED | `addopts = "-m 'not perf and not live and not packaging'"` in pyproject.toml; default `uv run pytest -q` → 468 passed, **8 deselected**; `-m packaging` → 3 passed |
| 4 | (SC2) `deploy/sift.container` + `deploy/llama-server.container.example` ship under `deploy/` matching SPEC §7 | ✓ VERIFIED | Both files exist and are substantive; `Environment=` prefix syntax correct; example references Vulkan image, publishes 8080, documents second `--embeddings` instance on 8081 |
| 5 | Shipped `deploy/sift.container` base_urls pass `_assert_local(allow_public=False)` with no `--i-know-what-im-doing` | ✓ VERIFIED | `test_deploy_base_urls_are_guard_clean` PASSED; live call of the real `_assert_local` accepts `http://127.0.0.1:8080/v1` and `:8081/v1` without raising; `Network=host` present; no break-glass token in either file |
| 6 | (SC2) Quadlet generator dry-run validates where present, skips gracefully where absent (D-07) | ✓ VERIFIED | `test_quadlet_generator_dry_run_validates_or_skips` PASSED — ran (not skipped) against the real `podman-system-generator --user --dryrun`, returncode 0, stdout references `sift` |
| 7 | (SC2) ADR 0011 records the DNS-free guard / literal-loopback decision and the `host.containers.internal` interaction | ✓ VERIFIED | `docs/decisions/0011-quadlet-loopback-guard.md` present, ADR format, cites PKG-02/D-06/`src/sift/llm/client.py`. Live check confirms guard rejects `host.containers.internal`, accepts `127.0.0.1` — matches the ADR |
| 8 | (SC3) README quickstart runs install → backend → `sift doctor` → new/ingest/analyze/report → pdf extra, in order (D-09) | ✓ VERIFIED | README.md (181 lines) follows the exact section order; `sift show` arg order corrected to `sift show my-incident clusters` matching the real CLI signature `sift show {case} {what}` |
| 9 | (SC3) README documents both backends: llama.cpp (Vulkan default / ROCm 7.2+ on gfx1151) and Lemonade (:13305, embeddings-recipe caveat) | ✓ VERIFIED | README §2 Options A/B: Vulkan default + ROCm 7.2+ alternative; Lemonade port 13305 explicit; ONNX/OGA-can't-embed caveat with `sift doctor` round-trip pointer |
| 10 | README documents the two-instance setup naming both env vars | ✓ VERIFIED | Both `SIFT_GENERATION_BASE_URL` and `SIFT_EMBEDDINGS_BASE_URL` named; `--embeddings` embedding-only rule stated; matches `src/sift/config.py` env-var names |
| 11 | README documents the `sift[pdf]` extra + Fedora `dnf install pango`; core install stays system-dep-free | ✓ VERIFIED | README §5: `uv tool install '.[pdf]'` + `sudo dnf install pango`; `[project.optional-dependencies] pdf` present in pyproject.toml; core deps carry no system-dep requirement |

**Score:** 11/11 truths verified (0 present, behaviour-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `pyproject.toml` | `packaging` marker + addopts exclusion; version 0.1.0; scripts/uv_build carried | ✓ VERIFIED | Marker registered; addopts excludes packaging; `version = "0.1.0"`; `[project.scripts] sift = "sift.cli:app"` |
| `tests/test_packaging.py` | offline install smoke + guard lock + quadlet dry-run | ✓ VERIFIED | 3 tests, all pass under `-m packaging`; imports real `_assert_local` |
| `src/sift/cli.py` `--version` | eager callback printing 0.1.0 | ✓ VERIFIED | `uv run sift --version` → `0.1.0`; `importlib.metadata` with `PackageNotFoundError` fallback |
| `deploy/sift.container` | Network=host + loopback-literal base_urls | ✓ VERIFIED | Guard-clean; regression-locked by Test A |
| `deploy/llama-server.container.example` | Vulkan default, second `--embeddings` noted | ✓ VERIFIED | Ports 8080/8081 documented |
| `docs/decisions/0011-quadlet-loopback-guard.md` | ADR recording D-06 correction | ✓ VERIFIED | Full Context/Decision/Consequences; cites guard source |
| `README.md` | D-09 quickstart, British English | ✓ VERIFIED | Rewritten from 2-line stub; human-walked end-to-end |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `pyproject.toml` `[project.scripts]` | `sift.cli:app` | console-script entry point | ✓ WIRED | `from sift.cli import app` imports; installed `bin/sift` runs in the packaging test |
| `deploy/sift.container` env | `_assert_local` | literal `127.0.0.1` accepted by DNS-free guard | ✓ WIRED | Live call returns without raise; Test A locks it |
| `tests/test_packaging.py` | `sift.llm.client._assert_local` | direct import of the real guard | ✓ WIRED | Not a stub — exercises production guard |
| README env vars | `src/sift/config.py` | `SIFT_GENERATION_BASE_URL` / `SIFT_EMBEDDINGS_BASE_URL` | ✓ WIRED | Names match config mapping |

### Behavioural Spot-Checks

| Behaviour | Command | Result | Status |
| --------- | ------- | ------ | ------ |
| Offline wheel install yields runnable console script | `uv run pytest -m packaging` | 3 passed | ✓ PASS |
| `sift --version` prints package version | `uv run sift --version` | `0.1.0` | ✓ PASS |
| Guard accepts shipped loopback, rejects magic-DNS | live `_assert_local` calls | 127.0.0.1 accepted; host.containers.internal rejected | ✓ PASS |
| Quadlet units lint clean | `podman-system-generator --user --dryrun` | returncode 0, references `sift` | ✓ PASS |
| README `sift show` matches CLI | `uv run sift show --help` | `{case} {what}` order matches README | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| PKG-01 | 08-01, 08-03 | `uv tool install` from clean checkout yields a working `sift` (pipx-compatible) | ✓ SATISFIED | Offline install smoke test PASSED; console-script wiring real; README documents install path incl. pipx |
| PKG-02 | 08-02, 08-03 | Optional Podman Quadlet deployment files with llama-server example, gfx1151 Vulkan/ROCm docs | ✓ SATISFIED | Deploy files ship; guard-clean; ADR 0011; Quadlet dry-run clean; README backend + deploy pointer |

Both requirement IDs declared in the phase plans are present in REQUIREMENTS.md and
marked Complete in the traceability table. No orphaned or unclaimed requirements
for Phase 8.

### Quality Gate State (independently re-run)

| Gate | Result |
| ---- | ------ |
| `uv run ruff check` | All checks passed! (exit 0) |
| `uv run pyright` | 0 errors, 0 warnings, 0 informations (exit 0) |
| `uv run pytest -q` (default) | 468 passed, 8 deselected (exit 0) |
| `uv run pytest -m packaging` | 3 passed (exit 0) |

### Commit Verification

All ten commits referenced across the three SUMMARYs exist in git history:
`a305520`, `98208c3` (08-01); `645f82e`, `5394991`, `40d2501` (08-02);
`0ef3889`, `cf97381`, `f1502a6` (08-03 + walkthrough); `35874b5`, `0c27499`
(embedding-overflow fix). The embedding fix is real in the code:
`src/sift/config.py:50` (`max_input_chars: int = 8000`, env
`SIFT_EMBEDDINGS_MAX_INPUT_CHARS`) and `src/sift/llm/client.py` (input
truncation at `text[:self._max_input_chars]` + actionable over-context error).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `deploy/sift.container` | 31 | `Exec=--help` on the container unit | ℹ️ Info | The shipped unit runs `sift --help` as its exec — a placeholder an operator adapts. The image is explicitly user-provided (build/publish out of M8 scope) and PKG-02 deployment is optional, so this is a template default, not a goal-blocking stub. Consider documenting the intended real Exec in a follow-up. |

No debt markers (TBD/FIXME/XXX) in phase-modified files. No stubs blocking the
goal. The `Image=localhost/sift:latest` and example image/model are documented
user-supplied placeholders, not stubs.

### Human Verification Required

None outstanding. The 08-03 blocking human-verify checkpoint was resolved by the
user walking the quickstart end-to-end on a real Fedora box against a 62 MB
MicroStrategy `DSSErrors.log` (178,925 events): install ✓, doctor ✓, new/ingest ✓
(99.8% coverage), analyze ✓ (524 clusters), report ✓. The walkthrough surfaced
and fixed two real defects (README `sift show` arg order; embedding-overflow bug
in analyze), both verified present in the codebase.

### Gaps Summary

None. All three roadmap success criteria and all eleven plan-level must-have
truths are verified against the codebase and by running the real gates and
packaging suite. The phase goal — a stranger on Fedora can go from clean checkout
to first triage report using only the README — is achieved, with the install
path proven offline-installable, the optional deploy files guard-clean and
lint-clean, and the README validated by a real end-to-end human walkthrough.

This is the final phase of milestone v1.0; all 44 v1 requirements are now
Complete in the traceability table.

---

_Verified: 2026-07-19_
_Verifier: Claude (gsd-verifier)_
