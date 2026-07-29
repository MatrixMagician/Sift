"""Shared render-time helpers: sanitisation, escaping, MB conversion, PDF error.

``sanitise`` is the single control-char strip used by BOTH the CLI (imported
back as ``_sanitise``) and the report renderers, so there is one implementation
and no ``cli`` <-> ``render`` import cycle (render never imports cli).
``mb_bytes`` is likewise the single bytes-to-MB conversion, shared by the MCM
report renderer and the MCM fact renderer (IN-01).

``md_escape``/``md_field`` are the single Markdown+HTML escaping path (WR-04),
and ``csv_safe`` the single spreadsheet-formula guard (T-13-CSVINJ). They live
here — not in ``markdown.py`` / ``perfmon_report.py`` — so sibling renderers
share them through the utility module instead of importing each other's
private symbols.
"""

import html
import unicodedata


def sanitise(text: str) -> str:
    """Strip control characters (except newline and tab) from rendered text.

    T-04-01: hostile log bytes must never drive the operator's terminal.
    Removes C0 controls (below 0x20), DEL (0x7f), C1 controls (0x80-0x9f,
    e.g. the single-byte CSI) and Unicode format characters (category Cf:
    bidi overrides like U+202E, zero-width characters) that can visually
    reorder or hide rendered triage output. Applied at render time only —
    stored raw and message text stay verbatim for citation fidelity.
    """
    return "".join(
        ch
        for ch in text
        if ch in "\n\t"
        or (
            ord(ch) >= 0x20
            and not (0x7F <= ord(ch) <= 0x9F)
            and unicodedata.category(ch) != "Cf"
        )
    )


def mb_bytes(granted_bytes: int) -> float:
    """Convert bytes to megabytes, rounded deterministically to 3 dp.

    The single conversion for every granted-memory figure Sift displays, called
    by both ``render/mcm_report.py`` and ``pipeline/mcm_facts.py`` (IN-01): two
    independent divisions agree on real data but can drift apart under later
    edits, and the report and the prompt must never quote different numbers for
    the same row.
    """
    return round(granted_bytes / 1024**2, 3)


# Markdown structural metacharacters that could inject headings, emphasis,
# lists, code spans, links or table columns if left raw in a DB/model field.
# Backslash comes first so we never double-escape our own escapes. `< > &` are
# handled by html.escape (they become entities, safe in Markdown AND the PDF's
# HTML), so they are deliberately NOT in this backslash set.
_MD_STRUCT = ("\\", "`", "*", "_", "#", "[", "]", "|")


def md_escape(text: str) -> str:
    """Escape Markdown structural + HTML metacharacters in DB/model text (WR-04).

    Backslash-escapes Markdown structure (``\\ ` * _ # [ ] |``) then HTML-escapes
    ``& < >`` to entities. The result is inert both as inline Markdown and, once
    ``markdown.markdown`` converts it, as HTML in the PDF path — so a title or
    narrative cannot inject a heading, link, fake OK marker, or a raw ``<img>``.
    """
    for ch in _MD_STRUCT:
        text = text.replace(ch, "\\" + ch)
    return html.escape(text, quote=False)


def md_field(text: str) -> str:
    """Sanitise (strip control chars) then escape a DB/model inline field."""
    return md_escape(sanitise(text))


# The characters a spreadsheet treats as the start of a formula when it opens a
# CSV. Only the four printable triggers: leading whitespace is handled by
# testing the first SIGNIFICANT character in ``csv_safe`` (WR-05) rather than
# by smuggling whitespace into the trigger set, where a naive first-character
# check would still miss ``" =cmd"`` (a space, then a real trigger).
_FORMULA_TRIGGERS = ("=", "+", "-", "@")


def csv_safe(value: str) -> str:
    """Neutralise a spreadsheet formula trigger at the start of a CSV cell.

    Three facts make this guard necessary and non-redundant (T-13-CSVINJ):

    1. Perfmon counter names originate in the customer's DSSPerformanceMonitor
       CSV header and are therefore attacker-influenceable. This is exactly the
       premise that does NOT hold for ``mcm_report.write_attribution_csv``,
       whose keys are structurally hex SIDs/OIDs or ``[\\w:]+`` source values
       that cannot begin with a trigger — so that writer's quoting-suffices
       reasoning is deliberately NOT carried over here. The divergence is
       intentional, not an inconsistency.
    2. ``csv.writer`` quoting prevents delimiter and newline injection, but a
       quoted cell beginning ``=`` is still evaluated as a formula when the file
       is opened in a spreadsheet. Quoting is the wrong layer for this threat.
    3. ``sanitise`` handles a DIFFERENT threat and is composed here ALONGSIDE
       the formula guard, not instead of it (CR-02): it strips the control
       characters and Unicode-Cf code points (a single-byte CSI 0x9B, a bidi
       override) that would otherwise drive the terminal of an operator who
       ``cat``s the bundle — the same threat T-13-MDESC/T-13-JSONESC close for
       the Markdown and JSON artefacts. Every printable formula trigger passes
       through it untouched, so it cannot replace the quote-prefix.

    Only string cells are guarded. A numeric cell is written by ``csv.writer``
    from a real ``float``/``int``, so a legitimately negative figure such as a
    falling slope keeps its leading minus sign rather than being corrupted into
    text by a guard it never needed.

    Ordering is load-bearing: sanitise FIRST (strip the control bytes), then
    quote — quoting first would leave a stripped-to-empty trigger sitting behind
    the quote. The first SIGNIFICANT character is tested, not literally the first
    one: a spreadsheet strips leading whitespace before deciding a cell is a
    formula, so ``" =cmd"`` is as dangerous as a bare ``=`` (WR-05).
    """
    cleaned = sanitise(value)
    significant = cleaned.lstrip(" \t\r\n")
    return f"'{cleaned}" if significant.startswith(_FORMULA_TRIGGERS) else cleaned


class PdfExtraMissing(RuntimeError):
    """Raised when the optional ``sift[pdf]`` extra (WeasyPrint) is unavailable.

    Defined here so ``cli.report``'s pdf branch can name it before the real
    ``render/pdf.py`` renderer lands in plan 06-05 (D-10).
    """
