---
phase: 10
slug: diagnostic-flags-lead-up-attribution-sift-mcm-report-csv
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-07-19
---

# Phase 10 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Verified by gsd-security-auditor in verify-mitigations mode (register authored at plan time; ASVS L1, block-on: high). Every high-severity threat traced to a file:line control and a named guard test.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| DSSErrors log text → Markdown/JSON report | Untrusted `Source=`/SID/OID/lifecycle/raw text rendered into a shareable `mcm_report.md`/`.json` (and the PDF-capable HTML path) | Attacker-controlled log strings |
| DSSErrors log text → CSV export | Untrusted key/`Source=` values written into a spreadsheet-openable `mcm_attribution.csv` | Attacker-controlled log strings |
| `case` argument → filesystem write target | User-supplied case name resolved to the `<case>/mcm/` bundle directory | User-supplied path component |
| stdout summary | Log-derived text echoed to the operator's terminal | Attacker-controlled log strings |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-10-01 | Denial of Service | `AVAIL_MCM_RE`/`HWM_RE` re-parse in `_avail_timeline` | low | mitigate | Anchored regexes reused verbatim (`mcm.py:47-48`); single forward pass (`mcm.py:530-538`) | closed |
| T-10-02 | Tampering | integer coercion of `AvailableMCM=`/`HWM(PB)=` | low | accept | `\d+`-matched ints, Python unbounded; documented rationale | closed |
| T-10-03 | Information Disclosure | `select_window` output | low | accept | Pure function, no I/O (`mcm.py:541-603`); documented rationale | closed |
| T-10-04 | Tampering | inverted headroom grading | medium | mitigate | `_grade(invert=True)` (`mcm.py:609-624`); guard `test_headroom_inverted_grading` (`test_mcm.py:467`) | closed |
| **T-10-05** | Tampering | absolute-GB leak into a flag headline | **high** | mitigate | Every `value_pct` is `part/whole*100` (`mcm.py:645,663,682,739`); guard `test_machine_independence_scaled` (`test_mcm.py:504-528`) | closed |
| T-10-06 | Denial of Service | zero/None denominators in ratio maths | low | mitigate | None/zero-denominator guards before every divide (`mcm.py:644,662,681,709,736-738`) | closed |
| T-10-07 | Tampering | malformed `[mcm.thresholds]` config | low | mitigate | `extra="forbid"` on `ThresholdPair`/`McmThresholdsConfig`/`McmConfig` (`config.py:70,88,101`) | closed |
| **T-10-08** | Tampering | attributing the wrong span (post-denial grants) | **high** | mitigate | `attribute_window` walks `range(start_idx, denial_idx)` gated on `SUCCESS_MARKER` (`mcm.py:913-915`); guard `test_attribution_excludes_post_denial` (`test_mcm.py:671-683`) | closed |
| **T-10-09** | Repudiation | a figure without its citation | **high** | mitigate | `AttributionRow.event_ids` required (`mcm.py:258`); guard `test_attribution_event_id_provenance` asserts `⊆ ep.event_ids ⊆ store` (`test_mcm.py:621-641`) | closed |
| T-10-10 | Denial of Service | `SID/OID/SIZE/SOURCE_RE` on hostile lines | low | mitigate | Anchored regexes reused (`mcm.py:43-46`), single pass (`mcm.py:917-924`) | closed |
| T-10-11 | Tampering | non-deterministic row order (set iteration) | medium | mitigate | `dict.fromkeys` dedup + sort (`mcm.py:940-945`); guards `test_json_deterministic`/`test_csv_deterministic`/`test_two_episode_determinism_byte_identical` | closed |
| **T-10-12** | Tampering | Markdown/HTML injection via hostile log text | **high** | mitigate | `_field` (aliased import `mcm_report.py:38`, = `_escape(sanitise(text))` `markdown.py:65-67`) applied to every log-sourced field (`mcm_report.py:93-94,111,132,154-163,170,183`); guard `test_markdown_sanitises_hostile_fields` (`test_mcm_report.py:155-164`) | closed |
| **T-10-13** | Tampering | CSV / formula injection via `key`/`Source` fields | **high** | mitigate | `path.open(..., newline="")` + `csv.writer` (`mcm_report.py:243-244`, never manual-join); keys structurally hex/`[\w:]+` cannot begin with a formula trigger (`mcm.py:43-46`) | closed |
| **T-10-14** | Tampering | path traversal on the `<case>/mcm/` write | **high** | mitigate | `case_db_path(config.data_dir, case).parent / "mcm"` (`cli.py:1035`); `case_db_path` runs `validate_case_name` + asserts `resolve().is_relative_to(cases)` (`store.py:135-139`) | closed |
| T-10-15 | Tampering | terminal-injection via the stdout summary | medium | mitigate | `_sanitise(top.message)` before stdout echo (`cli.py:1065`) | closed |
| **T-10-16** | Information Disclosure | absolute-GB figure in a report headline | **high** | mitigate | Flags rendered `{value_pct:.1f}%` (`mcm_report.py:108-113`), window `% of HWM` with GB only parenthetical (`mcm.py:602`); guard `test_markdown_no_absolute_gb_headline` (`test_mcm_report.py:167-179`) | closed |
| T-10-17 | Denial of Service | render of a very large/open-truncated episode | low | mitigate | Pure bounded pass `render_mcm_markdown` (`mcm_report.py:206-219`); only escaped labels + numeric breakdown rendered | closed |
| T-10-SC | Tampering | dependency installs (supply chain) | low | accept | No package installs — stdlib `csv`/`json`/`re`/`dataclasses` + already-installed Pydantic/Typer; surface unchanged | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above `high` count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-10-01 | T-10-02 | `AvailableMCM=`/`HWM=` values are `\d+`-matched and coerced to Python's unbounded `int`; no overflow/injection surface. | Plan-time threat model | 2026-07-19 |
| AR-10-02 | T-10-03 | `select_window` is a pure function with no I/O, filesystem, or network access; nothing to disclose. | Plan-time threat model | 2026-07-19 |
| AR-10-03 | T-10-SC | Zero package installs this phase — stdlib + already-installed Pydantic/Typer only; supply-chain surface unchanged. | Plan-time threat model | 2026-07-19 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-19 | 18 | 18 | 0 | gsd-security-auditor (verify-mitigations, ASVS L1) |

**Non-blocking hardening observations (informational — do not affect `threats_open`):**
- **T-10-13 (CSV):** mitigation is defence-by-construction (structural key regexes + `csv.writer`); no dedicated test feeds a formula-trigger key (`=`/`+`/`-`/`@`) through `write_attribution_csv`. Present in code → CLOSED at L1; a formula-trigger assertion would harden it.
- **T-10-14/T-10-15 (CLI):** containment (`case_db_path`) and stdout `_sanitise` calls are present in `cli.py`; no dedicated CLI test asserts a rejected `../` case name or sanitised hostile stdout. Present in code → CLOSED at L1; these are defence-in-depth (flag messages are numeric in practice).

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-19
