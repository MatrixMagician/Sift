---
phase: 12
slug: dssperfmon-adapter-pipeline-exclusion
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-07-20
---

# Phase 12 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

**Posture applied:** `security_asvs_level: 1`, `security_block_on: high` — both read from
`.planning/config.json` (`workflow` block). The audit brief stated these were unset; they are in fact
set, so the configured values were used rather than a default posture. L1 verification depth
(mitigation PRESENT in the cited file) was the floor; the four constructs called out for scrutiny were
traced to L2/L3 depth (boundary placement and bypass-path analysis).

**Register scope correction.** The brief described T-12-01 … T-12-16. The shipped plans actually carry
**T-12-01 … T-12-18** (12-04 declares five threats, T-12-14 … T-12-18, not three) plus a supply-chain
threat **T-12-SC** repeated verbatim in all four plans. All 19 were verified; none were dropped.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| customer artefact → adapter | PDH-CSV read from disk; contents, sizes, encodings and counter names are attacker-influenceable in principle | Untrusted customer diagnostic text |
| compressed file → decompressed stream | `base.open_bytes` handles gzip/zstd; a hostile archive crosses here | Untrusted compressed bytes |
| malformed artefact → parser branches | Deliberately corrupt CSV rows reach the degrade paths | Untrusted rows, bad cells, bad stamps |
| arbitrary case file → `detect()` | Every file in an ingested case is now scored by a fifth sniff | Untrusted file heads (64 KB) |
| CLI argument → adapter selection | `--adapter` / config globs may name an adapter; default is content routing | User-supplied glob + registry name |
| event `source` value → SQL | The phase's only new SQL clause; must not become an injection vector | Module-constant source kinds |
| ranking pipeline → citation pipeline | PERF-03's boundary: exclusion applies on one side only | Event rows / event ids |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-12-01 | Denial of Service | `DssperfmonAdapter.sniff` | medium | mitigate | Anchored literal byte-prefix compare against `PDH_SNIFF_PREFIX`; **no regex imported anywhere in the module** — `src/sift/adapters/dssperfmon.py:45,174-177`. Grep for `import re` / `re.` returns only prose comments (lines 14, 42, 136), zero code matches. ReDoS discharged by construction | closed |
| T-12-02 | Denial of Service | `parse` read loop | medium | mitigate | Loop is `genericlog.byte_lines`, which force-splits a newline-less run at `MAX_EVENT_BYTES` — `src/sift/adapters/genericlog.py:44,250-263`; call site `dssperfmon.py:191`. Per-line memory bounded at 64 KB | closed |
| T-12-03 | Tampering | timestamp normalisation | medium | mitigate | `tz_offset_min` is **never arithmetic**: all 15 occurrences are string capture (`dssperfmon.py:153-155`), note formatting (157), tuple transport (161, 208) or `attrs` storage (237-238). Timestamps flow only through `to_utc(naive, override_tz)` at line 226 — the bias is not a parameter. ADR 0012 honoured | closed |
| T-12-04 | Information disclosure | adapter module | low | accept | Pure local parsing, no socket opened. Autouse `_no_network` guard patches `socket.socket.connect` to raise for every non-`live` test — `tests/conftest.py:34-59`. Logged as AR-12-01 | closed |
| T-12-05 | Denial of Service | `base.open_bytes` decompression | low | accept | Pre-existing shipped behaviour; `git diff` over the phase shows no change to `base.py`. No new exposure. Logged as AR-12-02 | closed |
| T-12-06 | Denial of Service | malformed-row branches | medium | mitigate | Every branch emits-and-continues; none raises, recurses or retries. Verified by execution, not reading: `next(csv.reader([text]))` survives NUL bytes, lone/unterminated quotes, 64 KB lines and replacement chars without raising, and blank lines are skipped before the call (`dssperfmon.py:199-202`). `MAX_EVENT_BYTES` (65536) sits below csv's default field limit (131072), so `_csv.Error: field larger than field limit` is unreachable. All four degrade paths carry tests — `tests/test_dssperfmon.py:97,109,120,133,145` | closed |
| T-12-07 | Tampering | cell validity probe | medium | mitigate | `float()` result is discarded and never rebound; the cell stays an unconverted string, since `attrs.update(values)` at `dssperfmon.py:239` consumes `values` built from raw `row[1:]` at line 227 — `_bad_cells` (116-129) returns only *names*, never values. Executed the probe against `1e999`, `NaN`, `Infinity`, `-inf`, `1_000`, `0x10`, `''` and a 100 000-digit literal: no exception type other than the caught `ValueError`, and no path by which a crafted literal reaches stored state. See OBS-1 below for a non-security follow-up | closed |
| T-12-08 | Repudiation | parse coverage | medium | mitigate | `stats.unknown_fallback_bytes += len(bline)` on every degrade path — `dssperfmon.py:261` — feeding the existing `ParseStats.coverage` property. Pinned by `tests/test_dssperfmon.py:169` (`test_parse_coverage`) and `:274` (`test_span_partition_and_coverage`). Silent loss is observable | closed |
| T-12-09 | Denial of Service | embedded-newline handling | low | accept | Fragments degrade through the column-count branch (`dssperfmon.py:244-250`) with `line_offset` captured before any decode (line 193). No reassembly buffer exists to exhaust. Pinned by `tests/test_dssperfmon.py:145`. Logged as AR-12-03 | closed |
| T-12-10 | Denial of Service | `detect()` sniff loop | medium | mitigate | `read_head(path).startswith(PDH_SNIFF_PREFIX)` — `dssperfmon.py:175`. Constant work per file, no scan, no regex. Registry iteration is a fixed 5-entry dict, `src/sift/adapters/__init__.py:19-25,87` | closed |
| T-12-11 | Tampering | adapter routing | high | mitigate | **The shipped test is stronger than the threat model's prose.** The register describes a "unique-maximum assertion"; `tests/test_adapters_detect.py:167-173` actually asserts sole claimancy — `assert claimants == [name]`, where `claimants` is every domain adapter clearing `SNIFF_THRESHOLD`, not merely the argmax. Covers all four domain adapters incl. `dssperfmon` (`_DOMAIN_ADAPTERS`, line 33). Divergence is deliberate and recorded in 12-03-SUMMARY.md; weakening the test to match the prose would admit a real collision. Closed on the stronger assertion | closed |
| T-12-12 | Spoofing | `REGISTRY` contents | low | accept | Source-level dict literal, `src/sift/adapters/__init__.py:19-25`. No `importlib`, no entry points, no plugin loading — only a code change can add an adapter. Logged as AR-12-04 | closed |
| T-12-13 | Information disclosure | CLI tests | low | mitigate | Autouse `_no_network` fixture raises `RuntimeError` on any `socket.socket.connect` for every test lacking the `live` marker — `tests/conftest.py:34-59`. The phase's CLI tests carry no `live` marker | closed |
| T-12-14 | Tampering | `iter_event_summaries` exclusion clause | high | mitigate | Verified line by line at `src/sift/store.py:659-668`: `sorted(EXCLUDED_FROM_RANKING)` → `placeholders = ",".join("?" ...)` → only `{placeholders}` is f-string-interpolated; the SELECT list and ORDER BY are non-f static strings, and every source value is `?`-bound via `tuple(excluded)`. The set is a module frozenset (`store.py:335`) reachable by no caller or user input. `# noqa: S608` at line 664 carries a two-line justification (662-663). `sorted()` additionally fixes parameter order for determinism | closed |
| T-12-15 | Tampering | citation retrieval paths | high | mitigate | `iter_event_rows` is unfiltered by design with an explicit anti-tidy-up comment naming the asymmetry — `store.py:683-689`. Pinned by four tests: `tests/test_store.py:602` (`iter_event_rows` unfiltered), `:614` (`get_events` resolves perfmon), `tests/test_cli.py:1439` (`show events` includes perfmon), `:1447` (every one of the 20 samples citable via `get_events_by_ids` **and** none ranked) | closed |
| T-12-16 | Repudiation | cluster output regression | high | mitigate | `test_cluster_output_identical_with_and_without_perfmon` — `tests/test_cli.py:1415-1436`. Asserts `a.output == b.output` on derived `show clusters` output, with the non-vacuity guard `n_b - n_a == _PERFMON_ROWS` (1436) so an equality that passed because the CSV silently failed to ingest fails loudly. Note: 12-04-SUMMARY.md places this test in `test_cluster.py`; it actually landed in `test_cli.py` (see OBS-2) | closed |
| T-12-17 | Elevation of privilege | exclusion configurability | medium | mitigate | `EXCLUDED_FROM_RANKING` has exactly four references repo-wide (`store.py:335,647,659,683`) — a definition, two docstrings, one use. No parameter, no `SIFT_*` env var, no config key, and `iter_event_summaries()` takes no arguments (`store.py:641`). Cannot be widened or disabled at runtime (D-07) | closed |
| T-12-18 | Information disclosure | clustering tests | low | mitigate | Existing `httpx.MockTransport` fake (`tests/test_cluster.py:_client`) plus the autouse `_no_network` guard. The criterion-4 test runs no `analyze` step, so no embedding or LLM call is attempted at all | closed |
| T-12-SC | Tampering | dependency supply chain | high | mitigate | `git diff 2d9d090..HEAD -- pyproject.toml uv.lock` returns **empty** — no dependency added or version moved across the entire phase. The parser uses stdlib `csv` only (`dssperfmon.py:26`). No Package Legitimacy Gate was required or bypassed | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-12-01 | T-12-04 | Adapter performs pure local parsing and opens no socket; the autouse `_no_network` conftest guard enforces this in tests. Consistent with the project-wide zero-egress rule | Phase 12 plan 12-01 | 2026-07-20 |
| AR-12-02 | T-12-05 | Decompression DoS surface in `base.open_bytes` is pre-existing shipped behaviour, unchanged by this phase; no new exposure introduced | Phase 12 plan 12-01 | 2026-07-20 |
| AR-12-03 | T-12-09 | Embedded-newline fragments degrade through the column-count branch with byte offsets intact; no reassembly buffer exists to exhaust | Phase 12 plan 12-02 | 2026-07-20 |
| AR-12-04 | T-12-12 | Adapter registration is a source-level dict with no dynamic or plugin loading; only a code change can add an adapter | Phase 12 plan 12-03 | 2026-07-20 |

---

## Observations (non-blocking, no threat opened)

**OBS-1 — `float()` accepts non-finite literals (data quality, not tampering).**
`_bad_cells` treats `NaN`, `Infinity`, `-inf` and overflow literals such as `1e999` as *valid*, so a
row carrying one is classed `severity="info"` rather than degraded to `"unknown"`. This does **not**
reopen T-12-07: the value is stored verbatim as an unconverted string, exactly as the threat's
mitigation claims, and no stored state is altered. It matters for Phase 13, whose correlator will
convert these cells for arithmetic — a `math.isfinite` guard belongs there, at the point of
conversion, not here at the point of storage. Recorded for Phase 13 rather than patched in Phase 12.

**OBS-2 — `# noqa: DTZ007` is design, not masking.**
`datetime.strptime(row[0], TS_FORMAT)` at `dssperfmon.py:221` suppresses DTZ007 (naive datetime).
Verified as deliberate: a PDH sample stamp genuinely carries no zone token, and the result is handed
straight to `to_utc(naive, override_tz)` on line 226 — the same shared seam every other adapter uses.
Attaching a zone at the strptime call would bypass both `to_utc` and the `--tz` override, which is
precisely what ADR 0012 forbids, and would shift perfmon samples away from the paired DSSErrors
timeline. The suppression is scoped to one call and carries a six-line justification (215-218). Pinned
by `tests/test_dssperfmon.py:296,304,313`.

**OBS-3 — Summary artefact drift (process, not security).**
`12-01-SUMMARY.md` and `12-02-SUMMARY.md` carry no `## Threat Flags` section at all, where 12-03 and
12-04 both do (`None.` in each). Nothing suggests suppressed surface — the two plans' threats all
verify closed against shipped code — but the section's absence means the executor's "no new surface"
claim is unstated rather than stated for plans 01 and 02. Separately, 12-04-SUMMARY.md attributes
`test_cluster_output_identical_with_and_without_perfmon` to `tests/test_cluster.py`; it is in
`tests/test_cli.py:1415`. Both are documentation defects with no code impact.

---

## Unregistered Flags

None. Both summaries that declare a `## Threat Flags` section declare `None.`, and the audit found no
new attack surface outside the register: the phase's entire `src/` footprint is four files
(`adapters/dssperfmon.py`, `adapters/__init__.py`, `adapters/dsserrors.py`, `store.py`), each mapped
to at least one threat, with no new endpoint, auth path, schema change or dependency.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-20 | 19 | 19 | 0 | security-auditor (verify-mitigations, ASVS L1, block_on high) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-20
