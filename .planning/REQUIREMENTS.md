# Requirements: Sift — v1.3 EU-Stack Hang & Slowdown Diagnosis

**Defined:** 2026-07-25
**Core Value:** Turn a directory of raw diagnostics into a structured, evidence-cited triage report
— entirely offline, with every claim citing verifiable event IDs.

**Milestone goal:** Turn eu-stack thread dumps into a deterministic thread-state and saturation
analysis that explains why the Intelligence Server is slow or hung — working with or without an
accompanying DSSErrors log.

**Grounding:** ingestion is already solved. The shipped `eustack` adapter parses the reference
capture at 99.999% coverage (sniff 0.8, 3,903 events, 22 fallback bytes of 2,521,771). Every
requirement below is analysis *above* ingestion. Full measured evidence in
`.planning/research/MILESTONE-CONTEXT-v1.3.md`; synthesis in `.planning/research/SUMMARY.md`.

---

## v1.3 Requirements

### Thread classification

- [x] **EUS-01**: User gets every thread in a dump classified as `idle-parked`,
  `blocked-on-external`, `blocked-on-lock`, `running`, or `unclassified`, driven by a versioned
  rules file that can be edited without touching Python

- [x] **EUS-02**: User sees unrecognised frames counted and reported as `unclassified` — never
  silently bucketed into a known role and never guessed

### Saturation and contention

- [x] **EUS-03**: User sees per-pool occupancy so an idle pool of parked workers reads as healthy
  rather than saturated

- [x] **EUS-04**: User sees threads converging on a lock-acquisition path, always reported as
  ownership-blind

- [x] **EUS-05**: User sees external-wait concentration split by dependency (warehouse, HTTP, IPC)
- [x] **EUS-06**: User sees the thread population collapsed to distinct stack signatures, ranked by
  thread count

### Multi-dump progression

- [x] **EUS-07**: User gets full analysis from a single dump, and per-signature population deltas
  when two or more dumps are present

- [x] **EUS-08**: User sees dumps ordered without invented timestamps, with the ordering basis
  stated and unresolvable ordering flagged loudly rather than assumed

### Reporting and integration

- [x] **EUS-09**: User runs `sift eustack <case>` to get a deterministic report plus CSV export,
  working with no DSSErrors log present in the case

- [x] **EUS-10**: User sees eu-stack figures inside `sift analyze` as cited evidence, with the
  prompt byte-identical to today when a case contains no eu-stack data

- [x] **EUS-11**: Eu-stack thread events stop competing in dedup/embed/cluster/salience while
  remaining individually citable

- [ ] **EUS-12**: A regression-gated golden eval covers both the real healthy capture (must not
  report a hang) and synthetic hang fixtures (must)

### Determinism

- [ ] **DET-01**: User re-running `sift analyze` on an unchanged case reuses persisted embedding
  vectors instead of re-embedding, with the reuse/embed split reported

---

## Decisions folded into these requirements

Recorded here because they were settled during scoping and must not be silently re-litigated
during planning. Each needs an ADR in `docs/decisions/`.

| Decision | Rationale |
|----------|-----------|
| Thread roles come from a hand-curated versioned rules file, never LLM classification | Preserves the deterministic-core-vs-LLM boundary that v1.1/v1.2 established: figures are COMPUTED, the model only narrates. An LLM-authored classification would be un-citable and non-deterministic. |
| Rules file is TOML, not Markdown tables or YAML | Reached independently by two researchers. `\|` is the Markdown table delimiter and `operator\|\|` is a real C++ symbol; TOML literal strings need zero escaping for `<`, `>`, `::`, `&`. Reuses stdlib `tomllib` already in `config.py` — no new dependency. |
| Classification reads `Event.raw`, not `Event.message` | `adapters/eustack.py:150-152` caps `message` at `CONDENSED_FRAMES = 5`; the classifying frame sits 8–19 deep. Reached independently by two researchers. |
| Classification keys on the enclosing application frame, not the leaf alone | Leaf frames give the mechanism (`pthread_cond_timedwait`); the enclosing frame gives the role. A leaf-only rules file misclassifies every idle pool as "blocked" — the 98.9% false positive one level down. |
| A knob change (`embeddings.context` / `batch_size` / `max_input_chars`) does NOT invalidate reused vectors; an explicit `--re-embed` applies it | Not invalidating is precisely what makes re-runs reproducible and closes the ADR 0014 exposure. Invalidating would re-embed under a new batch layout on the first run after any knob change — reopening the hysteresis the seed exists to eliminate. Model or dimension change still invalidates. |
| EUS-11 lands only after EUS-09 and EUS-10 ship | Eu-stack events currently produce working clusters and hypotheses for eu-stack-only cases. Removing them from ranking before the replacement exists would open a regression window. Sequencing is a requirement, not a preference. |
| Exclusion stays a property of source kind, with no composition-dependent middle option | The D-07 principle already governing this seam (`store.py:333-334`). Excluding only when another ranked source is present would make output depend on case composition — a determinism hazard. |

---

## Deferred to v1.4+

Genuine capability, deliberately out of this milestone.

| Requirement | Reason |
|-------------|--------|
| **EUSV2-01**: Cross-referencing eu-stack thread state against MCM denial episodes and perfmon counters | The single-source analysis must prove itself first; correlation is a milestone of its own, mirroring how v1.2 followed v1.1. |
| **EUSV2-02**: `/proc/<tid>/stat` state codes alongside eu-stack frames | A genuinely orthogonal signal (running vs sleeping vs uninterruptible), but requires a capture-pipeline change outside this milestone's ingestion format. |
| **EUSV2-03**: Graded saturation thresholds ("N% busy = warning") | No authoritative source exists for defensible numeric thresholds; research explicitly declined to invent them. Needs validation against real incident captures first. |
| **PERFV2-01/02/03** | Carried from v1.2: recovery-trend, multi-host correlation, perfmon-only anomaly detection. |

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| **Deadlock detection** | **Permanent non-goal, not deferred work.** eu-stack output carries no monitor-ownership edges, so a wait-for graph cannot be constructed at all. JVM `jstack` can only do this because the JVM records ownership. Sift must never emit the word "deadlock"; lock findings are always ownership-blind. |
| Stack-diff "identical after N seconds = stuck thread" as a hang mechanism | Measured at 98.9% false-positive on a healthy server (3,849 of 3,893 common TIDs). Idle pool workers park in `pthread_cond_timedwait` by design. Superseded by composition-based classification. |
| Per-TID causal narratives across dumps | TID reuse is measured, not hypothetical (9 exited / 10 new in 60 s on an idle server), and eu-stack carries no thread start time or name. Progression is expressed as per-signature population deltas; same-TID persistence is only used gated to non-idle buckets. |
| LLM-authored thread classification | Would make the classification itself un-citable and non-deterministic, inverting the load-bearing boundary. |
| Live/streaming stack capture | v1 is batch analysis of collected artefacts; unchanged from v1.0. |
| Symbol resolution / re-demangling of stripped binaries | Sift analyses what the capture contains. Absent symbols degrade to `unclassified` (EUS-02), never guessed. |

---

## Known evidence gap

The reference capture is a **healthy, near-idle server** — roughly 3,400 of 3,902 threads are
parked pool workers. It can prove the analyser does not raise false alarms (EUS-12 negative case).
It **cannot** prove hang-detection recall. No real hung-server capture exists.

Positive eval cases are therefore synthetic and must be labelled as authored, not observed. The
classic failure mode — writing fixtures to match the detector, so the test proves only that the
code runs — is a named risk in `.planning/research/PITFALLS.md` and EUS-12 must guard against it.
A real hung-server capture, if one is ever obtained, upgrades this from synthetic to observed.

---

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| EUS-01 | Phase 15 | Complete |
| EUS-02 | Phase 15 | Complete |
| EUS-03 | Phase 16 | Complete |
| EUS-04 | Phase 16 | Complete |
| EUS-05 | Phase 16 | Complete |
| EUS-06 | Phase 16 | Complete |
| EUS-07 | Phase 17 | Complete |
| EUS-08 | Phase 17 | Complete |
| EUS-09 | Phase 17 | Complete |
| EUS-10 | Phase 18 | Complete |
| EUS-11 | Phase 19 | Complete |
| EUS-12 | Phase 19 | Pending |
| DET-01 | Phase 20 | Pending |

**Coverage: 13/13 requirements mapped to exactly one phase each.** No orphans, no duplicates.

Phase-to-requirement view:

| Phase | Requirements |
|-------|--------------|
| 15 — Thread-Role Taxonomy & Rules File | EUS-01, EUS-02 |
| 16 — Saturation, Contention & Signature Collapse | EUS-03, EUS-04, EUS-05, EUS-06 |
| 17 — Multi-Dump Progression & `sift eustack` Report + CSV | EUS-07, EUS-08, EUS-09 |
| 18 — Eu-Stack Facts into `sift analyze` | EUS-10 |
| 19 — Ranking Exclusion & Regression-Gated Golden Eval | EUS-11, EUS-12 |
| 20 — SEED-002 Embedding Vector Reuse | DET-01 |
