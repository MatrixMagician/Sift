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
import os
from pathlib import Path

import httpx
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


# --- the harness pins its own sampling (SEED-003) ------------------------------


def _recorded_chat_bodies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, toml: str | None = None
) -> list[dict[str, object]]:
    """Run one offline eval suite and return every chat body it sent."""
    bodies: list[dict[str, object]] = []
    inner = eval_handler()

    def recording(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            bodies.append(json.loads(request.content))
        return inner(request)

    if toml is not None:
        cfg_dir = Path(os.environ["XDG_CONFIG_HOME"]) / "sift"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "config.toml").write_text(toml, encoding="utf-8")

    patch_http(monkeypatch, recording)
    suite = single_case_suite(tmp_path)
    result = runner.invoke(app, ["eval", "--suite", str(suite)])
    assert result.exit_code == 0, result.output
    assert bodies, "the suite made no chat call at all"
    return bodies


def test_eval_pins_seed_and_temperature_on_every_chat_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``determinism_stability`` must measure Sift, not the operator's server.

    Before SEED-003 the harness sent no sampling knobs at all, so a green
    determinism figure proved only that the endpoint happened to be
    deterministic during that run. Measured against a real endpoint loaded with
    a random seed at temperature 0.8, the metric scored 0.00 with nothing wrong
    in Sift.
    """
    for body in _recorded_chat_bodies(monkeypatch, tmp_path):
        assert body["seed"] == 42
        assert body["temperature"] == 0.0


def test_configured_sampling_still_beats_the_harness_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The harness supplies a default, it does not seize control.

    Someone deliberately evaluating their own sampling policy must be able to,
    and the precedence chain (flags > env > toml > defaults) must not invert
    just because the caller is the eval command.
    """
    bodies = _recorded_chat_bodies(
        monkeypatch, tmp_path, toml="[generation]\nseed = 99\ntemperature = 0.5\n"
    )
    for body in bodies:
        assert body["seed"] == 99
        assert body["temperature"] == 0.5


def test_partially_configured_sampling_fills_only_the_gap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A pinned temperature must not also silently pin the seed, or vice versa."""
    bodies = _recorded_chat_bodies(
        monkeypatch, tmp_path, toml="[generation]\ntemperature = 0.5\n"
    )
    for body in bodies:
        assert body["seed"] == 42  # harness default fills the unset field
        assert body["temperature"] == 0.5  # operator's value survives
