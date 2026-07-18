"""Optional PDF triage-report renderer (REPT-04, D-08/D-09/D-10).

Import-guarded behind the ``sift[pdf]`` extra: ``markdown`` and ``weasyprint``
are imported lazily *inside* :func:`render_pdf`, so the core install and the
default (socket-blocked) test suite never require them or the pango system
library (ADR 0002). The Markdown report (:func:`render_markdown`) is reused
wholesale — converted to a self-contained HTML document (inline ``<style>``,
no ``<img>``, only internal ``#evt-`` anchors) and rendered to PDF by
WeasyPrint with URL fetching disabled. Egress is therefore impossible both by
content (nothing external to fetch) and by a rejecting ``url_fetcher`` (D-09).

Both failure modes — the extra absent (``ImportError``) and its pango/harfbuzz
system libraries absent at render time (``OSError`` deep in ``write_pdf``,
Pitfall 5) — map to the same helpful :class:`PdfExtraMissing`, never a bare
traceback across the CLI boundary (D-10).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sift.render._util import PdfExtraMissing
from sift.render.markdown import render_markdown

if TYPE_CHECKING:
    from pathlib import Path

    from sift.store import CaseStore

_PDF_EXTRA_MSG = (
    "PDF output requires the optional extra: install 'sift[pdf]' and the pango "
    "system library (Fedora: dnf install pango)"
)

# D-09: a minimal print stylesheet, fully inline — no external CSS, font or
# image is ever referenced, so WeasyPrint never needs to fetch a resource.
_STYLE = """\
body { font-family: sans-serif; font-size: 11px; line-height: 1.4; }
h1 { font-size: 20px; } h2 { font-size: 16px; } h3, h4 { font-size: 13px; }
code, pre { font-family: monospace; font-size: 10px; }
pre { white-space: pre-wrap; background: #f4f4f4; padding: 6px; }
pre { border: 1px solid #ddd; }
table { border-collapse: collapse; }
td, th { border: 1px solid #ccc; padding: 3px 6px; }
blockquote { border-left: 3px solid #c00; margin: 0; padding-left: 8px; color: #900; }
"""


def _wrap_html(body: str) -> str:
    """Wrap a rendered-HTML body in a self-contained document (D-09).

    Inline ``<style>`` only — no external stylesheet, font or image reference —
    so WeasyPrint never has cause to fetch a resource.
    """
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f"<style>{_STYLE}</style></head><body>{body}</body></html>"
    )


def _block_all(url: str) -> dict[str, object]:
    """Reject every URL fetch (D-09 zero-egress, defence-in-depth).

    The HTML is self-contained, so this should never be called; if it ever is,
    fail loud rather than silently reaching the network or filesystem.
    """
    raise ValueError(f"external fetch blocked (zero-egress): {url!r}")


def render_pdf(store: CaseStore, out: Path) -> None:
    """Render the Markdown triage report to a PDF at ``out`` (REPT-04).

    Raises :class:`PdfExtraMissing` (with a helpful message) when the
    ``sift[pdf]`` extra is absent, or when WeasyPrint's system libraries are
    missing at render time (Pitfall 5). Never raises a bare traceback.
    """
    try:
        import markdown  # type: ignore[import-untyped]
        from weasyprint import HTML  # type: ignore[import-untyped]
    except ImportError as exc:
        raise PdfExtraMissing(_PDF_EXTRA_MSG) from exc

    md_text = render_markdown(store)
    body: str = markdown.markdown(md_text, extensions=["fenced_code", "tables"])
    html = _wrap_html(body)
    try:
        pdf_bytes = cast(
            "bytes",
            HTML(string=html, url_fetcher=_block_all).write_pdf(),  # pyright: ignore[reportUnknownMemberType]
        )
    except OSError as exc:
        # WR-02: reserve the pango/harfbuzz diagnosis for the RENDER step —
        # cffi surfaces an OSError deep in write_pdf when the system libraries
        # are absent. Rendering to bytes (no output path) means this except can
        # never catch a write-target error, so an unwritable --out is reported
        # as a write failure below, not misdiagnosed as a missing extra.
        raise PdfExtraMissing(_PDF_EXTRA_MSG) from exc
    # A write-target OSError (unwritable/missing --out dir, full disk) propagates
    # as an OSError — cli.report maps it to a distinct "cannot write" message.
    out.write_bytes(pdf_bytes)
