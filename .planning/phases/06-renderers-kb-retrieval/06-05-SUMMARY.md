---
phase: 06-renderers-kb-retrieval
plan: 05
subsystem: reporting
tags: [pdf, weasyprint, markdown, renderer, zero-egress, optional-extra, cli]

# Dependency graph
requires:
  - phase: 06-renderers-kb-retrieval
    plan: 01
    provides: "render_markdown (MD body reused for the PDF), render/_util.PdfExtraMissing, sift report --format pdf lazy-import branch, tests/_report_fixtures.build_analysed_case"
provides:
  - "src/sift/render/pdf.py::render_pdf (import-guarded MD->HTML->WeasyPrint, egress-blocked)"
  - "pyproject [project.optional-dependencies] pdf (markdown + weasyprint, pinned)"
  - "sift report --format pdf --out r.pdf renders a self-contained PDF (REPT-04)"
affects: [06-04]

# Tech tracking
tech-stack:
  added:
    - "markdown==3.10.2 (pdf extra only)"
    - "weasyprint==69.0 (pdf extra only)"
  patterns:
    - "Optional feature behind an opt-in extra: heavy/system-dep libs imported lazily inside the function, core install stays system-dep-free (ADR 0002)"
    - "Zero-egress defence-in-depth: self-contained HTML (inline <style>, no <img>) AND a rejecting url_fetcher — egress impossible by content and by fetcher (D-09)"
    - "Both failure modes (extra absent ImportError, pango absent OSError) map to one helpful PdfExtraMissing message, never a traceback (D-10, Pitfall 5)"

key-files:
  created:
    - src/sift/render/pdf.py
    - tests/test_render_pdf.py
  modified:
    - pyproject.toml
    - uv.lock

key-decisions:
  - "url_fetcher is the stable plain-callable form (A4), module-level so tests can spy it; self-contained HTML means it should never actually fire"
  - "Real WeasyPrint render test gated @pytest.mark.live so the default socket-blocked suite needs no pango/markdown/weasyprint; egress + missing-extra paths run by default via injected fakes / forced ImportError"

requirements-completed: [REPT-04]

coverage:
  - id: D-08
    description: "render_pdf renders the Markdown report to PDF via markdown -> HTML -> weasyprint.write_pdf, reusing render_markdown"
    requirement: "REPT-04"
    verification:
      - kind: unit
        ref: "tests/test_render_pdf.py#test_render_pdf_hands_self_contained_html_to_weasyprint"
        status: pass
      - kind: live
        ref: "tests/test_render_pdf.py#test_render_pdf_live_writes_real_pdf_without_external_fetch"
        status: deferred
    human_judgment: false
  - id: D-09
    description: "External URL fetching disabled: self-contained HTML (no <img>/http refs, only #evt- anchors) + rejecting url_fetcher"
    requirement: "REPT-04"
    verification:
      - kind: unit
        ref: "tests/test_render_pdf.py#test_render_pdf_url_fetcher_blocks_every_url"
        status: pass
      - kind: unit
        ref: "tests/test_render_pdf.py#test_render_pdf_hands_self_contained_html_to_weasyprint"
        status: pass
    human_judgment: false
  - id: D-10
    description: "Missing extra / pango absent -> helpful PdfExtraMissing, CLI exit 1, no traceback (not Typer usage exit 2)"
    requirement: "REPT-04"
    verification:
      - kind: unit
        ref: "tests/test_render_pdf.py#test_render_pdf_missing_extra_raises_pdfextramissing"
        status: pass
      - kind: unit
        ref: "tests/test_render_pdf.py#test_report_pdf_missing_extra_exits_one_no_traceback"
        status: pass
    human_judgment: false

# Metrics
duration: 20min
completed: 2026-07-18
status: complete
---

# Phase 6 Plan 05: Optional PDF Report Summary

**`sift report --format pdf --out r.pdf` renders the Markdown triage report to a self-contained, print-quality PDF via WeasyPrint behind the opt-in `sift[pdf]` extra — with URL fetching disabled (zero-egress by content and by a rejecting fetcher) and a single helpful error when the extra or its pango system libraries are absent (never a traceback).**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-07-18
- **Tasks:** 3 (RED -> GREEN -> live-marker/gate)
- **Files:** 2 created, 2 modified

## Accomplishments
- New `src/sift/render/pdf.py::render_pdf(store, out)`: import-guarded (`markdown` + `weasyprint` imported lazily inside the function), reuses `render_markdown` for the body, converts MD -> HTML (`fenced_code`, `tables` extensions), wraps it in a self-contained document (inline `<style>`, no `<img>`, only internal `#evt-` anchors), and renders via `weasyprint.HTML(string=…, url_fetcher=_block_all).write_pdf()`.
- Zero-egress defence-in-depth (D-09): module-level `_block_all` raises on any URL, and the HTML has nothing external to fetch — egress impossible by content AND by fetcher.
- Both failure modes map to one helpful message (D-10, Pitfall 5): `ImportError` (extra absent) and the WeasyPrint runtime `OSError` (pango/harfbuzz absent) both re-raise as `PdfExtraMissing`; `cli.report` catches it and exits 1 with a helpful message — never a Typer usage exit 2, never a traceback.
- `pyproject.toml` gains `[project.optional-dependencies] pdf = ["markdown==3.10.2", "weasyprint==69.0"]` (both pinned, both vetted at 01-01 + ADR 0002); `[project.dependencies]` is untouched — the core install stays system-dep-free.
- 6 tests: missing-extra (forced `ImportError` -> `PdfExtraMissing` + CLI exit 1), egress (fake `markdown`/`weasyprint` capture the self-contained HTML + rejecting fetcher), helper-importability without the extra, and a `@pytest.mark.live` real-render test asserting `%PDF` magic bytes and that `_block_all` never fired. The default suite needs neither `markdown`, `weasyprint` nor pango.

## Task Commits

1. **Task 1: RED — missing-extra + egress-blocked PDF tests** — `1587fa4` (test)
2. **Task 2: GREEN — render/pdf.py (import-guarded, egress-blocked) + pdf extra** — `96025b4` (feat)
3. **Task 3: live-render marker + full gate** — no code change required; the `@pytest.mark.live` real-render test was authored in Task 1 and the full gate (ruff + pyright + pytest) is green. Confirmed the live test collects only under `-m live`.

## Files Created/Modified
- `src/sift/render/pdf.py` — `render_pdf`, `_wrap_html`, `_block_all`, `_STYLE`, `_PDF_EXTRA_MSG`.
- `tests/test_render_pdf.py` — 6 tests (5 default + 1 `live`).
- `pyproject.toml` — `[project.optional-dependencies] pdf`.
- `uv.lock` — resolved `markdown` + `weasyprint` under the `pdf` extra marker.

## Decisions Made
- **Plain-callable `url_fetcher` (A4):** used the stable `url_fetcher=<callable>` form rather than the `URLFetcher(allowed_protocols=())` class; `_block_all` is module-level so the live test can spy it and assert no external fetch ever occurred.
- **Egress tested without the real libs:** injected fake `markdown`/`weasyprint` modules via `sys.modules` to capture the exact `string`/`url_fetcher` handed to WeasyPrint, so the D-09 assertions run in the default socket-blocked suite with no system dependencies.

## Deviations from Plan
None — plan executed as written. (Task 3 required no new code because the live marker + assertions were correctly authored in the Task 1 test file; the full gate was already green.)

## Manual UAT (documented, not automated)
PDF visual fidelity is manual UAT (06-VALIDATION Manual-Only). To verify on a machine with the extra + pango installed:

```bash
uv sync --extra pdf          # pulls markdown + weasyprint
sudo dnf install pango        # Fedora system lib WeasyPrint needs
uv run sift report <case> --format pdf --out /tmp/sift-uat/r.pdf
uv run pytest -m live tests/test_render_pdf.py   # asserts %PDF + no external fetch
```

Then open `r.pdf` and eyeball layout (headings, code fences, cluster table, evidence appendix anchors).

## Known Stubs
None.

## Threat Flags
None — no security surface beyond the plan's `<threat_model>` (T-06-20/21/22/SC all mitigated: rejecting `url_fetcher` + self-contained HTML, `sanitise`/fenced raw from 06-01, dual-failure-mode helpful message, pinned + vetted extra).

## Issues Encountered
- pyright strict flagged `write_pdf` (untyped WeasyPrint) and test access to `_block_all`/`_wrap_html` — resolved with targeted `# pyright: ignore` comments (reportUnknownMemberType / reportPrivateUsage).
- A pre-existing uncommitted change to `tests/test_render_json.py` (a prior-wave pyright cast refactor) is present in the working tree; it is out of scope for 06-05 and was intentionally left unstaged.

## Next Phase Readiness
- REPT-04 complete: all three report formats (md/json/pdf) now render through `sift report`; the PDF path is opt-in and fails helpfully.
- Quality gate green: `uv run ruff check`, `uv run pyright` (0 errors), `uv run pytest` (406 passed, 3 deselected — perf + live).

## Self-Check: PASSED

Both created files + this SUMMARY exist on disk; both task commits (`1587fa4`, `96025b4`) present in git log; markdown/weasyprint confirmed present only under the `pdf` extra (core `[project.dependencies]` unchanged).

---
*Phase: 06-renderers-kb-retrieval*
*Completed: 2026-07-18*
