---
phase: 02
slug: case-store-template-dedup
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-07-17
---

# Phase 02 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

Register origin: authored at plan time (all four PLAN.md files carried a `<threat_model>` block). Auditor mode: verify declared mitigations exist (no new-threat scan). ASVS L1, block_on = high.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| stored/tampered case.db → reader | a shared or tampered `case.db` is untrusted input to zstd decompression and every TEXT column flows to the terminal | attacker-controlled bytes (raw event text, templates, exemplar ids) |
| log bytes → mask regex | fully hostile log content enters the masking regex and template strings | untrusted file content |
| template strings / DB fields → operator terminal | masked templates, event rows and exemplar text render to the operator's terminal | attacker-controlled bytes (ESC/CSI/bidi) |
| --filter values → SQL layer | user- or script-supplied filter values flow toward query construction | user input |
| input bundle → write path | a truncated/corrupt archive must not corrupt the store's accounting record | untrusted archive content |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-02-01 | DoS | store.py `_decode_raw` | high | mitigate | `_MAX_RAW_BYTES = 128 MiB` cap on `_DCTX.decompress(..., max_output_size=...)` (store.py:25,48); sole raw-decode path (store.py:356) | closed |
| T-02-02 | Tampering/Spoofing | cli.py `show clusters` | high | mitigate | whole line wrapped `print(_sanitise(f"…"))` (cli.py:466-472); `_sanitise` strips C0/DEL/C1/Cf (cli.py:42-61) | closed |
| T-02-03 | DoS | dedup.py mask regex | medium | mitigate | single `re.VERBOSE` alternation, linear branches, anchored+bounded bare-hex lookaheads (dedup.py:27-40) | closed |
| T-02-04 | Tampering | store.py `template_groups` SQL | high | mitigate | `_TEMPLATE_GROUP_COLUMNS` module constant; INSERT/SELECT column lists constant, values `?`-bound (store.py:154,407-408,435-436) | closed |
| T-02-05 | DoS | cli.py ingest memory | medium | mitigate | `itertools.batched(..., 5000)` streaming, no whole-file materialisation (cli.py:14,262) | closed |
| T-02-06 | Tampering/Spoofing | rich Progress renderables | medium | mitigate | static progress description (cli.py:206,214); filenames never enter rich markup, only `_sanitise`d stdout | closed |
| T-02-07 | Tampering | WAL sidecars | low | mitigate | `store.close()` checkpoints WAL on all three CLI paths (store.py:475-476; cli.py:124,146,488) | closed |
| T-02-08 | Tampering | store.py filtered queries | high | mitigate | key allowlist → fixed snippet dicts using `instr(...) > 0` not LIKE; unknown key → `ValueError` before SQL; values `?`-bound (store.py:164-176,199-208) | closed |
| T-02-09 | Tampering/Spoofing | cli.py show render + error echoes | medium | mitigate | `_sanitise` on echoed filter errors (cli.py:444) and every rendered field (cli.py:466-485) | closed |
| T-02-10 | DoS | show events on large cases | low | mitigate | `iter_event_rows` SELECTs 6 columns only, streams `for row in cursor` (store.py:388-397; cli.py:478); no raw/zstd/Event hydration | closed |
| T-02-11 | Tampering | cli.py show render — all DB fields (WR-01) | high | mitigate | whole-line `_sanitise` on both paths (cli.py:466-472,482-485); non-list exemplar JSON guard (store.py:447-459) | closed |
| T-02-12 | Tampering | store.py write-path accounting (CR-01) | high | mitigate | per-file `savepoint()` (store.py:276-300) wrapping the per-file body (cli.py:239), nested in the outer `BEGIN IMMEDIATE` (cli.py:217) — a failed file contributes zero rows | closed |
| T-02-13 | Tampering | savepoint SQL identifier | low | mitigate | savepoint name is module constant `_SAVEPOINT_INGEST_FILE` (store.py:56,277), never user data | closed |
| T-02-14 | DoS | show on corrupt/read-only case.db (WR-02) | low | mitigate | `_case_store` catches `sqlite3.Error` → loud exit 1, no traceback, sanitised bytes (cli.py:74-81) | closed |
| T-02-SC | Tampering (supply-chain) | package installs | low | accept | no new packages this phase; `rich` promoted transitive→explicit (already in tree). See Accepted Risks Log | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-02-SC | T-02-SC | No new packages entered the environment this phase; `rich` was promoted from a transitive (typer) dependency to explicit, versions already pinned in `uv.lock` (Phase 1 checkpoint). No new supply-chain surface. | O Hingst | 2026-07-17 |
| AR-02-WR07 | T-02-12 | WR-07: a disk-full `SQLITE_FULL`/`IOERR` mid-ingest triggers SQLite auto-rollback that destroys the per-file SAVEPOINTs, weakening T-02-12's atomicity guarantee **under disk-full conditions only**. Accepted as a known limitation and carried forward to Phase 3 as a scheduled fix (ROADMAP Phase 3; 02-UAT Deferred Follow-Ups). | O Hingst | 2026-07-17 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-17 | 15 | 15 | 0 | gsd-security-auditor (verify-mitigations mode, ASVS L1, block_on=high) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-17
