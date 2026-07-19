---
phase: 8
reviewers: [llama_cpp]
reviewers_dropped: [lemonade, ollama, claude]
generated: 2026-07-19
note: >
  Local prompt-only reviewers (no repo file access) — advisory second opinion,
  not a source-grounded authority check. The authoritative source-grounded pass
  was gsd-plan-checker (VERIFICATION PASSED, 0 blockers). Orchestrator verified
  each actionable finding below against the actual plan text before recording it.
---

# Phase 8 — Cross-AI Plan Review

## Reviewer availability

| Reviewer | Model | Status |
|----------|-------|--------|
| llama.cpp (:8080) | Qwen3.6-35B-A3B-UD-Q4_K_M | ✓ reviewed |
| Lemonade (:13305) | Qwen3.5-27B-GGUF | ✗ dropped — `llama-server request failed` (model not resident / prompt exceeded loaded context) |
| ollama (:11434) | llama3.1:8b | — skipped (low capability for a ~22K-token plan review) |
| claude CLI | — | — skipped (self; no independence — orchestrator runs inside Claude Code) |

External CLIs (gemini, codex, coderabbit, opencode, qwen, cursor, agy): none installed.

---

## llama.cpp (Qwen3.6-35B) Review

> Prompt-only reviewer — could not open the repo; file-dependent claims are its inferences from the plan text.

### Summary
The three plans comprehensively address Phase 8's requirements (PKG-01, PKG-02, D-09) with a strong grasp of the project's constraints, particularly the DNS-free SSRF guard correction. They correctly separate concerns across waves, enforce offline invariants, and include appropriate automated and human verification gates. Primary gaps: minor scope creep around container image references, a deviation from the exact `uv tool install` command in the smoke test, and a potential runtime crash in the `--version` affordance under non-standard installs. Overall risk: **MEDIUM**, easily mitigated.

### Strengths
- Correctly implements the load-bearing D-06 correction (`Network=host` + `127.0.0.1`, not `host.containers.internal`).
- Rigorous offline enforcement on every `uv` subprocess (`--offline`, `UV_OFFLINE=1`, `--no-index --find-links`).
- Clean wave/dependency ordering (08-01 harness → 08-02 deploy → 08-03 docs).
- Graceful CI degradation for the Quadlet dry-run (D-07).
- Clear automated + human-verify acceptance criteria.

### Concerns (reviewer severity → orchestrator verdict)
- **MEDIUM → CONFIRMED (substantive):** the smoke test uses `uv venv` + `uv pip install`, but PKG-01 names **`uv tool install`**. The test proves wheel-install-and-run, not the `uv tool install` tool-dir/PATH code path the requirement specifies. *(Verified: 08-01-PLAN.md Task 2.)*
- **LOW → CONFIRMED:** `sift --version` uses bare `importlib.metadata.version("sift")` → `PackageNotFoundError` if run from an uninstalled checkout. The plan's own gate uses `uv run` (installed), so it won't fail the gate, but a fallback is cheap hardening. *(Verified: 08-01-PLAN.md Task 1, line 66.)*
- **MEDIUM → CONFIRMED (minor):** `Image=localhost/sift:latest` is a placeholder; a Quadlet requires an `Image=`, but image build/publish is deferred scope — a clarifying comment avoids implying the user must build/pull an image. *(Verified: 08-02-PLAN.md Task 1, line 73.)*
- **LOW → REASONABLE:** README should state the inference backend (llama-server / Lemonade) is a separate, user-managed component. *(08-03 D-09 covers backend setup; an explicit "prerequisites" note strengthens it.)*
- **OPEN QUESTION → ALREADY KNOWN:** does `uv build --offline` succeed on a cold cache? Matches RESEARCH Assumption A1 + the plan-checker's INFO note; the plan documents the `--find-links dist/` vendored-wheel fallback.

### Suggestions (from reviewer)
- Use `uv tool install --offline` (with `UV_TOOL_DIR`/`UV_TOOL_BIN_DIR` → tmp_path) to match PKG-01 exactly and validate PATH injection.
- Wrap `importlib.metadata.version("sift")` in try/except → fallback (`"0.1.0"` / `"unknown"`).
- Replace/annotate `Image=localhost/sift:latest` with an "out-of-scope for M8, user-provided" comment.
- Add a README "Prerequisites" note that the backend is user-managed, with links.
- Assert `$PATH` resolves `sift` in the smoke test, not just that the binary runs.

### Overall Risk: MEDIUM (reviewer) — non-blocking refinements per orchestrator verification.

---

## Orchestrator Consensus

Only one independent reviewer completed, and it is prompt-only (no repo access), so this review is a **second opinion, not an authority check** — the source-grounded gate was gsd-plan-checker (PASSED, 0 blockers) plus the requirements/decision coverage gates (all green).

**Actionable, worth incorporating (all refinements to already-passing plans, none blocking):**
1. **[MEDIUM] 08-01** — make the smoke test exercise `uv tool install --offline` (tool-dir redirected to tmp_path) so it proves PKG-01's exact `uv tool install` claim, not just an equivalent wheel install.
2. **[LOW] 08-01** — guard `sift --version` against `PackageNotFoundError` (try/except fallback).
3. **[LOW] 08-02** — annotate the `Image=` placeholder as user-provided / out-of-scope for M8.
4. **[LOW] 08-03** — add a README "Prerequisites: inference backend is user-managed" note.

**Not actionable:** the cold-cache open question (already documented with a fallback).
