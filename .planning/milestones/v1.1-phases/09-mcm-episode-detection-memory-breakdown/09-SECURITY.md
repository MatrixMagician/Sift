---
phase: 9
slug: mcm-episode-detection-memory-breakdown
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on (high) severity
threats_open: 0
asvs_level: 1
created: 2026-07-19
---

# Phase 9 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Verified in verify-mitigations mode against the implemented code (READ-ONLY
> audit). Config: ASVS L1, block_on = high. No high-severity threats exist, so
> nothing blocks; all mitigations independently confirmed in source.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| stored dsserrors `event.raw` -> `pipeline/mcm.py` regex parser | Malformed/adversarial memory-dump lines and integer figures cross here; the analyser must parse defensively and never hang or crash. Input already bounded by the adapter's 256-line / 64 KB event caps (`adapters/dsserrors.py:47-48`). | Untrusted production log text (real host/SID/OID tokens, memory figures) |
| `pipeline/mcm.py` -> caller (Phase 10/11, tests) | Pure return of typed Pydantic models; no side effects, no I/O, no egress. | Typed `McmEpisode` / `MemoryBreakdown` models |
| committed fixture -> test-time `DsserrorsAdapter` | Trusted local test data authored in-repo; no runtime parse of external/untrusted input in the RED plan. Tests run under the conftest zero-network guard. | Local dev fixture text |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-09-02-01 | Denial of Service (ReDoS) | `DETAIL_LINE_RE` / `ABBREV_LINE_RE` on malformed dump lines | medium | mitigate | Both patterns `^`-anchored with required `$` terminator and non-nested (single) quantifiers, mirroring `adapters/dsserrors.py:50`; reference 60-line block cap retained. Verified `mcm.py:58` (`^\t*(.+?)\((GB\|MB\|KB)\):\s*(-?\d+)\s*$`), `mcm.py:64-67` (`^([A-Za-z][A-Za-z0-9 /\-]*?)\s*=\s*(...)\s*(?:\(...\))?\s*$`), 60-line cap at `mcm.py:223-224`. Input bounded by adapter 256-line/64 KB caps. | closed |
| T-09-02-02 | Denial of Service (availability) | `parse_detail_block` / `parse_abbrev_block` on absent/garbled block | medium | mitigate | Tolerate-absence (D-03/D-07): both parsers return `(data, idx)` and never raise; absent detail -> EMPTY `MemoryBreakdown` (`mcm.py:418-425`), open episode at EOF -> `open_truncated=True` (`mcm.py:350-362`), missing label -> `_get` returns `None` (`mcm.py:89-99`), absent marker -> no signal (`mcm.py:383-384`). No `raise` statements in the module; loops always progress or break (bounded by `len(lines)` + 60-line cap). | closed |
| T-09-02-03 | Tampering (integer parse) | AvailableMCM / HWM / Size / memory figures | low | mitigate | Figures captured via `-?\d+` / `\d+`-anchored groups (`mcm.py:44-47,58`) into Python ints (arbitrary precision — no overflow); the only `int()` is `mcm.py:217`, fed to `to_mb()` -> `float` stored in `raw_map`. Never used for allocation or indexing (all indices are enumerate/loop-derived stream positions, not parsed figures). Non-match -> value simply absent. | closed |
| T-09-02-04 | Information disclosure (egress) | analyser egress path | low | accept | Independently confirmed zero-egress: no `httpx`/`requests`/`socket`/`subprocess`/`urllib`/`open(`/`.write(` in the module; imports are `re`, `dataclasses`, `typing`, `pydantic` only (`mcm.py:26-32`). Tests run under conftest `_no_network` guard (`tests/conftest.py:35-60`). No egress path exists. | closed |
| T-09-02-SC | Tampering (supply chain) | pip/npm/cargo installs | n/a | accept | Plan installs NO packages — pure stdlib `re` + already-vendored Pydantic. No supply-chain surface. | closed |
| T-09-01-01 | Information disclosure | `tests/fixtures/mcm/hartford_deny_slice.log` (real host/SID/OID tokens) | low | accept | Local dev fixture from real diagnostics (present, 10.8 KB); report redaction (REPT-05) is explicitly v2/out of scope. No egress — tests run under the conftest network guard. Accepted for a private-repo dev fixture. | closed |
| T-09-01-02 | Tampering | `docs/reference/analyze_dss8.py` (vendored) | low | accept | Confirmed non-executed and never imported: `analyze_dss8` appears only in provenance comments/docstrings across `src/` and `tests/` (no `import`). Provenance-only; cannot affect runtime behaviour. | closed |
| T-09-01-SC | Tampering (supply chain) | pip/npm/cargo installs | n/a | accept | RED plan installs NO packages (pytest already present, no new deps). No supply-chain surface. | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above block_on=high count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-09-01 | T-09-02-04 | Analyser makes zero network/subprocess/file-write/LLM calls; only `llm/` talks HTTP. Verified by grep — no egress path exists. | O Hingst | 2026-07-19 |
| AR-09-02 | T-09-02-SC / T-09-01-SC | Neither plan installs any package (stdlib `re` + already-vendored Pydantic; pytest already present). No supply-chain surface. | O Hingst | 2026-07-19 |
| AR-09-03 | T-09-01-01 | `hartford_deny_slice.log` is a private-repo dev fixture from real diagnostics; report redaction deferred to v2; no test egress under conftest guard. | O Hingst | 2026-07-19 |
| AR-09-04 | T-09-01-02 | Vendored `analyze_dss8.py` is provenance-only — never imported or executed. | O Hingst | 2026-07-19 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-19 | 8 | 8 | 0 | security-auditor (verify-mitigations, ASVS L1, block_on=high) |

**Unregistered flags:** none. `09-02-SUMMARY.md ## Threat Flags` declares "None"; `09-01-SUMMARY.md` has no Threat Flags section. No new attack surface appeared during implementation.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-19
