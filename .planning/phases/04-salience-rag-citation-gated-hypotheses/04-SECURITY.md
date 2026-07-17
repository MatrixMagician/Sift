---
phase: 4
slug: salience-rag-citation-gated-hypotheses
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on (high) severity
threats_open: 0
asvs_level: 1
created: 2026-07-17
---

# Phase 4 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Register authored at plan time (all six 04-0N-PLAN.md carry a `<threat_model>` block); mitigations verified at ASVS L1 grep depth.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| ingested log text → triage prompt | Exemplar excerpts (attacker-influenced log content) flow into the generation prompt | Untrusted log text |
| client → local inference server | The only outbound HTTP in Sift; the request body carries a schema constraint (`response_format`) | Prompt + schema |
| server body → chat return | Local llama-server / Lemonade response body is untrusted even on loopback (reasoning models return malformed/empty shapes); parsed defensively in `client.chat()` | Untrusted model JSON |
| model output → citation gate → store | Untrusted hypotheses (titles, narratives, cited ids) are validated, gated, and persisted | Untrusted LLM text |
| shared case.db → read path | A `case.db` can be tampered between runs; `query_hypotheses` treats every column as untrusted | Untrusted persisted rows |
| stored aggregates → salience maths | Cluster/TemplateGroup timestamps and counts come from a possibly-tampered `case.db` | Untrusted numeric aggregates |
| persisted model text → terminal | `sift show hypotheses` / `analyze` renders untrusted model titles/narratives/ids to the operator's terminal | Untrusted text → TTY |
| CLI flags → inference client | `analyze` constructs the SSRF-guarded client; `--i-know-what-im-doing` is the only bypass | Endpoint config |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-04-01 | Tampering (prompt injection) | `triage.md` / `_assemble` | high | mitigate | `triage.md` instructs the model to treat every excerpt as untrusted data, never instructions (`src/sift/prompts/triage.md:10`); citation gate holds regardless of model compliance | closed |
| T-04-02 | Spoofing (hallucinated ids) | `_citation_gate` / exit-code surfacing | high | mitigate | cited ⊆ prompted ⊆ store enforced against `prompted_ids`; regenerate once then `citations_valid=false` + degraded (exit 3, FLAGGED) — never silently accepted (`src/sift/pipeline/hypothesise.py:307`) | closed |
| T-04-03 | Tampering | `show hypotheses` render / `analyze` stdout | medium | mitigate | Whole-line `_sanitise` on every DB/model-sourced line; untrusted text never enters a rich renderable; persist verbatim, sanitise at render only | closed |
| T-04-04 | DoS / Tampering | chat response parse / `_validate` | medium | mitigate | Defensive `_json_object` + `_MAX_CONTENT_CHARS` cap in client; Pydantic `extra="forbid"` validate; malformed output degrades, never crashes | closed |
| T-04-05 | Tampering (SQLi) | `store.replace_hypotheses` INSERT | high | mitigate | Parameterised `?` binds only; `_HYP_COLUMNS` is a module constant — no model value reaches SQL text (`src/sift/store.py:288,826`) | closed |
| T-04-06 | Information disclosure | outbound chat request / `analyze` client construction | high | mitigate | `_assert_local` SSRF guard at `InferenceClient` construction (`src/sift/llm/client.py:54,174-175`); Phase 4 opens no new endpoint or egress path; refusal maps to exit 1 | closed |
| T-04-07 | DoS | salience burstiness / span maths | low | mitigate | Clamp spans `max(span, _SPAN_FLOOR)`; missing/degenerate timestamps give neutral features — no unbounded or divide-by-zero maths | closed |
| T-04-08 | Tampering | `query_hypotheses` JSON list columns | medium | mitigate | WR-01 defensive coercion (wrap non-list, `str()` each element); render-time `_sanitise` strips hostile bytes | closed |
| T-04-09 | Tampering | severity ordering | low | mitigate | Frozen `_SEVERITY_RANK` dict, never lexicographic; out-of-vocab severity defaults to rank 0 — never reorders spuriously | closed |
| T-04-10 | Tampering | constraint field misuse | low | mitigate | Send only `response_format`, never also `grammar` (both is a llama.cpp hard error); caller builds a single self-contained schema | closed |
| T-04-11 | Tampering | atomic persistence | medium | mitigate | All writes inside one `store.transaction()` — a mid-generation/persist failure rolls back to zero hypotheses (no partial state) | closed |
| T-04-06-D | Denial of Service | `hypothesise()` handler / `client.chat()` | high | mitigate | `except (httpx.HTTPError, ValueError)` maps a malformed/empty 200 body to a clean `failed` Outcome instead of an uncaught traceback (`src/sift/pipeline/hypothesise.py:310`) — closes G1 | closed |
| T-04-06-T | Tampering | `client.chat()` response parsing | medium | mitigate | Empty/whitespace-only content normalised to a malformed-response `ValueError` at the shared boundary, unified with existing no-choices/absent-content guards; content length-capped | closed |
| T-04-06-I | Information Disclosure | failed-Outcome persistence | low | accept | A failed run persists nothing — no raw server body written to the store; whole-line `_sanitise` still covers render | closed |
| T-04-SC | Tampering (supply chain) | package installs (plans 01–05) | low | accept | No package installs in Phase 4 — all deps already pinned in `uv.lock`; RESEARCH Package Legitimacy Audit: none added | closed |
| T-04-06-SC | Tampering (supply chain) | package installs (plan 06) | low | accept | No new dependencies added (boring-tech constraint); no installs in the gap-closure plan | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above `high` count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-04-01 | T-04-SC | No package installs in Phase 4 (plans 01–05); all deps pinned in `uv.lock` — nothing to legitimacy-check | O Hingst | 2026-07-17 |
| AR-04-02 | T-04-06-SC | No new dependencies in the 04-06 gap-closure plan — boring-tech constraint honoured | O Hingst | 2026-07-17 |
| AR-04-03 | T-04-06-I | A failed run persists nothing; no raw server body reaches the store — residual info-disclosure risk is negligible | O Hingst | 2026-07-17 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-17 | 16 | 16 | 0 | gsd-secure-phase (L1 grep-depth, register authored at plan time) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-17
