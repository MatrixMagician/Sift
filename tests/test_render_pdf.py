"""`render_pdf` tests (REPT-04, D-08/D-09/D-10).

The default (socket-blocked) suite exercises only paths that need neither
``weasyprint`` nor pango: the missing-extra guard is driven by forcing the
in-function import to raise ``ImportError`` (deterministic even if the extra
happens to be installed), and the egress assertions run against fake
``markdown``/``weasyprint`` modules injected via ``sys.modules`` so the real
call shape (self-contained HTML + rejecting ``url_fetcher``) is captured
without importing WeasyPrint. The only test that actually calls ``write_pdf``
(and thus needs pango) is marked ``@pytest.mark.live``.
"""

from __future__ import annotations

import builtins
import sys
import types
from typing import TYPE_CHECKING

import pytest
from _report_fixtures import build_analysed_case, open_case
from typer.testing import CliRunner

from sift.cli import app
from sift.render._util import PdfExtraMissing
from sift.render.pdf import _block_all, _wrap_html, render_pdf

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _force_extra_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import markdown``/``from weasyprint import HTML`` raise ImportError.

    Deterministic regardless of whether the extra is actually installed.
    """
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "markdown" or name == "weasyprint" or name.startswith("weasyprint."):
            raise ImportError(f"forced-absent: {name}")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", fake_import)


def _install_fake_pdf_libs(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Inject fake ``markdown`` + ``weasyprint`` modules; capture the HTML+fetcher.

    Lets the egress assertions run without the real libraries: the fake
    ``markdown.markdown`` echoes the Markdown body into an HTML fragment and the
    fake ``weasyprint.HTML`` records the ``string`` and ``url_fetcher`` handed
    to it, then writes trivial ``%PDF`` bytes.
    """
    captured: dict[str, object] = {}

    class _FakeHTML:
        def __init__(self, *, string: str, url_fetcher: object) -> None:
            captured["string"] = string
            captured["url_fetcher"] = url_fetcher

        def write_pdf(self, target: str) -> None:
            captured["target"] = target
            with open(target, "wb") as fh:
                fh.write(b"%PDF-1.7 fake")

    fake_weasy = types.ModuleType("weasyprint")
    fake_weasy.HTML = _FakeHTML  # type: ignore[attr-defined]

    fake_md = types.ModuleType("markdown")

    def _md_markdown(text: str, extensions: object = None) -> str:
        return f"<div class='md'>{text}</div>"

    fake_md.markdown = _md_markdown  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "weasyprint", fake_weasy)
    monkeypatch.setitem(sys.modules, "markdown", fake_md)
    return captured


def test_render_pdf_missing_extra_raises_pdfextramissing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    case = build_analysed_case(monkeypatch)
    store = open_case(case)
    _force_extra_absent(monkeypatch)
    try:
        with pytest.raises(PdfExtraMissing):
            render_pdf(store, tmp_path / "r.pdf")
    finally:
        store.close()


def test_report_pdf_missing_extra_exits_one_no_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    case = build_analysed_case(monkeypatch)
    _force_extra_absent(monkeypatch)
    out = tmp_path / "r.pdf"
    result = runner.invoke(app, ["report", case, "--format", "pdf", "--out", str(out)])
    assert result.exit_code == 1, result.output
    assert "sift[pdf]" in result.output
    # A failure, not an uncaught traceback (Pitfall 5/7).
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert not out.exists()


def test_render_pdf_hands_self_contained_html_to_weasyprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured = _install_fake_pdf_libs(monkeypatch)
    case = build_analysed_case(monkeypatch)
    store = open_case(case)
    try:
        render_pdf(store, tmp_path / "r.pdf")
    finally:
        store.close()

    html = captured["string"]
    assert isinstance(html, str)
    lowered = html.lower()
    assert "<style" in lowered  # inline stylesheet, not an external <link>
    assert "<img" not in lowered  # no images to fetch
    assert "http://" not in lowered and "https://" not in lowered  # no external refs
    assert "#evt-" in html  # internal anchors survive


def test_render_pdf_url_fetcher_blocks_every_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured = _install_fake_pdf_libs(monkeypatch)
    case = build_analysed_case(monkeypatch)
    store = open_case(case)
    try:
        render_pdf(store, tmp_path / "r.pdf")
    finally:
        store.close()

    fetcher = captured["url_fetcher"]
    assert callable(fetcher)
    for url in ("http://evil.example/x", "file:///etc/passwd", "data:text/css,x"):
        with pytest.raises(ValueError, match="zero-egress"):
            fetcher(url)


def test_block_all_and_wrap_html_are_importable_without_the_extra() -> None:
    # These helpers must not import weasyprint/markdown at module level.
    with pytest.raises(ValueError, match="zero-egress"):
        _block_all("http://anything")
    wrapped = _wrap_html("<p>body #evt-abcd</p>")
    assert "<style" in wrapped.lower()
    assert "<img" not in wrapped.lower()
    assert "http://" not in wrapped and "https://" not in wrapped


@pytest.mark.live
def test_render_pdf_live_writes_real_pdf_without_external_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("markdown")
    pytest.importorskip("weasyprint")
    from sift.render import pdf as pdf_mod

    fetched: list[str] = []
    original = pdf_mod._block_all

    def _spy(url: str) -> dict[str, object]:
        fetched.append(url)
        return original(url)

    monkeypatch.setattr(pdf_mod, "_block_all", _spy)

    case = build_analysed_case(monkeypatch)
    store = open_case(case)
    out = tmp_path / "r.pdf"
    try:
        render_pdf(store, out)
    finally:
        store.close()

    data = out.read_bytes()
    assert data.startswith(b"%PDF")  # a real PDF was produced
    assert fetched == []  # the self-contained HTML never triggered a fetch
