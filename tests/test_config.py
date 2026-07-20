"""D-08 config precedence matrix: flags > SIFT_* env > config.toml > defaults.

The autouse conftest fixture redirects XDG_DATA_HOME/XDG_CONFIG_HOME to
tmp_path and clears SIFT_* env vars, so every test starts from bare defaults.
"""

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from sift.config import McmThresholdsConfig, load_config


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


def test_unknown_config_key_is_a_loud_error_naming_the_key() -> None:
    """WR-05 / T-04-02: a typo'd key never silently does nothing."""
    _write_toml('data_dirr = "/tmp/typo"\n')
    with pytest.raises(ValidationError, match="data_dirr"):
        load_config()


def test_unknown_config_section_is_a_loud_error() -> None:
    _write_toml('[timezone]\n"node1/*" = "Europe/Berlin"\n')  # [timezones] typo
    with pytest.raises(ValidationError, match="timezone"):
        load_config()


def test_malformed_toml_is_a_loud_error() -> None:
    cfg_path = _write_toml("data_dir = [unclosed\n")
    with pytest.raises(ValueError, match=str(cfg_path)):
        load_config()


def test_new_sections_have_tuned_defaults() -> None:
    config = load_config()
    # D-03: no baked embedding-model default; scalar knobs are tuned.
    assert config.embeddings.model is None
    assert config.generation.model is None
    assert config.embeddings.base_url == "http://localhost:13305/v1"
    assert config.embeddings.batch_size == 64
    assert config.clustering.algorithm == "hdbscan"
    assert config.clustering.min_samples == 1  # sklearn self-count (+1 vs standalone)


def test_embeddings_section_round_trips_from_toml() -> None:
    _write_toml(
        '[embeddings]\nmodel = "nomic-embed"\nbatch_size = 8\n'
    )
    config = load_config()
    assert config.embeddings.model == "nomic-embed"
    assert config.embeddings.batch_size == 8


def test_env_beats_toml_for_embeddings_base_url_but_flag_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SIFT_* scalar env sits between toml and flags (precedence matrix)."""
    _write_toml('[embeddings]\nbase_url = "http://localhost:1/v1"\n')
    monkeypatch.setenv("SIFT_EMBEDDINGS_BASE_URL", "http://localhost:2/v1")
    # Env overrides the toml value...
    assert load_config().embeddings.base_url == "http://localhost:2/v1"
    # ...but a flag override still wins over env, without clobbering siblings.
    config = load_config({"embeddings": {"base_url": "http://localhost:3/v1"}})
    assert config.embeddings.base_url == "http://localhost:3/v1"


def test_env_batch_size_coerced_to_int(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIFT_EMBEDDINGS_BATCH_SIZE", "16")
    assert load_config().embeddings.batch_size == 16


def test_unknown_key_under_clustering_is_a_loud_error() -> None:
    """T-04-02: extra=forbid on every nested model, not just the root."""
    _write_toml('[clustering]\nmin_cluster_sze = 4\n')  # typo'd key
    with pytest.raises(ValidationError, match="min_cluster_sze"):
        load_config()


# ------------------------------------------------ MCM-03 / D-12 ([mcm.thresholds])


def test_mcm_thresholds_defaults() -> None:
    """An absent [mcm.thresholds] block yields the RESEARCH-calibrated documented
    constants (config-only, D-12), so the real Hartford episode reads CRITICAL."""
    t = load_config().mcm.thresholds
    assert isinstance(t, McmThresholdsConfig)
    assert (t.working_set_pct_virtual.warn, t.working_set_pct_virtual.critical) == (
        20,
        40,
    )
    assert (
        t.other_processes_pct_physical.warn,
        t.other_processes_pct_physical.critical,
    ) == (10, 20)
    assert (t.cube_pct_virtual.warn, t.cube_pct_virtual.critical) == (25, 40)
    assert t.mmf_pct_of_cube_low == 10
    assert (
        t.smartheap_pool_pct_virtual.warn,
        t.smartheap_pool_pct_virtual.critical,
    ) == (5, 15)
    # Inverted metric stored as-authored (warn=20, critical=5); the grader flips
    # the comparison direction, not the config (lower free-% is worse).
    assert (
        t.system_free_headroom_pct.warn,
        t.system_free_headroom_pct.critical,
    ) == (20, 5)


def test_mcm_thresholds_override_and_typo() -> None:
    """A [mcm.thresholds] override wins per field under standard precedence
    (CLI>env>toml>defaults); a typo'd key fails loudly (extra='forbid'), never
    silently dropped (T-04-02)."""
    _write_toml(
        "[mcm.thresholds]\n"
        "working_set_pct_virtual = { warn = 30, critical = 55 }\n"
    )
    t = load_config().mcm.thresholds
    assert (t.working_set_pct_virtual.warn, t.working_set_pct_virtual.critical) == (
        30,
        55,
    )
    # Untouched rows keep the documented defaults.
    assert (
        t.other_processes_pct_physical.warn,
        t.other_processes_pct_physical.critical,
    ) == (10, 20)

    # A typo'd key inside [mcm.thresholds] is a loud error, not a silent default.
    _write_toml(
        "[mcm.thresholds]\n"
        "working_set_pct_virtal = { warn = 30, critical = 55 }\n"
    )
    with pytest.raises(ValidationError, match="working_set_pct_virtal"):
        load_config()


def test_env_generation_context_coerced_to_int(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIFT_GENERATION_CONTEXT", "4096")
    config = load_config({})
    assert config.generation.context == 4096
