"""Advisory LLM-as-judge tests for `sift eval --judge` (EVAL-04, D-08).

Two layers:

- **Offline (zero sockets)** — the default fake client seam (`_eval_fixtures`)
  extended with a judge-aware handler that recognises the judge chat call by its
  `response_format` schema (the judge schema carries a ``score`` property) and
  replies with a scripted judge grade. These tests prove the load-bearing
  contract: the judge is OFF by default, ON it reports a score ALONGSIDE the
  keyword metrics, and — critically (D-08) — a low or malformed judge reply
  NEVER changes the exit code, which stays governed solely by the keyword gate.
- **Live (`@pytest.mark.live`, excluded from the default socket-blocked suite)**
  — a real round-trip against the configured local model, mirroring
  `tests/test_render_pdf.py`'s live marker.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _eval_fixtures import Handler, eval_handler, patch_http, single_case_suite
from typer.testing import CliRunner

from sift.cli import app

runner = CliRunner()

_REPO_ROOT = Path(__file__).resolve().parents[1]
_THRESHOLDS = _REPO_ROOT / "eval" / "thresholds.toml"
_CASE = "memory-watermark-cascade"

# A valid, high judge grade and a valid but LOW one (the advisory-never-gates
# probe), plus an unparseable reply that must degrade to no-score, never crash.
_GOOD_JUDGE = json.dumps(
    {"score": 0.9, "justification": "Clearly identifies the watermark cascade."}
)
_LOW_JUDGE = json.dumps(
    {"score": 0.0, "justification": "The hypotheses miss the root cause entirely."}
)
_BAD_JUDGE = "sorry, I cannot produce JSON right now"


def _judge_handler(judge_reply: str) -> Handler:
    """The good keyword handler, but the judge chat call (recognised by its
    ``score`` response_format schema) returns ``judge_reply``.

    Distinguishing on the schema's properties — not prompt wording — keeps the
    fake robust to prompt edits (judge.md is a versioned template)."""
    base = eval_handler()

    def handler(request):  # noqa: ANN001 — httpx.Request, matches Handler alias
        if request.url.path.endswith("/chat/completions"):
            payload = json.loads(request.content)
            rf = payload.get("response_format")
            schema = rf.get("schema", {}) if isinstance(rf, dict) else {}
            props = schema.get("properties", {}) if isinstance(schema, dict) else {}
            if "score" in props:
                import httpx

                return httpx.Response(
                    200, json={"choices": [{"message": {"content": judge_reply}}]}
                )
        return base(request)

    return handler


def _run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, handler: Handler,
         *args: str) -> object:
    patch_http(monkeypatch, handler)
    suite = single_case_suite(tmp_path)
    return runner.invoke(
        app,
        ["eval", "--suite", str(suite), "--thresholds", str(_THRESHOLDS), *args],
    )


def test_default_run_has_no_judge_column(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Off by default: the text table carries no judge column and the run is a
    clean pass (exit 0)."""
    result = _run(monkeypatch, tmp_path, eval_handler())
    assert result.exit_code == 0, result.output
    assert "judge" not in result.output.lower()


def test_judge_flag_reports_score_alongside(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--judge reports the advisory score alongside the keyword metrics; the
    keyword suite still passes so the exit code is 0."""
    result = _run(monkeypatch, tmp_path, _judge_handler(_GOOD_JUDGE), "--judge")
    assert result.exit_code == 0, result.output
    assert "judge" in result.output.lower()
    assert "0.90" in result.output


def test_low_judge_score_never_changes_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The D-08 contract: a deliberately damning judge grade on a keyword-passing
    suite must NOT flip the pass — the gate ignores the judge entirely."""
    result = _run(monkeypatch, tmp_path, _judge_handler(_LOW_JUDGE), "--judge")
    assert result.exit_code == 0, result.output
    assert "0.00" in result.output


def test_malformed_judge_reply_degrades_not_crashes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unparseable judge reply degrades to no-score (never-crash idiom) and
    still exits 0 — no traceback, no gate change."""
    result = _run(monkeypatch, tmp_path, _judge_handler(_BAD_JUDGE), "--judge")
    assert result.exit_code == 0, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "n/a" in result.output.lower()


def test_judge_json_field_carries_the_score(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--judge --json exposes the advisory score in the per-case JSON, distinct
    from the gate object."""
    result = _run(
        monkeypatch, tmp_path, _judge_handler(_GOOD_JUDGE), "--judge", "--json"
    )
    assert result.exit_code == 0, result.output
    doc = json.loads(result.output)
    case = next(c for c in doc["cases"] if c["name"] == _CASE)
    assert case["judge_score"] == 0.9
    # The judge never enters the gate.
    assert doc["gate"]["passed"] is True


def test_default_json_leaves_judge_score_null(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No --judge: the reserved judge_score field stays null (byte-compatible
    with Plan 03's JSON shape)."""
    result = _run(monkeypatch, tmp_path, eval_handler(), "--json")
    assert result.exit_code == 0, result.output
    doc = json.loads(result.output)
    case = next(c for c in doc["cases"] if c["name"] == _CASE)
    assert case["judge_score"] is None


@pytest.mark.live
def test_judge_live_round_trip(tmp_path: Path) -> None:
    """Real local model: `sift eval --judge` over one case returns a judge score
    alongside the keyword scores. Excluded from the default socket-blocked suite
    (D-09); run with `uv run pytest -m live`."""
    suite = single_case_suite(tmp_path)
    result = runner.invoke(
        app,
        ["eval", "--suite", str(suite), "--thresholds", str(_THRESHOLDS), "--judge"],
    )
    # The keyword gate may pass or fail against a real model; the contract under
    # test is only that the judge column appears without crashing.
    assert result.exit_code in (0, 1), result.output
    assert "judge" in result.output.lower()
