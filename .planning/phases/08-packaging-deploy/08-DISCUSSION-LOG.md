# Phase 8: Packaging & Deploy - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-19
**Phase:** 8-Packaging & Deploy
**Areas discussed:** Distribution & install, Install verification, Podman Quadlet deployment, README quickstart
**Mode:** `--auto` (recommended option auto-selected for each area; grounded in SPEC.md, ADRs, and existing code)

---

## Distribution & install

| Option | Description | Selected |
|--------|-------------|----------|
| Clean-checkout + VCS `uv tool install`, no PyPI | Install from checkout / `git+https`; no registry publish | ✓ |
| Publish to PyPI | Full public distribution | |

| Option | Description | Selected |
|--------|-------------|----------|
| Bump version to 1.0.0 this phase | Align package version with the v1.0 milestone now | |
| Leave 0.1.0; release/tag separately authorised | Version bump is a distinct release action | ✓ |

**User's choice:** Auto-selected recommended defaults.
**Notes:** SPEC M8 criterion is explicitly "from a clean checkout" → PyPI is scope creep, deferred. Version bump is a separate authorised release step consistent with the project's local-branch-only convention; does not block PKG-01.

---

## Install verification (PKG-01 proof)

| Option | Description | Selected |
|--------|-------------|----------|
| Offline wheel build + isolated install + exercise real `sift` script | `uv build` → install into throwaway env → assert console script runs; opt-in marker | ✓ |
| Trust pyproject metadata / manual-only check | No automated proof | |

**User's choice:** Auto-selected recommended default.
**Notes:** Must stay fully offline (zero-network-in-tests invariant); reuses the existing `perf`/`live` opt-in marker pattern so the default suite stays fast.

---

## Podman Quadlet deployment (PKG-02)

| Option | Description | Selected |
|--------|-------------|----------|
| `host.containers.internal` (RFC1918, guard-permitted, no override) | Container reaches host endpoint via an address `_assert_local` already allows | ✓ |
| Document `--i-know-what-im-doing` workaround | Tell users to bypass the guard | |

| Option | Description | Selected |
|--------|-------------|----------|
| Hard CI gate on `podman quadlet` dry-run | Fail CI if validation doesn't pass | |
| Graceful skip when podman absent; doc + best-effort dry-run | Non-blocking validation | ✓ |

**User's choice:** Auto-selected recommended defaults.
**Notes:** Confirmed against `src/sift/llm/client.py:54` + `test_assert_local_accepts_loopback_and_rfc1918` — RFC1918 is permitted, so no override flag is needed from inside the Quadlet. Podman may be absent on CI runners, so validation cannot be a hard gate.

---

## README quickstart

| Option | Description | Selected |
|--------|-------------|----------|
| Vulkan default, ROCm 7.2+ alternative; Lemonade recipe caveat documented | Two backend paths, Vulkan as robust default for gfx1151 | ✓ |
| ROCm-first | Lead with ROCm | |

**User's choice:** Auto-selected recommended default.
**Notes:** SPEC calls Vulkan "the more robust default on this APU". README covers install → backend setup (llama.cpp + Lemonade, two-instance embeddings, ONNX/OGA embeddings caveat) → `sift doctor` → first-case walkthrough → optional `sift[pdf]` + pango.

## Claude's Discretion

- Exact pytest marker name for the packaging smoke test.
- README section ordering and prose.
- Whether `llama-server.container.example` uses Vulkan or ROCm in its example (recommend Vulkan).
- Optional `sift --version` affordance if not already present.

## Deferred Ideas

- PyPI / container-registry publishing.
- Homebrew / AUR / Windows / macOS packaging.
- Release-automation / version-bump tooling.
- Model bundling/serving (out of scope per SPEC).
