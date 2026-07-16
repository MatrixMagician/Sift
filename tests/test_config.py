"""D-08 config precedence matrix: flags > SIFT_* env > config.toml > defaults.

The autouse conftest fixture redirects XDG_DATA_HOME/XDG_CONFIG_HOME to
tmp_path and clears SIFT_* env vars, so every test starts from bare defaults.
"""

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from sift.config import load_config


def _write_toml(body: str) -> Path:
    cfg_dir = Path(os.environ["XDG_CONFIG_HOME"]) / "sift"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "config.toml"
    cfg_path.write_text(body, encoding="utf-8")
    return cfg_path


def test_defaults_when_no_config_anywhere() -> None:
    config = load_config()
    assert config.data_dir == Path(os.environ["XDG_DATA_HOME"]) / "sift"
    assert config.timezones == {}
    assert config.adapters == {}


def test_toml_beats_default(tmp_path: Path) -> None:
    toml_dir = tmp_path / "from-toml"
    _write_toml(f'data_dir = "{toml_dir}"\n')
    assert load_config().data_dir == toml_dir


def test_env_beats_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_toml(f'data_dir = "{tmp_path / "from-toml"}"\n')
    env_dir = tmp_path / "from-env"
    monkeypatch.setenv("SIFT_DATA_DIR", str(env_dir))
    assert load_config().data_dir == env_dir


def test_flag_beats_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIFT_DATA_DIR", str(tmp_path / "from-env"))
    flag_dir = tmp_path / "from-flag"
    assert load_config({"data_dir": flag_dir}).data_dir == flag_dir


def test_none_flag_override_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIFT_DATA_DIR", "/tmp-env-dir")
    assert load_config({"data_dir": None}).data_dir == Path("/tmp-env-dir")


def test_timezones_round_trip_from_toml() -> None:
    _write_toml('[timezones]\n"node1/*" = "Europe/Berlin"\n')
    assert load_config().timezones == {"node1/*": "Europe/Berlin"}


def test_invalid_timezone_rejected_naming_the_zone() -> None:
    _write_toml('[timezones]\n"node1/*" = "Not/AZone"\n')
    with pytest.raises(ValidationError, match="Not/AZone"):
        load_config()


def test_adapters_mapping_round_trip() -> None:
    _write_toml('[adapters]\n"*.dss" = "genericlog"\n')
    assert load_config().adapters == {"*.dss": "genericlog"}


def test_missing_toml_tolerated() -> None:
    # conftest guarantees XDG_CONFIG_HOME exists but contains no sift/config.toml
    assert not (Path(os.environ["XDG_CONFIG_HOME"]) / "sift").exists()
    assert load_config().data_dir == Path(os.environ["XDG_DATA_HOME"]) / "sift"


def test_malformed_toml_is_a_loud_error() -> None:
    cfg_path = _write_toml("data_dir = [unclosed\n")
    with pytest.raises(ValueError, match=str(cfg_path)):
        load_config()
