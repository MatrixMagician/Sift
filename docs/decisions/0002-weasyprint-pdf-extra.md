# ADR 0002: WeasyPrint behind a `sift[pdf]` optional extra

**Status:** Accepted (implementation deferred to Phase 6 / M6)
**Date:** 2026-07-16 (research date; recorded during Phase 1 per D-02)
**Answers:** SPEC.md §10 open question 2 — "reportlab vs weasyprint for PDF, or defer PDF to post-M8"

## Context

Sift's primary report format is Markdown; PDF is an optional convenience.
Research (STACK.md, 2026-07-16) compared the two candidates:

- **ReportLab 5.0.0** is pure Python with no system dependencies, but it is a
  programmatic canvas/flowables API. It renders neither Markdown nor HTML, so
  a ReportLab-based renderer means hand-writing layout code for every report
  element — the expensive path disguised as the light one.
- **WeasyPrint 69.0** renders HTML+CSS to print-quality PDF, so the pipeline
  is trivially `markdown → HTML → PDF`, reusing the Markdown renderer that
  must exist anyway. Cost: system libraries (pango, harfbuzz, gdk-pixbuf)
  that pip cannot install — on Fedora (the reference platform) a single
  `dnf install pango` away, and bakeable into the Quadlet container image.

## Decision

Use WeasyPrint behind an optional extra `sift[pdf]` (together with the
`markdown` package), with URL fetching disabled so PDF rendering cannot
become a network-egress surface. Implementation is deferred to Phase 6 (M6).
ReportLab is rejected: its zero-system-deps advantage is bought with an order
of magnitude more rendering code.

## Consequences

- Core `uv tool install sift` stays system-dependency-free; PDF is opt-in.
- `sift report --format pdf` must error helpfully when the extra is absent
  ("install sift[pdf] and pango").
- WeasyPrint's URL fetcher is disabled at render time — zero network egress
  holds even for the PDF path.
- If M6 runs hot, PDF defers cleanly to post-M8: Markdown and JSON are the
  load-bearing outputs.
