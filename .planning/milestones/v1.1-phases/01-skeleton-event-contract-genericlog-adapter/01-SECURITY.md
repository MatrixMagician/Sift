---
phase: 1
slug: skeleton-event-contract-genericlog-adapter
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-07-16
---

# Phase 1 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| PyPI → local venv | Third-party code enters the build environment via `uv add` | Package code (supply chain) |
| Developer shell → CLI args | Untrusted argument strings enter the process | Case names, paths, flags |
| CLI args → filesystem | Case name and input dir drive path construction | Path components |
| Log file bytes → parser/store | Fully untrusted adversarial content enters parse and SQL layers | Arbitrary bytes |
| Compressed input → decompressor | Tiny input can expand enormously (bomb) | gz/zst/zip streams |
| Stored log content → terminal | Untrusted bytes echoed to the user's terminal by `sift show` | Control chars, escapes |
| config.toml / env → process | User-writable config drives paths and timezone lookups | Config values |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-01-SC | Tampering | PyPI installs (uv add) | high | mitigate | Human legitimacy checkpoint for all six [SUS]-flagged packages; exact versions pinned in `uv.lock` (present) | closed |
| T-01-05 | Information Disclosure | any module (network egress) | high | mitigate | No HTTP dependency in `pyproject.toml`; autouse socket guard (`tests/conftest.py:44-50`) fails any network use across all tests | closed |
| T-02-01 | Tampering | store.validate_case_name / case_db_path | high | mitigate | Strict allowlist (`src/sift/store.py:22`) + resolved-path containment check (`store.py:36` `is_relative_to`) | closed |
| T-02-02 | Tampering | store.py SQL layer | high | mitigate | store.py is single SQL owner; parameterised `?` placeholders only — the two f-string statements (`store.py:146,155`) interpolate the constant column list, never values | closed |
| T-02-03 | Denial of Service | genericlog parse memory | medium | mitigate | Streaming byte loop, no slurp; per-event caps `MAX_EVENT_LINES=256` / `MAX_EVENT_BYTES=65536` (`genericlog.py:38-39`) | closed |
| T-03-01 | Denial of Service | open_bytes + parse loop (decompression bomb) | medium | mitigate | Streaming decompression; per-event 64 KB/256-line caps; forced 64 KB split of newline-less runs; nothing written decompressed to disk (01-03-SUMMARY) | closed |
| T-03-02 | Tampering | record decoding (hostile encodings) | low | accept | errors-replace decoding strictly after byte offsets are fixed — malformed bytes cannot corrupt identity or coverage; render-side sanitisation covered by T-04-01 | closed |
| T-04-01 | Tampering/Spoofing | cli show rendering | medium | mitigate | `_sanitise` (`src/sift/cli.py:30`) strips control chars (C0+C1, except newline/tab) at render time; stored text stays verbatim | closed |
| T-05-01 | Repudiation | docs/decisions ADRs | low | accept | ADRs 0001–0003 present in `docs/decisions/` — decisions auditable in-repo | closed |
| T-04-02 | Tampering | config load (bad tz names, malformed toml) | low | mitigate | Pydantic validation + `ZoneInfo` construction at config time (`src/sift/config.py:35`); tomllib parse errors surface naming the file, never silent defaults | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-01 | T-03-02 | Hostile/invalid encodings decoded with errors-replace only after byte offsets are fixed; cannot corrupt event identity or parse coverage. Rendering side sanitised separately (T-04-01). | plan 01-03 (user-approved plan) | 2026-07-16 |
| AR-02 | T-05-01 | Repudiation of design decisions mitigated by the ADRs themselves; no further control needed. | plan 01-05 (user-approved plan) | 2026-07-16 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-16 | 10 | 10 | 0 | gsd-secure-phase (L1 grep verification, short-circuit — plan-time register, all mitigations located in implementation) |

Post-execution code review (01-REVIEW.md / 01-REVIEW-FIX.md) independently found and fixed 2 Critical + 7 Warning security findings (terminal injection, bidi/zero-width spoofing, symlink escape, UTF-16 alignment, silent overwrite, corrupt-archive handling) — all verified green before this audit.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-16
