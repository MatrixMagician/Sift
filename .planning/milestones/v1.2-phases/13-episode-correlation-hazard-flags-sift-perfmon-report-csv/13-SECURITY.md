---
phase: 13
slug: episode-correlation-hazard-flags-sift-perfmon-report-csv
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
block_on: high
created: 2026-07-20
---

# Phase 13 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

Register authored at plan time (`register_authored_at_plan_time: true`) — all six PLAN.md files
carried a `<threat_model>` block. The audit therefore ran in **verify-mitigations** mode: every
threat below was checked for a present, working control in the implementation. No retroactive
threat discovery was performed.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| customer CSV header → adapter `attrs` keys | Counter names are attacker-influenceable text that becomes dictionary keys alongside provenance metadata | Untrusted text |
| customer CSV rows → `stats.notes` | One malformed header width can drive one note per data row — an attacker-chosen multiplier | Untrusted volume |
| `case.db` `attrs` values → computed figures | Counter values are customer-supplied strings stored verbatim by the Phase 12 adapter | Untrusted numerics |
| `McmAnalysis` boundary ids → resolved timestamps | A tampered or partially-ingested store can present an id that does not resolve | Integrity-critical refs |
| counter names / hazard text → CSV cells | Customer text reaches a file a spreadsheet will open and may evaluate | Untrusted text |
| counter names / hazard text → Markdown + stdout | Customer text reaches a document and a terminal the operator reads | Untrusted text |
| analysis models → JSON report | Non-ASCII code points would otherwise reach the JSON artefact raw | Untrusted text |
| `case` CLI argument → filesystem path | A user-supplied case name must never escape the configured data directory | Path input |
| exception text → operator stdout | `OSError` messages embed filesystem paths and may embed customer-derived names | Internal detail |

---

## Threat Register

27 threats. All closed. Line references verified against the implementation at commit `8ff3b2f`.

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-13-FIXPATH | Tampering | `tests/_perfmon_fixtures.py` builders | low | mitigate | `_write(tmp_path, name, …)` builds `tmp_path / name`; all three public builders pass fixed filenames. No caller-chosen destination parameter exists. | closed |
| T-13-VACUOUS | Repudiation | the three synthetic fixtures | medium | mitigate | Three co-located guard tests: `test_collision_fixture_really_collides`, `test_drift_fixture_really_drifts`, `test_non_finite_fixture_passes_bare_float`. Each builder was also counterfactually broken during execution and confirmed to fail. | closed |
| T-13-NETWORK | Information Disclosure | new test modules | low | accept | `tests/conftest.py:34` `@pytest.fixture(autouse=True)`; `_blocked` raises `RuntimeError` via `monkeypatch.setattr(socket.socket, "connect", …)`. Basis confirmed true, not assumed. | closed |
| T-13-NONFINITE | Tampering | `_numeric` in `pipeline/perfmon.py` | **high** | mitigate | `math.isfinite(parsed)` gate at `perfmon.py:81`. Applied at **both** numeric entry points — `_counter_trends:264` and `_hazard_denial_always_zero:434`; no third path reads counter cells as numbers. `test_non_finite_excluded`. | closed |
| T-13-BOUNDARY | Spoofing | `_resolve_span` | medium | mitigate | `perfmon.py:198-217` — four distinct unresolvable returns yield a graded hazard and no trend (D-04). `McmEpisode.denial_ts` appears nowhere in the module (grep-confirmed); no neighbour substitution. `test_span_missing_ts_hazard`. | closed |
| T-13-ATTRSWEEP | Tampering | counter sweep in `_counter_trends` | medium | mitigate | `perfmon.py:251-258` filters `key not in _RESERVED_ATTRS`, **imported** from the adapter (`:22`) rather than redeclared, covering all 7 provenance keys plus `_DRIFT_ATTR`. | closed |
| T-13-TYPECOERCE | Tampering | `_numeric` input | low | accept | See Accepted Risks — rationale corrected during audit. | closed |
| T-13-ATTRKEY | Tampering | `_DRIFT_ATTR` / `_RESERVED_ATTRS` | **high** | mitigate | `dssperfmon.py:108` — `_DRIFT_ATTR` is a member of `_RESERVED_ATTRS`; a colliding counter is routed under `_COUNTER_PREFIX`. Marker written at `:377` **before** the counter loop. `test_counter_named_like_drift_marker_cannot_shadow_it`. | closed |
| T-13-DOS | Denial of Service | note appends in `dssperfmon.py` | **high** | mitigate | `_NOTE_CAP = 10` (`:81`) enforced in the per-category `note()` closure (`:280-284`), plus one summary line per overflowed category (`:448-455`). Uncapped, one header-width mismatch yields 13,596 notes (~1 MB in a single meta row). `test_notes_capped`. | closed |
| T-13-DROP | Repudiation | `dict(zip(counter_names, …))` | medium | mitigate | `_qualify_counter_names:126-165` — two-segment qualification, full-path last resort (`:155-157`); every column retains a key. `test_collision_qualified_keys_retain_both_counters`. | closed |
| T-13-EVIDENCE | Repudiation | interaction of WR-02 and WR-05 | medium | mitigate | The marker write (`:377`) is unconditional per drifted row and **not** routed through `note()`, so the cap cannot suppress the drift evidence. | closed |
| T-13-FALSEJOIN | Spoofing | non-overlap hazard | **high** | mitigate | `_hazard_non_overlap:334-380` — `severity="critical"` (`:369`), names both ranges; caller (`:609-612`) emits it *instead of* counters. Zero-sample case guarded before indexing (`:362`). `test_non_overlap_hazard`. | closed |
| T-13-EVADE | Tampering | `_find_counter_key` | medium | mitigate | Returns `tuple[str, ...]` (`:394-411`); caller accumulates **every** matching key's reading (`:430-436`) and requires `all` readings zero (`:438`). A crafted duplicate cannot mask a genuinely non-zero instance. | closed |
| T-13-DRIFTTRUST | Tampering | drift hazard | medium | mitigate | `_hazard_counter_set_drift:474` — sole predicate is `_DRIFT_ATTR in s.attrs`; no width/cell-count recount exists in the module, so adapter and correlator cannot disagree. `test_drift_hazard_reads_marker_not_row_widths`. | closed |
| T-13-HAZDOS | Denial of Service | cited `event_ids` | medium | mitigate | `_CITE_CAP = 10` (`:62`) applied via `_cited()` (`:383-391`) in both unbounded-growth hazards (`:441`, `:481`); both messages state `Citing {n} of {total}`, so capping never silently hides evidence. | closed |
| T-13-HAZTEXT | Tampering | hazard `message` strings | low | transfer | All three receiving controls verified present, not assumed: `render/markdown.py:65-67` `_field = _escape(sanitise(text))`; `perfmon_report.py:196` `ensure_ascii=True`; `cli.py:1160` `_sanitise(top.message)`. Pipeline tier confirmed print-free. | closed |
| T-13-CSVINJ | Tampering | `_csv_safe` / `write_perfmon_trend_csv` | **high** | mitigate | `_FORMULA_TRIGGERS` (`:74`); `_csv_safe:224` prefixes `'`. Applied to **every** string cell (`:242`, `:246-257`). Empirically confirmed by the orchestrator across all six triggers (`=`, `+`, `-`, `@`, tab, CR) with legitimate names passing through unmodified. `test_csv_formula_guard`. | closed |
| T-13-MDESC | Tampering | `_counter_table` / `_hazard_table` | medium | mitigate | `_field` on every dynamic cell (`:121-123`, `:144-146`, `:154-159`, `:106`). No unescaped interpolation of model data found. `test_markdown_cells_pass_through_field`. | closed |
| T-13-JSONESC | Tampering | `render_perfmon_json` | medium | mitigate | `ensure_ascii=True` (`:196`) backslash-escapes every non-ASCII code point. `test_json_is_pure_ascii`. | closed |
| T-13-JSONNAN | Tampering | `render_perfmon_json` | medium | mitigate | The upstream `_numeric` finite-or-`None` invariant is the only source of stored floats, so `json.dumps` can never emit bare `NaN`/`Infinity`. `test_json_round_trips_through_loads`. | closed |
| T-13-RENDPATH | Tampering | `write_perfmon_trend_csv(path)` | low | transfer | Receiving control verified present at `cli.py:1119` (see T-13-PATH). Renderer's only I/O is `path.open` (`:238`) with a caller-supplied path. | closed |
| T-13-PATH | Tampering | `perfmon` bundle directory | **high** | mitigate | `cli.py:1119` `case_db_path(config.data_dir, case).parent / "perfmon"`. `store.py:133-140` calls `validate_case_name(name)` then asserts `path.resolve().is_relative_to(cases.resolve())`, raising `ValueError` on escape. No user-supplied path is joined anywhere in the command. | closed |
| T-13-ERRLEAK | Information Disclosure | `except OSError` branch | **high** | mitigate | `cli.py:1137-1145` — `_sanitise(str(exc))` + `raise typer.Exit(1) from None`. The `try` wraps **all three** write operations (`mkdir`, `write_text`, `write_perfmon_trend_csv`). `test_write_failure_exit_one` asserts `"Traceback" not in output`. | closed |
| T-13-STDOUTESC | Tampering | stdout summary block | medium | mitigate | `cli.py:1160` — the only path that echoes hazard text passes through `_sanitise`. | closed |
| T-13-FMTPARSE | Tampering | `--format` handling | low | mitigate | `PerfmonFormat(StrEnum)` (`:1074-1080`); `test_exit_codes` asserts exit 2 **and** `not (case_dir / "perfmon").exists()`, proving rejection precedes any filesystem access. | closed |
| T-13-WAL | Denial of Service | store lifetime | low | mitigate | `cli.py:1163-1165` `finally: store.close()`. `_case_store`'s own `typer.Exit` paths raise before the store is bound, so no handle leaks. | closed |
| T-13-DOUBLEREAD | Denial of Service | `store.query_events()` | low | mitigate | `cli.py:1125-1126` — a single call whose list feeds both `analyse_mcm` and `analyse_perfmon`. | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above `block_on: high` count toward `threats_open`*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

No `T-13-SC` supply-chain checkpoint applies: this phase adds no external packages
(RESEARCH.md § Package Legitimacy Audit).

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-13-01 | T-13-NETWORK | Nothing in this phase needs network access, and the autouse `_no_network` fixture (`tests/conftest.py:34`) already raises `RuntimeError` on `socket.socket.connect` for every non-`live` test. No additional control is warranted at ASVS L1. | Plan-time disposition (13-01, approved at planning); basis re-confirmed against `conftest.py` at audit | 2026-07-20 |
| AR-13-02 | T-13-TYPECOERCE | **Rationale corrected during audit.** The plan-time basis claimed `float()` inside a `try` "degrades a non-`str` value to `None` without raising" — this is wrong: `perfmon.py:79` catches only `ValueError`, while `float()` on a non-`str`/non-numeric object raises `TypeError`, which would propagate. The accept nevertheless stands on a *different* and stronger basis: `_numeric(value: str)` is called only with `Event.attrs` values, and `models.py:34` types `attrs: dict[str, str]` under Pydantic validation, making the `TypeError` branch unreachable. Recorded with the corrected reasoning so a future audit does not inherit the false premise. | Plan-time disposition (13-02, approved at planning); **rationale replaced** at audit — the disposition stands, its stated basis did not | 2026-07-20 |

Both accepts carry their plan-time disposition forward; neither was newly accepted at audit time.
AR-13-02's *reasoning* was corrected because the original premise was factually wrong — the
outcome is unchanged but the justification is now sound.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-20 | 27 | 27 | 0 | gsd-security-auditor (verify-mitigations mode), orchestrator-spot-checked |

**Audit scope note.** The ASVS L1 short-circuit (skip the auditor when the plan-time register
reports no open threats) was deliberately **not** taken: `threats_open` would have been asserted
from a grep-level pass with no mitigation evidence behind it. The auditor was spawned instead and
verified each control in the implementation.

**Post-verification change accounted for.** Commit `8ff3b2f` removed the always-empty
`PerfmonAnalysis.hazards` field and the renderer's unreachable case-level hazard branch *after*
phase verification passed. The audit explicitly re-traced the three threats that could have
depended on it — T-13-HAZDOS, T-13-DRIFTTRUST, T-13-STDOUTESC — and confirmed all remain intact:
`_CITE_CAP`/`_cited` are `TrendGroup`-scoped and never referenced the removed field; the drift
hazard is reached on both surviving paths (`perfmon.py:619` episode scope, `:531` file scope); and
the CLI still iterates `analysis.groups → group.hazards` and sanitises every message. All four
hazard emitters (`span`, `non_overlap`, `denial_always_zero`, `counter_set_drift`) remain
reachable and rendered.

**Non-blocking observations** (recorded, no threat opened):

1. `perfmon_report.py:130` — `_hazard_table` retains a `heading` parameter now only ever called
   with its default, residue of the branch `8ff3b2f` deleted. Dead parameter, no security effect.
2. `cli.py:1125` `store.query_events()` sits outside the `except OSError` block, so a
   `sqlite3.Error` there would surface as a traceback rather than a sanitised exit. Out of
   register scope — the declared T-13-ERRLEAK vector is the write path, which is covered, and
   `_case_store` already handles open-time sqlite failures. Worth a threat entry in a future
   phase that touches this command.
3. Summary template drift: 13-01/13-02 declare `## Threat Flags: None`, 13-03/05/06 omit the
   section, 13-04 uses a `## Threat mitigations verified` table. Cosmetic inconsistency, not new
   attack surface — every mitigation those summaries claim was verified independently in code.

**Cross-checks.** `uv run pytest tests/test_perfmon.py tests/test_perfmon_report.py
tests/test_cli_perfmon.py tests/test_dssperfmon.py tests/_perfmon_fixtures.py -q` → 83 passed.
Full gate at HEAD, run independently by the orchestrator: `ruff check` clean, `pyright` 0 errors,
`pytest` 630 passed / 8 deselected. All seven **high**-severity mitigations were additionally
spot-checked against source line-by-line by the orchestrator rather than accepted on the
auditor's report.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-20
