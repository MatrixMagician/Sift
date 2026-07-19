---
phase: 5
slug: domain-adapters-journald-dsserrors-eustack
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on (high) severity
threats_open: 0
asvs_level: 1
created: 2026-07-18
---

# Phase 5 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Register derived from the six 05-0N-PLAN.md `<threat_model>` blocks and 05-RESEARCH,
> plus the Phase-1 adapter register carried forward because journald / dsserrors / eustack
> are new untrusted-ingest surface. Mitigations verified at ASVS L1 grep depth against the
> committed state including the `fix(05-review)` commits 5db0225 · ab3f798 · 81aeb01 · 016762b · 432242c.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| diagnostic file bytes → adapter parse | Fully untrusted adversarial content (journald JSONL, DSSErrors records, eu-stack dumps) enters the new parsers | Arbitrary bytes |
| compressed input → `open_bytes` | gz/zst siblings of any format can expand enormously (bomb) | gz/zst streams |
| case-relative path → `attrs["node"]` | A crafted `nodeN/` directory name is read as node metadata | Path component (metadata only) |
| adapter fields → store INSERT | message / session / thread / component / attrs / severity flow into SQL | Untrusted parsed fields |
| stored adapter fields → terminal | `sift show events` renders untrusted message / severity / source to the operator's TTY | Control chars, escapes |
| case bundle → file enumeration | `rglob` walk of the input dir may encounter symlinks pointing outside the bundle | Filesystem paths |
| adversarial line/frame → regex | dsserrors / eustack token regexes run on attacker-crafted lines | Untrusted text → regex engine |

---

## Threat Register

### Phase-5 registered threats (PLAN `<threat_model>` blocks)

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-05-01 | Repudiation | cli.py coverage read-back | high | mitigate | `stats = last_stats if isinstance(file_adapter, ConfigurableAdapter) else None`; real `ParseStats.coverage`, never fabricated 1.0 (`cli.py:352-357`); guarded by `test_phase5_e2e_ingest_show_real_coverage_idempotent` + `test_dsserrors.test_coverage_bounded_non_vacuous` | closed |
| T-05-02 | Tampering | tz_overrides / input_root delivery | medium | mitigate | Config delivered to *any* `ConfigurableAdapter`, not just genericlog (`cli.py:272-274`) so node-tagging / multi-node tz cannot be silently skipped | closed |
| T-05-03 | Information disclosure | user-provided fixture sample | medium | mitigate | 05-02 resolved proceed-on-assumed-shapes: no production sample entered the repo; all fixtures are synthetic + sanitised (05-04/05-05 SUMMARY, fixture files) | closed |
| T-05-10 | DoS | oversized single journald JSON line | high | mitigate | Byte-level split via shared `byte_lines` force-splits a monster line at `MAX_EVENT_BYTES` (`journald.py:192`, `genericlog.py:250-264`) — bounded memory | closed |
| T-05-11 | Tampering/DoS | malformed / partial JSON line | medium | mitigate | `json.loads` in try/except → `severity="unknown"`, byte-accounted event, never crash (`journald.py:209-221`); `test_malformed_line_becomes_unknown_and_byte_accounted`, `test_non_object_json_line_is_unknown` | closed |
| T-05-12 | Tampering | binary / NUL / non-UTF-8 MESSAGE | medium | mitigate | `_field_to_str` decodes int-arrays via `bytes(...).decode("utf-8", errors="replace")` — no list repr, NUL survives (`journald.py:86-110`); `test_field_to_str_int_array_with_nul_decodes`, `test_message_nul_from_fixture` | closed |
| T-05-13 | Tampering | PRIORITY outside 0-7 violating severity CHECK | high | mitigate | Exhaustive `_PRIORITY_SEVERITY` map defaults to `unknown` (`journald.py:39-45,66-83`); `test_priority_full_range_maps_to_six_value_set`, `test_priority_invalid_or_missing_maps_to_unknown`, `test_no_emitted_severity_outside_check_set` | closed |
| T-05-14 | Tampering/Spoofing | ANSI/terminal escape in journald message | medium | mitigate | Whole-line `_sanitise` at render covers the new fields (`cli.py:57-76,588`); `test_phase5_show_sanitises_domain_adapter_escape_bytes` | closed |
| T-05-20 | DoS | never-terminated MCM Info Dump block | high | mitigate | 256-line / 64 KiB cap force-closes into a `severity="unknown"` continuation (`dsserrors.py:296-313`); `test_mcm_cap_forces_unknown_continuation`, `test_mcm_truncated_at_eof_is_one_event` | closed |
| T-05-21 | Tampering | path traversal via crafted node directory | medium | mitigate | `node = parts[0] if len(parts) > 1 else None` from the already case-relative path — metadata only, never used to open a file (`dsserrors.py:178-179`); symlinks skipped at enumeration (`cli.py:242`); `test_node_tagging_distinct_per_subdirectory`, `test_node_omitted_for_root_level_file` | closed |
| T-05-22 | Tampering (SQLi) | SID / OID / message via store INSERT | high | mitigate | `store.py` is sole SQL owner, parameterised `?` binds only (carried T-02-02 / T-04-05); new fields ride the same path unchanged | closed |
| T-05-23 | Tampering | severity token outside the 6-value CHECK | high | mitigate | Exhaustive `_DSS_SEVERITY` map, default `unknown`, never fabricated (`dsserrors.py:76-100`); `test_token_severity_tags_map_to_six_value_set`, `test_token_no_emitted_severity_outside_check_set` | closed |
| T-05-24 | Tampering/Spoofing | ANSI escape in dsserrors message/session/thread | medium | mitigate | Whole-line `_sanitise` at render (`cli.py:57-76,588`) | closed |
| T-05-30 | DoS | monster / never-terminated thread block | high | mitigate | 256-line / 64 KiB cap force-closes into a `severity="unknown"` continuation (`eustack.py:211-225`); `test_oversized_thread_caps_to_unknown_continuation` (260-frame fixture) | closed |
| T-05-31 | Tampering/DoS | malformed / truncated dump (partial thread) | medium | mitigate | Header-triggered grouping degrades to a byte-accounted `severity="unknown"` event, never crash (`eustack.py:238-254`); `test_preamble_is_unknown_ts_none` | closed |
| T-05-32 | Tampering/Spoofing | ANSI escape in frame symbols / message | medium | mitigate | Whole-line `_sanitise` at render (`cli.py:57-76,588`) | closed |
| T-05-33 | Tampering (SQLi) | thread / message via store INSERT | high | mitigate | Parameterised `?` only; `store.py` sole SQL owner; new fields ride the same path | closed |
| T-05-40 | Repudiation | e2e coverage report for domain adapters | high | mitigate | e2e asserts real coverage strictly below 100% on an unparseable-region fixture — the fabricated-100% bug cannot regress (`test_phase5_e2e_ingest_show_real_coverage_idempotent`) | closed |
| T-05-41 | Tampering/Spoofing | terminal-escape content in adapter fields | medium | mitigate | e2e asserts `_sanitise` strips a real ESC from a journald MESSAGE on `show`, visible text survives (`test_phase5_show_sanitises_domain_adapter_escape_bytes`) | closed |
| T-05-42 | Tampering | wrong-adapter routing (sniff collision) | medium | mitigate | Unique-max detection, genericlog fallback on tie/below-threshold (`adapters/__init__.py:85-91`); `test_adapters_detect` asserts unique max per fixture, no cross-collision | closed |
| T-05-SC | Tampering (supply chain) | pip/uv package installs | low | accept | Zero external packages this phase — stdlib `json`/`re`/`datetime` only; every SUMMARY `## Threat Flags` = None | closed |

### Carried-forward Phase-1 adapter register (new ingest surface)

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-05-CF1 | DoS | decompression bomb on the shared `open_bytes` raw-read path | medium | mitigate | Streaming decompression (`base.py:56-67`, zstd `stream_reader` / gzip stream) + per-event `MAX_EVENT_BYTES` force-split (`genericlog.py:227-273`) → bounded memory; nothing decompressed to disk. **Note:** the 128 MiB `_MAX_RAW_BYTES` cap (`store.py:27,50`) governs the *case.db raw-BLOB read-back* path (T-02-01), a distinct path — ingest-bomb protection is bounded-memory streaming + force-split, not a total-output cap. `test_ingest_truncated_gz_mid_stream_contributes_zero_rows` | closed |
| T-05-CF2 | Tampering/Spoofing | terminal ESC / C0 / C1 / DEL + bidi / zero-width at render | medium | mitigate | `_sanitise` strips C0 (<0x20 except \n\t), DEL+C1 (0x7f-0x9f) and Unicode category Cf (bidi U+202E, zero-width) on the whole rendered line (`cli.py:57-76`); `test_show_strips_terminal_escapes`, `test_show_sanitises_every_db_sourced_field`, `test_hostile_filename_escapes_never_reach_terminal` | closed |
| T-05-CF3 | Tampering | symlink / `..` path escape from the case bundle | medium | mitigate | `parse()` is strictly per-file — opens only its given `path` via `open_bytes`, no directory walk / sibling glob; rotated-sibling + node-dir derivation are metadata only; symlinks skipped loudly at enumeration (`cli.py:242-254`); `test_ingest_skips_symlinks_loudly_never_follows` | closed |
| T-05-CF4 | Tampering/DoS | corrupt-archive handling | medium | mitigate | `detect()` + `parse()` run inside a per-file savepoint nested in the ingest transaction with try/except (`cli.py:255-347`) — a corrupt gz/zst raises a loud per-file ERROR, contributes zero rows, run continues; `test_ingest_truncated_gz_mid_stream_contributes_zero_rows` | closed |
| T-05-CF5 | DoS (ReDoS) | new dsserrors / eustack token regexes | medium | mitigate | All new patterns anchored (`^`/`\b`) and linear — no nested quantifiers, no catastrophic backtracking (`dsserrors.py:51-72`, `eustack.py:55-66`); verified by static inspection at L1 | closed |
| T-05-CF6 | Repudiation | silent loss / determinism | low | mitigate | Every unparseable region becomes a `severity="unknown"` ts=None byte-accounted event (nothing dropped); `event_id=sha256(relpath, byte_offset)[:16]` computed on the decompressed byte stream — determinism unaffected; per-adapter `test_coverage_*` / `test_*_is_unknown_ts_none` | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above `high` count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-05-01 | T-05-SC | Zero external packages added in Phase 5 — stdlib `json`/`re`/`datetime` only; nothing to legitimacy-check | O Hingst | 2026-07-18 |
| AR-05-02 | T-05-03 / 05-02 | Proceed-on-assumed-shapes: no sanitised production sample was supplied, so no real SIDs/IPs/hostnames could enter fixtures; dsserrors/eustack regexes are anchored on version-stable structural tokens and a later real sample is a localised regex change (functional, not security, residual) | O Hingst | 2026-07-18 |
| AR-05-03 | T-03-02 (carried) | Hostile/invalid encodings decoded `errors="replace"` strictly after byte offsets are fixed — cannot corrupt event identity or coverage; render side sanitised separately (T-05-CF2) | carried from Phase 1 (AR-01) | 2026-07-16 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-18 | 27 | 27 | 0 | gsd-secure-phase (L1 grep-depth; register from six PLAN `<threat_model>` blocks + carried Phase-1 adapter register; every mitigation located in committed code and a guarding test named) |

Gate confirmed green at audit time: `uv run ruff check` clean, `uv run pyright` 0 errors/0 warnings, `uv run pytest` 378 passed / 2 deselected. Post-review `fix(05-review)` commits (IN-01..04, WR-01) verified present in the audited tree.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-18
