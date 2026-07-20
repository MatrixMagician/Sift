---
phase: 14
slug: perfmon-facts-into-sift-analyze-golden-eval-case
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-07-20
---

# Phase 14 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Register authored at plan time (all 5 PLAN files carried a parseable `<threat_model>` block).
> ASVS L1, block_on: high — verified at grep-depth (L1); no auditor spawn required for a
> clean, plan-time-authored register at L1.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| customer CSV/log → case.db → analyser | untrusted diagnostic text enters the pipeline | untrusted counter names, timestamps, hazard text |
| perfmon sample text → correlator | untrusted counter/timestamp values, disclosure channel added | untrusted numeric/counter values |
| customer CSV counter names / hazard messages → triage prompt | untrusted text interpolated into the fact block the model reads | untrusted prose (injection surface) |
| rendered fact block → LLM prompt | counter-derived text reaches the model; citation gate controls what it may cite back | untrusted text + citable event_ids |
| golden truth.yaml → eval loader | project-authored truth files loaded for the golden gate | trusted (project-authored) YAML |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-14-01 | Tampering | fixture builders in tests/_perfmon_fixtures.py | low | mitigate | builders write strictly beneath pytest `tmp_path`; no caller-chosen destination (`_perfmon_fixtures.py:11,49-50`) | closed |
| T-14-02 | Information disclosure | committed fixture content | low | accept | synthetic/redacted host + counters only; no secrets — see Accepted Risks | closed |
| T-14-03 | Information disclosure | `_unattributed_group` provenance keys | low | mitigate | inherits `_hazard_unplaceable_samples` citing only event_ids; `_RESERVED_ATTRS` exclusion preserved (`perfmon.py:22,304,511`) | closed |
| T-14-04 | DoS | one event_id per untimestamped row inflating the hazard | low | mitigate | `_CITE_CAP=10` cap reused verbatim; true total reported (`perfmon.py:97,438`) | closed |
| T-14-05 | Tampering | prompt injection via crafted counter name / hazard message in `render_perfmon_facts` | high | mitigate | `sanitise()` on every log/CSV-derived value before interpolation; injection test asserts `sanitise(injection) in block` (`perfmon_facts.py:116`; `test_perfmon_facts.py:238-250`) | closed |
| T-14-06 | Tampering | model authoring a perfmon figure | high | mitigate | no-digit guard — versioned fragment carries zero ASCII digits; every figure read verbatim from `analyse_perfmon` (`test_perfmon_facts.py:256`, D-06 guard) | closed |
| T-14-07 | Tampering | model fabricating a perfmon figure or citation | high | mitigate | `cited ⊆ prompted ⊆ store` gate; printed perfmon ids unioned into `prompted_ids`, fabricated id FLAGGED (`hypothesise.py:127` `_apply_perfmon_block`; `test_perfmon_analyze.py:298,325`) | closed |
| T-14-08 | Tampering | prompt-drift regressing the shipped no-data baseline | high | mitigate | 4-combination byte-identity guard freezes pre-phase neither/MCM-only hashes; 4 distinct hashes asserted (`test_perfmon_analyze.py:270-295`, `_NEITHER_PROMPT_HASH`) | closed |
| T-14-09 | Tampering | truth.yaml custom-tag RCE vector | low | mitigate | `load_truth` uses `yaml.safe_load` only; custom tags refused (`eval/truth.py:3,40,43`) | closed |
| T-14-10 | Repudiation | a vacuous gate silently passing a regression | high | mitigate | citation-sensitivity test proves the gate turns red when perfmon injection is removed (`test_eval_cases.py:348` `test_perfmon_denial_citation_validity_is_perfmon_sensitive`) | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-14-01 | T-14-02 | Committed perfmon-denial fixtures hold synthetic/redacted host + counter values only — no secrets. Reference host string is already public in previously shipped fixtures. | O Hingst | 2026-07-20 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-20 | 10 | 10 | 0 | gsd-secure-phase (L1 grep-depth) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-20
