---
phase: 06-renderers-kb-retrieval
fixed_at: 2026-07-18T00:00:00Z
review_path: .planning/phases/06-renderers-kb-retrieval/06-REVIEW.md
iteration: 1
findings_in_scope: 10
fixed: 10
skipped: 0
status: all_fixed
---

# Phase 6: Code Review Fix Report

**Fixed at:** 2026-07-18
**Source review:** `.planning/phases/06-renderers-kb-retrieval/06-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 10 (fix_scope=all — CR-01, WR-01..05, IN-01..04)
- Fixed: 10
- Skipped: 0

**Process notes:**
- All work happened in an isolated git worktree on temp branch
  `gsd-reviewfix/06-<pid>`, fast-forwarded into the phase branch on cleanup
  (per the project convention), with a recovery sentinel for crash-safety.
- Each finding was applied TDD-style: a regression test was written and confirmed
  RED against the unfixed code (via `git stash` of the fix), then GREEN after the
  fix, then the full gate (`uv run ruff check`, `uv run pyright`,
  `uv run pytest`) was run clean before committing. Each finding is ONE atomic
  green commit (`fix(06-review): <id> …`) containing test + fix — a RED-only
  commit was deliberately avoided so every commit keeps the gate green.
- Adversarial C1/bidi test payloads (IN-02) were built from `\u` escape
  sequences, never raw bytes, and the source files were scanned to confirm zero
  raw hazardous bytes landed on disk.
- Baseline before fixes: 412 passed. After all fixes: 424 passed, 3 deselected
  (the 3 deselected are the pre-existing `@pytest.mark.live` PDF tests).

## Fixed Issues

### CR-01: `sift analyze --kb <dir>` crashes with unhandled `sqlite3.OperationalError` on a Markdown-free KB dir

**Files modified:** `src/sift/store.py`, `tests/test_kb_analyze.py`
**Commit:** fc3db8e
**Applied fix:** Root-cause guard in `store.knn_kb_chunks` — a missing
`kb_vectors` table (index_kb short-circuits before creating it when the `--kb`
dir has no indexable `*.md`) is caught and treated as an empty index, so
`retrieve_kb` returns `[]` instead of letting a raw `OperationalError` escape the
`analyze` handler (which only catches `httpx.HTTPError`/`ValueError`). Test:
`analyze demo --kb <dir-with-only-a-.txt> --no-label` exits cleanly.

### WR-01: `report --format md|json --out <path>` leaks a raw traceback on a write failure

**Files modified:** `src/sift/cli.py`, `tests/test_cli_report.py`
**Commit:** 8f19174
**Applied fix:** Wrapped `out.write_text(...)` in `try/except OSError`, mapping
it to a sanitised exit-1 message ("cannot write report to …"), mirroring the PDF
branch and honouring ADR 0007. Test: `--out` at a missing-parent path exits 1
with a helpful message, no `result.exception`.

### WR-02: `render_pdf` misreports every `OSError` (incl. an unwritable `--out`) as "install sift[pdf] and pango"

**Files modified:** `src/sift/render/pdf.py`, `src/sift/cli.py`, `tests/test_render_pdf.py`
**Commit:** 60e9d4c
**Applied fix:** `render_pdf` now renders to bytes (`write_pdf()` with no target)
so the pango/harfbuzz `OSError` is confined to the render step and mapped to
`PdfExtraMissing`; the file write (`out.write_bytes`) happens separately and its
`OSError` propagates. `cli.report` gained a dedicated `except OSError` branch
reporting a write failure, distinct from the missing-extra message. The test
fake weasyprint was updated to return bytes. Tests: a write-target error surfaces
as `OSError` (not `PdfExtraMissing`); the CLI reports "cannot write report", not
"pango".

### WR-03: a hard-degraded run (zero rows, `triage_raw` persisted) makes `report` exit 1 "run analyze first"

**Files modified:** `src/sift/cli.py`, `src/sift/render/markdown.py`, `tests/test_cli_report.py`
**Commit:** 4db0a34
**Applied fix:** `report` now gates on `triage_created_at` (did analyze run)
instead of on `query_hypotheses()` being non-empty, so a hard-degraded run is
reportable. `render_markdown` emits a fenced, byte-capped "Raw model output
(unvalidated)" section when `triage_raw` is present (the DEGRADED banner already
fires on `triage_degraded`). `show hypotheses` no longer claims analyze never ran
when raw output was persisted — it points the operator at `report`. This also
resolves IN-04 (the redundant second `query_hypotheses` guard is gone). Tests:
hard-degraded `report` exits 0 with DEGRADED + raw; `show hypotheses` mentions
degradation, not "run analyze first".

### WR-04: model/DB-sourced fields rendered without HTML/Markdown escaping (markdown-injection + PDF `<img>` → ValueError traceback)

**Files modified:** `src/sift/render/markdown.py`, `src/sift/cli.py`, `tests/test_render_markdown.py`, `tests/test_render_pdf.py`
**Commit:** 2a2154c
**Applied fix:** Added a single `_field`/`_escape` helper (sanitise +
backslash-escape Markdown structure `\ ` `` ` `` `* _ # [ ] |` + html-escape
`& < >`) applied to every inline model/DB field (title, confidence, narrative,
reasoning, contradicting evidence, next steps, cluster name, severity,
provenance, timeline, signals, run metadata). `_link_citations` now escapes prose
in the same pass while preserving `[evt:hex]` anchor links. Added a `ValueError`
branch to `cli.report`'s PDF handler so a blocked-egress fetch (from an injected
`<img>`) is a clean exit 1, never a traceback. The existing Pitfall-2 test was
updated to the new (backslash-escaped, still non-linking) rendering of a
cited-but-absent id. Test: injected `<img>`/`<script>`/`# heading`/`[link]` are
neutralised while the genuine citation link still renders.

### WR-05: evidence-appendix anchor id neither sanitised nor escaped

**Files modified:** `src/sift/render/markdown.py`, `tests/test_render_markdown.py`
**Commit:** f6fe975
**Applied fix:** The appendix HTML anchor (`<a id="evt-{eid}">`) is emitted only
when `eid` matches `[0-9a-f]{16}` (the same shape `_link_citations` gates on); a
non-conforming id (possible in a tampered/shared `case.db`) renders as an inert,
escaped code span with no anchor, so it can never break out of the id attribute.
Test: a cited event whose stored `event_id` is `"><b>evil` produces no raw
`id="evt-…"` attribute and no `<b>` break-out.

### IN-01: `normalise_for_determinism` drops any string value beginning with `/`

**Files modified:** `src/sift/render/json_out.py`, `tests/test_report_determinism.py`
**Commit:** 633c953
**Applied fix:** The absolute-path strip now fires only when the KEY names a path
(`*path*`/`*file*`/`*dir*`); a content value that merely starts with `/` under a
non-path key (a signature/narrative quoting `/etc/…`) is retained. This matches
the ADR 0008 promise and stops the helper masking a genuine run-to-run difference
in such a field. The existing "drops exactly the D-06 fields" test still passes
(its `out_path` key is path-named). Test: a `/`-leading value under `signature`
/`narrative` is retained; `generated_at` still goes.

### IN-02: JSON report not sanitised for C1/bidi terminal-injection bytes

**Files modified:** `src/sift/render/json_out.py`, `tests/test_render_json.py`
**Commit:** 4a53e5c
**Applied fix:** `render_json` now dumps with `ensure_ascii=True`, so every
non-ASCII code point (including C1 controls 0x80-0x9F and Cf bidi/format chars) is
`\u`-escaped — `cat report.json` is terminal-safe, output stays deterministic,
and a JSON parser round-trips the escapes back (fidelity preserved). This is the
"fix rather than document" resolution the reviewer offered. The canonical-dump
test was updated to `ensure_ascii=True`. Test: a timeline summary carrying U+009B
and U+202E emits no raw hazardous byte, emits the `\u` escapes, and round-trips.

### IN-03: `index_kb` follows symlinks under `--kb` with no trust-boundary check

**Files modified:** `src/sift/pipeline/retrieve.py`, `tests/test_kb_retrieval.py`
**Commit:** c8f0621
**Applied fix:** The KB walk skips symlinked files (`path.is_symlink()`) for
parity with `ingest`'s trust boundary, so a symlinked runbook (`x.md → /etc/…`)
is never read and embedded into the prompt; this also avoids directory-symlink
loops (a symlinked `.md` is never indexed). Test: a symlinked `link.md` pointing
outside the KB dir is not indexed while a real `real.md` is.

### IN-04: `report` (md path) queries `query_hypotheses()` twice

**Files modified:** (none — resolved as a side effect of WR-03)
**Commit:** 4db0a34 (WR-03)
**Applied fix:** The reviewer flagged this as optional and noted the run-meta gate
would also fix WR-03's mis-messaging. WR-03's fix replaces the emptiness guard
(`if not store.query_hypotheses()`) with a run-meta check
(`store.get_meta("triage_created_at") is None`), so `report` now calls
`query_hypotheses()` exactly once (inside the renderer). No separate commit was
needed.

---

_Fixed: 2026-07-18_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
