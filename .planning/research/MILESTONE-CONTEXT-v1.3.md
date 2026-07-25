# v1.3 milestone context for researchers (measured evidence, not assumptions)

**Read this before researching. The numbers below are measured from the real reference
capture, not estimated. Do not contradict them; research around them.**

## What Sift already has (DO NOT re-research)

Sift is a fully local, offline incident-triage CLI for MicroStrategy / Strategy Intelligence
Server diagnostics. Python 3.12+, `uv`, SQLite + sqlite-vec case store, local OpenAI-compatible
LLM endpoint only (llama.cpp `llama-server` / Lemonade). Shipped and validated:

- **Five adapters**: `genericlog`, `journald`, `dsserrors`, `eustack`, `dssperfmon`.
- **`eustack` adapter already ingests native eu-stack thread dumps.** Confirmed against the
  reference capture: sniff 0.8, 3,903 events, 22 fallback bytes of 2,521,771 (99.999% coverage).
  **Ingestion is solved. v1.3 is purely the analysis layer above it.**
- **v1.1 MCM analysis** — deterministic denial-episode detection, memory breakdown, graded flags,
  attribution, `sift mcm` report + CSV, facts into `sift analyze` as cited evidence.
- **v1.2 perfmon correlation** — `dssperfmon` PDH-CSV adapter, `EXCLUDED_FROM_RANKING` store seam,
  episode lead-in annotation, `sift perfmon` report + CSV, facts into `sift analyze`.
- Pipeline: ingest → template dedup (regex masking) → embed → HDBSCAN cluster → salience →
  KB retrieve → hypothesise → render. Prompts are versioned `sift/prompts/*.md` files.

## The load-bearing architectural boundary

**Deterministic core computes every figure; the LLM only narrates it.** Every number in a report
is COMPUTED before generation and handed to the model as citable evidence. `cited ⊆ prompted ⊆
store`. Anti-hallucination tests prove a planted wrong figure never reaches the prompt. Fact
templates contain zero authored digits. This is not negotiable and it constrains every
recommendation you make: anything requiring the model to *derive* a classification or a metric is
out of scope by construction.

## Measured facts about the reference capture

`/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/` — two native eu-stack dumps of the same
Intelligence Server process (PID 1363967), captured 60 seconds apart (16:07:39 and 16:08:37).

Format is native elfutils `eu-stack` output:

```
PID 1363967 - process
TID 1363967:
#0  0x0000714e2614691a __sigtimedwait
#1  0x0000714e26145fbc sigwait
#2  0x0000000000410844 MExec::Controller_Impl::ProcessExternalRequestsUntilStopped()
...
```

**No lock ownership, no blocked-on info, no per-thread timestamps, no thread names** — only TID,
frame index, instruction address, and demangled symbol. This is a hard constraint: any technique
requiring `waiting to lock <0x...>` / monitor-owner edges (i.e. JVM `jstack` deadlock detection)
is **not applicable**. Sift cannot build a wait-for graph from this input.

Measured structure:

| Metric | Dump A | Dump B |
|---|---|---|
| Threads | 3,902 | 3,903 |
| Frames | 38,493 | 38,406 |
| Distinct stack signatures | 93 | — |
| Common TIDs across both | 3,893 | |
| TIDs only in A (exited) | 9 | |
| TIDs only in B (new) | 10 | |
| **Identical stack after 60 s** | **3,849 (98.9% of common)** | |
| Changed stack after 60 s | 44 | |

Stack depth histogram (A): depth 10 → 1,974 threads; 9 → 1,115; 8 → 258; 6 → 219; 19 → 158.

### THE CRITICAL FINDING — the intuitive mechanism is dead

**"Identical stack after 60 s = stuck thread" flags 98.9% of threads on a demonstrably HEALTHY,
near-idle server.** It is not a weak signal, it is an inverted one. An idle Intelligence Server
parks thousands of pool workers in `pthread_cond_timedwait` indefinitely; they are *supposed* to
look identical. Any research output that recommends stack-diffing as the primary hang mechanism
will be rejected.

**Composition, not motion, is the signal.** 3,902 threads collapse to 93 signatures, and the top
signatures self-label by their deepest MicroStrategy frame:

| Threads | % | Deepest MicroStrategy frame | Interpretation |
|---|---|---|---|
| 1,715 | 44% | `MSIQTask::GetNextPreferredJob` (under `Semaphore::SmartLock::WaitForResource`) | idle job-queue worker, waiting for work |
| 1,110 | 28% | `MSIEvaluationTask::Run` (under `EventImpl::Wait`) | idle evaluation worker |
| 247 | 6% | `MSICommandQTask::GetNextCommand` | idle command queue |
| 212 | 5% | `CrossProcessEventImpl::WaitOnPipe` (under `__select`) | idle IPC |
| 110 | 3% | `ThreadPoolImpl::GetNextRunnable` | idle generic pool |
| 80 | 2% | `ParallelBursting::ThreadPool::WorkLoop` | idle bursting pool |
| **79** | 2% | `CDSSQueryEngine::WaitUntilFinished` | **blocked on the warehouse** |
| **78** | 2% | `curl_multi_poll` (under `Curl_poll`) | **blocked on external HTTP** |
| 38 | 1% | `boost::asio::detail::scheduler::run` | idle asio reactor |
| 30 | 1% | `CDSSReportCacheManager::RunBackupTask` | idle cache backup |

The 44 threads that *did* change stack are where real work lives — observed frames include
`_shi_allocBlock`/`_shi_allocVar`/`MemAllocPtr` (allocation), `CDSSSubsetEngine::GenCube` /
`MCE::GetBaseRIbyID` (cube generation), `MSynch::RWLock::ReadSmartLock` under
`__GI___lll_lock_wake` (lock acquisition), `pthread_rwlock_rdlock` under
`FeatureFlagMgr::IsFeatureEnabled`, `SharedMemoryImpl::WaitOnSemaphore` (shared-memory wait).

### The evidence gap you must respect

**The reference capture is a healthy, near-idle server** — roughly 3,400 of 3,902 threads are
parked pool workers with no work. It can prove an analyser does not raise false alarms. It
**cannot** prove hang detection works. No real hung-server capture is available. v1.3's positive
eval cases will be synthetic fixtures encoding known hang shapes, explicitly labelled as authored.

## What v1.3 will build (scope is already decided — research informs HOW, not WHETHER)

1. Thread-role taxonomy as a **versioned rules file** (hand-curated frame-pattern → role/subsystem
   table, sibling to `sift/prompts/*.md`), classifying each thread idle-parked /
   blocked-on-external / blocked-on-lock / running / **unclassified**. Unknown frames are reported
   as unclassified, never guessed. Editable without touching Python.
2. Deterministic saturation & contention analysis — per-pool occupancy (busy vs parked),
   lock-contention convergence, external-wait concentration, stack-signature collapse.
3. Multi-dump progression signals — full analysis from 1 dump; 2+ additionally give per-signature
   population deltas and which threads advanced. Degrades loudly, never silently.
4. `sift eustack <case>` standalone report + CSV, working with **no DSSErrors log present**
   (mirrors the `sift mcm` / `sift perfmon` contract).
5. Eu-stack facts into `sift analyze` as cited-not-authored evidence (versioned zero-digit
   `eustack_facts.md`, byte-identical-additive when absent).
6. Decide whether eu-stack thread events belong in dedup/embed/cluster/salience.
   `EXCLUDED_FROM_RANKING` (`src/sift/store.py:335`) currently holds only `dssperfmon`; eu-stack's
   3,903 events per dump currently DO flow through ranking.
7. Regression-gated golden eval — real healthy capture as negative case, synthetic hang shapes as
   positives.
8. SEED-002 / DET-01 — reuse persisted embedding vectors instead of re-embedding every `analyze`,
   closing the ADR 0014 embedding batch-composition determinism exposure.

## Hard constraints on every recommendation

- **Zero network egress** at runtime except the configured localhost inference endpoint. Never
  call the network in tests.
- **Boring technology only**: stdlib, httpx, Pydantic, sqlite-vec, scikit-learn, Typer,
  zstandard. Anything beyond these needs explicit justification and will probably be rejected.
- **Determinism**: `event_id = sha256(source_file, byte_offset)[:16]`; identical case + config +
  model + seed → byte-identical JSON modulo timestamps.
- **British English** in docs and user-facing strings. Type hints everywhere.
- Adding an adapter must require zero changes outside a new module + registration — but note
  **v1.3 adds no adapter**.
- Quality gate: `ruff check`, `pyright`, `pytest` all clean is part of "done".
