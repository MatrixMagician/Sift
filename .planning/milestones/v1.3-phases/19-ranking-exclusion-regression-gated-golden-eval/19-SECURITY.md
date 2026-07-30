---
phase: 19
slug: ranking-exclusion-regression-gated-golden-eval
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-07-28
---

# Phase 19 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

Register origin: **authored at plan time** — all four `19-0*-PLAN.md` files carry a
parseable `<threat_model>` block, so this audit *verifies declared mitigations*
rather than building a register retroactively. ASVS L1 (grep-depth verification),
`security_block_on: high`.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| ingested artefact → `events` table | Untrusted eu-stack dump text enters stored `raw`/`message`, bounded by `MAX_EVENT_LINES=256` / `MAX_EVENT_BYTES=65536` | Attacker-influenced symbol and frame text |
| `EXCLUDED_FROM_RANKING` → `iter_event_summaries` SQL | A module-owned constant becomes SQL parameters | Source-name literals (never caller-supplied) |
| stored event text → terminal | `show events` / `analyze` output reaches an operator's terminal | Attacker-influenced frame text |
| `truth.yaml` on disk → `Truth` model | The eval trust boundary | Golden-case declared figures |
| `eval/thresholds.toml` → `load_thresholds` | The pass/fail authority | Five float floors |
| real capture → committed fixture | A customer-environment capture is reduced and redacted into the repo | Thread blocks, symbols, identifiers |
| eval harness → inference endpoint | **Not crossed** for eu-stack cases (D-19-06/D-19-16), proven by an observed-empty request log | — |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-19-01 | Tampering | `EXCLUDED_FROM_RANKING` → `iter_event_summaries` SQL | medium | mitigate | Verified `store.py:659-668`: only the placeholder count is interpolated (documented `noqa: S608`); every source value is `?`-bound from a module constant, `sorted()` for determinism | closed |
| T-19-02 | Information disclosure | `analyze` reaching `hypothesise()` on an excluded-source-only case | low | accept | No new data class crosses the boundary — same Phase-18 fact block already sent today; `InferenceClient` loopback/RFC1918 guard untouched | closed |
| T-19-03 | Tampering | terminal rendering of eu-stack frame text | low | accept | Pre-existing `render/_util.sanitise` strips C0/DEL/C1 on every DB-sourced render path (T-04-01, Phase 2); this phase adds assertions, not a new writer | closed |
| T-19-04 | Denial of service | one-row probe on a very large case | low | accept | Reads at most one row from a streaming cursor, once per `analyze` | closed |
| T-19-05 | Tampering | `eval/truth.py` loader | high | mitigate | Verified `yaml.safe_load` is the only parse path (`truth.py:76`); module docstring pins the prohibition; `load_truth` unchanged this phase | closed |
| T-19-06 | Tampering | `ExpectEustack` field validation | medium | mitigate | Verified `provenance: Literal["authored", "observed"]` at `truth.py:38` — mandatory, no default; `model_config = ConfigDict(extra="forbid")` independent of `Truth`'s | closed |
| T-19-07 | Spoofing | a fixture masquerading as a legitimate golden case | medium | accept | Inputs are committed, reviewed source at the same trust level as every existing `eval/cases/*/input/`; `provenance` + the single-`observed` test are the compensating controls | closed |
| T-19-08 | Information disclosure | error text from a failed eu-stack case | low | mitigate | Reuses the shipped `sanitise` path in `run_case`'s failure branch; no new formatter | closed |
| T-19-09 | Information disclosure | derived healthy fixture carrying customer-environment identifiers | high | mitigate | Data plane verified clean (see Audit 2026-07-28). Annotation leak found and **remediated this audit**: `eval/cases/eustack-healthy/README.md` no longer records the capture's absolute path | closed |
| T-19-10 | Tampering | `eval/thresholds.toml` as pass/fail authority | medium | mitigate | Verified binary-mode `tomllib` (`thresholds.py:48-49`); `METRIC_KEYS` makes the fifth floor REQUIRED, so a truncated file raises rather than gating on four metrics | closed |
| T-19-11 | Repudiation | a golden case whose declared figures were never measured | medium | mitigate | `test_eustack_healthy_case_scores_pass_offline` fails on any divergent declared figure; a fabricated figure cannot reach a green suite | closed |
| T-19-12 | Denial of service | oversized fixture slowing CI | low | mitigate | Measured 88,701 bytes ≤ 250,000 ceiling, 144 threads ≥ 100 floor | closed |
| T-19-13 | Information disclosure | environment identifiers in copied thread blocks | high | mitigate | Data plane verified clean (see Audit 2026-07-28). Annotation leak found and **remediated this audit**: the capture directory no longer appears in `eustack-hang-pool-warehouse`'s README or fixture header | closed |
| T-19-14 | Repudiation | a synthetic fixture presented as observed evidence | high | mitigate | Verified declarations: `eustack-hang-pool-warehouse` and `-mutated` are `authored`, `eustack-healthy` alone is `observed`; pinned by `test_only_the_healthy_case_is_marked_observed` | closed |
| T-19-15 | Tampering | a fixture authored backwards from the classifier | high | mitigate | `<fixture_authorship_discipline>` forbids consulting the rules file while authoring; every normalised symbol must exist in the source capture; the mutation twin is the second control | closed |
| T-19-16 | Tampering | sensitivity test mutating the shipped rules file | medium | mitigate | Verified `src/sift/rules/eustack_roles.toml` byte-untouched across `7c7f132..HEAD`; the neuter is applied at the `load_rules` seam via `monkeypatch` | closed |
| T-19-17 | Denial of service | deeply nested or oversized fixture stalling the parser | low | accept | Bounded upstream and unchanged: `MAX_EVENT_LINES=256`, `MAX_EVENT_BYTES=65536`, plus a 64 KB fixture cap (measured 38,463 bytes) | closed |
| T-19-SC | Tampering | npm/pip/cargo installs | high | mitigate | Verified `uv.lock` and `pyproject.toml` byte-untouched across `7c7f132..HEAD`; zero packages installed in any of the four plans | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above `workflow.security_block_on` count toward `threats_open`*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| R-19-01 | T-19-02 | The eu-stack-only fall-through sends the already-shipped Phase-18 fact block to the configured localhost endpoint — the same data `sift analyze` sends today for any case containing eu-stack events. No new data class crosses the boundary. | Plan-time disposition (19-01) | 2026-07-27 |
| R-19-02 | T-19-03 | Terminal control-character stripping is already mitigated upstream by `render/_util.sanitise` (T-04-01, Phase 2) and unchanged here. | Plan-time disposition (19-01) | 2026-07-27 |
| R-19-03 | T-19-04 | The one-row probe is strictly cheaper than the `query_events()` alternative it replaces and runs once per `analyze`. | Plan-time disposition (19-01) | 2026-07-27 |
| R-19-04 | T-19-07 | Golden-case inputs are committed, reviewed source at the same trust level as every existing `eval/cases/*/input/` file; no new trust boundary is introduced. | Plan-time disposition (19-02) | 2026-07-27 |
| R-19-05 | T-19-17 | Parser bounds (`MAX_EVENT_LINES`, `MAX_EVENT_BYTES`) predate this phase and are unchanged; the fixture cap is an additional bound. | Plan-time disposition (19-04) | 2026-07-27 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-28 | 18 | 18 | 0 | /gsd-secure-phase (orchestrator, ASVS L1) |

### Audit 2026-07-28 — findings and remediation

Two `high` threats were initially classified **OPEN**: their declared mitigations were
contradicted by the committed artefacts.

Fixture **content** was verified clean at the outset — a scan of all three
`eval/cases/eustack-*/input/threaddump.txt` for IPv4 literals, `/home/*` and
`/Users/*` paths, e-mail addresses, and `.com/.net/.local/.internal/.corp`
hostnames returned zero matches. The failure was confined to the **provenance
annotations**:

| File | Leaked | Mitigation claim contradicted |
|------|--------|-------------------------------|
| `eval/cases/eustack-healthy/README.md:12` | `/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/` — local username **and** capture identifier | T-19-09: "the README quotes the invocation with a **placeholder** input path" |
| `eval/cases/eustack-hang-pool-warehouse/README.md:19` | `~/Downloads/iserver1_stacks_1-minute_diff/` | T-19-13: "…is **never written into this repository**" — asserted two lines below the path |
| `eval/cases/eustack-hang-pool-warehouse/input/threaddump.txt:2` | same directory, alongside "(filename redacted — carries an environment identifier)" | Redacted the filename while writing the directory carrying the identifier |

Both leaks entered in Phase 19 commits (`5028e0b`, `d691c5b`), so they are
phase-introduced, not inherited.

**Remediation applied** (documentation-only; no fixture thread blocks, no test
logic, no source changed): all three paths replaced with a redaction note that
preserves the `160739` dump disambiguator — which carries no identifier — and
directs the reader to supply the path locally when re-deriving.

Post-remediation verification:
- `grep -rn "iserver1\|/home/oliverh" eval/` → no matches
- `uv run pytest` → 834 passed, 8 deselected
- `uv run ruff check` → clean
- Size caps still hold: 38,463 / 38,463 / 88,701 bytes (≤ 64 KB, ≤ 250 KB)

Both threats moved OPEN → CLOSED on that evidence. `threats_open: 0`.

### Out of scope — noted, not owned by this phase

- `docs/GETTING-STARTED.md:106` references `iserver1_stacks.txt`. It predates
  Phase 19 and was not introduced or touched here; recorded so it is not lost.
- `uv run pyright` reports 31 errors, all in `tests/test_cli_eustack.py`,
  `tests/test_eustack_progression.py`, `tests/test_eustack_report.py`
  (`reportUnknownMemberType`, `reportAttributeAccessIssue`, `reportPrivateUsage`).
  All three were last modified by Phase 17 commits (`2f7f90e`, `5134e9c`,
  `79a5ef1`) and are untouched by Phase 19 — pre-existing type-gate debt, not a
  security finding, but it does mean the project-wide "pyright clean" bar in
  CLAUDE.md is currently unmet.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
