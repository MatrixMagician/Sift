"""Offline end-to-end machinery test for `sift eval` (EVAL-02/05).

Drives the committed memory-watermark-cascade golden case through the real
ingest → cluster → hypothesise pipeline with a fake OpenAI-compatible client
(MockTransport). Opens zero sockets: the autouse `_no_network` guard stays
active, and every inference call is served in-process. This asserts the harness
*machinery* — that a run produces a metric row and parseable JSON — not real
model quality (a live concern).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _eval_fixtures import eval_handler, patch_http, single_case_suite
from typer.testing import CliRunner

from sift.cli import app

runner = CliRunner()

_CASE = "memory-watermark-cascade"

_METRICS = (
    "retrieval_hit_rate",
    "hypothesis_hit_at_k",
    "citation_validity_rate",
    "determinism_stability",
)


def test_eval_offline_prints_metric_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_http(monkeypatch, eval_handler())
    suite = single_case_suite(tmp_path)
    result = runner.invoke(app, ["eval", "--suite", str(suite)])
    assert result.exit_code == 0, result.output
    # The stub is gone and the case is named with numeric metric values.
    assert "arrives in Phase 7" not in result.output
    assert _CASE in result.output


def test_eval_offline_json_is_parseable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_http(monkeypatch, eval_handler())
    suite = single_case_suite(tmp_path)
    result = runner.invoke(app, ["eval", "--suite", str(suite), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    cases = {c["name"]: c for c in data["cases"]}
    assert _CASE in cases
    row = cases[_CASE]
    for metric in _METRICS:
        assert isinstance(row[metric], (int, float)), metric
    # The good handler hits every acceptable_keyword and the required evidence,
    # cites nothing (trivially valid), and is byte-identical across the two runs.
    assert row["hypothesis_hit_at_k"] == 1.0
    assert row["retrieval_hit_rate"] == 1.0
    assert row["citation_validity_rate"] == 1.0
    assert row["determinism_stability"] == 1.0


def test_eval_missing_suite_is_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(monkeypatch, eval_handler())
    result = runner.invoke(app, ["eval", "--suite", "/no/such/suite"])
    assert result.exit_code == 2, result.output
