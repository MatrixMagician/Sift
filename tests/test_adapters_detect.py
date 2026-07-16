"""INGST-03 detection: threshold, tie, fallback, and override rules."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from sift import adapters
from sift.adapters import REGISTRY, detect, parse_adapter_overrides
from sift.models import Event


class DummyAdapter:
    """Sniffs a fixed confidence; parses nothing."""

    def __init__(self, name: str, score: float) -> None:
        self.name = name
        self.score = score

    def sniff(self, path: Path) -> float:
        return self.score

    def parse(self, path: Path, case_id: str) -> Iterator[Event]:
        return iter(())


@pytest.fixture
def registry() -> Iterator[dict[str, adapters.Adapter]]:
    """Expose REGISTRY for mutation; restore the original entries afterwards."""
    saved = dict(REGISTRY)
    try:
        yield REGISTRY
    finally:
        REGISTRY.clear()
        REGISTRY.update(saved)


@pytest.fixture
def log_file(tmp_path: Path) -> Path:
    path = tmp_path / "app.log"
    path.write_text("plain text without any timestamp\n", encoding="utf-8")
    return path


def test_high_confidence_adapter_wins(
    registry: dict[str, adapters.Adapter], log_file: Path
) -> None:
    dummy = DummyAdapter("dummy", 0.9)
    registry["dummy"] = dummy
    assert detect(log_file, "app.log", {}) is dummy


def test_tie_at_max_falls_back_to_genericlog(
    registry: dict[str, adapters.Adapter], log_file: Path
) -> None:
    registry["dummy1"] = DummyAdapter("dummy1", 0.9)
    registry["dummy2"] = DummyAdapter("dummy2", 0.9)
    assert detect(log_file, "app.log", {}) is registry["genericlog"]


def test_all_below_threshold_falls_back_to_genericlog(
    registry: dict[str, adapters.Adapter], log_file: Path
) -> None:
    registry["dummy"] = DummyAdapter("dummy", 0.4)
    assert detect(log_file, "app.log", {}) is registry["genericlog"]


def test_override_beats_losing_sniff_score(
    registry: dict[str, adapters.Adapter], log_file: Path
) -> None:
    dummy = DummyAdapter("dummy", 0.0)  # would always lose detection
    registry["dummy"] = dummy
    special = log_file.with_name("data.special")
    special.write_text("x\n", encoding="utf-8")
    assert detect(special, "data.special", {"*.special": "dummy"}) is dummy


def test_first_matching_override_glob_wins(
    registry: dict[str, adapters.Adapter], log_file: Path
) -> None:
    registry["dummy"] = DummyAdapter("dummy", 0.0)
    overrides = {"app.*": "dummy", "*.log": "genericlog"}  # both match
    assert detect(log_file, "app.log", overrides) is registry["dummy"]


def test_override_with_unknown_name_raises_listing_registered(
    log_file: Path,
) -> None:
    with pytest.raises(ValueError, match="genericlog"):
        detect(log_file, "app.log", {"*.log": "nope"})


def test_empty_file_detects_as_genericlog(tmp_path: Path) -> None:
    empty = tmp_path / "empty.log"
    empty.write_bytes(b"")
    assert detect(empty, "empty.log", {}) is REGISTRY["genericlog"]


def test_parse_adapter_overrides_basic() -> None:
    assert parse_adapter_overrides(["*.log=genericlog"]) == {"*.log": "genericlog"}


def test_parse_adapter_overrides_glob_with_equals_survives() -> None:
    # Split happens on the LAST '=': adapter names never contain one.
    assert parse_adapter_overrides(["key=value*.log=genericlog"]) == {
        "key=value*.log": "genericlog"
    }


def test_parse_adapter_overrides_unknown_name_lists_registered() -> None:
    with pytest.raises(ValueError, match=r"unknown adapter 'nope'.*genericlog"):
        parse_adapter_overrides(["*.log=nope"])


@pytest.mark.parametrize("spec", ["justaname", "=genericlog", "*.log="])
def test_parse_adapter_overrides_malformed_spec_rejected(spec: str) -> None:
    with pytest.raises(ValueError, match="expected glob=name"):
        parse_adapter_overrides([spec])
