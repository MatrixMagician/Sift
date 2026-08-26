"""``docs/CONFIGURATION.md`` must describe the config that actually exists.

That reference is the only place an operator finds out a knob exists, and it is
maintained by hand while ``src/sift/config.py`` changes underneath it. Nothing
connected the two, so a new field could ship undocumented and a removed one
could linger in the table indefinitely — with the doc looking, to a reader,
exactly as authoritative either way.

Both directions are checked. The undocumented-field direction is the one that
loses operators a feature; the phantom-row direction is the one that sends them
looking for a key that does nothing, and `extra="forbid"` means acting on a
phantom row is a hard startup error.

The same check covers the ``SIFT_*`` environment column, which is a second hand-
maintained mapping (``config._ENV_SCALARS``) that can drift independently of the
field itself.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from sift.config import (
    _ENV_SCALARS,  # pyright: ignore[reportPrivateUsage] — the mapping under test
    ClusteringConfig,
    EmbeddingsConfig,
    EustackConfig,
    EustackThresholdsConfig,
    GenerationConfig,
    McmThresholdsConfig,
    SiftConfig,
)

_DOC = Path(__file__).resolve().parent.parent / "docs" / "CONFIGURATION.md"

# Each section's TOML key prefix and the model whose fields it must describe.
# `SiftConfig`'s own sub-model fields (generation, embeddings, ...) are the
# section headers themselves, so they are excluded from the top-level check.
# `mcm`/`eustack` each wrap a nested thresholds table; the reference documents
# the nested path, so the wrapper's own `thresholds` field is skipped below.
_SECTIONS: tuple[tuple[str, type[BaseModel]], ...] = (
    ("generation", GenerationConfig),
    ("embeddings", EmbeddingsConfig),
    ("clustering", ClusteringConfig),
    ("eustack", EustackConfig),
    ("mcm.thresholds", McmThresholdsConfig),
    ("eustack.thresholds", EustackThresholdsConfig),
)

# Documented at their nested path instead (`mcm.thresholds.*`, `eustack.thresholds.*`).
_WRAPPER_FIELDS = {"mcm.thresholds", "eustack.thresholds"}


def _documented_keys() -> set[str]:
    """Every ``key`` from a ``| `key` | ...`` table row in the reference."""
    text = _DOC.read_text(encoding="utf-8")
    return set(re.findall(r"^\|\s*`([a-z_.]+)`\s*\|", text, re.MULTILINE))


def _documented_env_vars() -> set[str]:
    """Every ``SIFT_*`` name appearing anywhere in the reference."""
    return set(re.findall(r"`(SIFT_[A-Z_]+)`", _DOC.read_text(encoding="utf-8")))


def test_every_config_field_is_documented() -> None:
    """A field an operator cannot discover may as well not exist."""
    documented = _documented_keys()
    missing: list[str] = []
    for prefix, model in _SECTIONS:
        for field in model.model_fields:
            key = f"{prefix}.{field}"
            if key not in documented and key not in _WRAPPER_FIELDS:
                missing.append(key)
    # Top-level scalars/tables, excluding the section wrappers themselves.
    section_names = {prefix.split(".")[0] for prefix, _ in _SECTIONS}
    for field in SiftConfig.model_fields:
        if field not in section_names and field not in documented:
            missing.append(field)
    assert not missing, f"undocumented config keys: {sorted(missing)}"


def test_no_documented_key_is_a_phantom() -> None:
    """A row for a key that does not exist is worse than no row at all.

    ``extra="forbid"`` means an operator who trusts a phantom row gets a hard
    startup error out of a document that told them to write it.
    """
    real: set[str] = {
        f"{prefix}.{field}"
        for prefix, model in _SECTIONS
        for field in model.model_fields
    }
    real |= set(SiftConfig.model_fields)
    real |= _WRAPPER_FIELDS
    phantom = sorted(
        key
        for key in _documented_keys()
        # Rows in the "not in config.toml" section describe flags, not keys.
        if "." in key or key in SiftConfig.model_fields or key.islower()
        if key not in real
    )
    assert not phantom, f"documented keys that do not exist: {phantom}"


def test_every_env_var_is_documented() -> None:
    """The ``SIFT_*`` column is a second hand-maintained mapping."""
    undocumented = sorted(
        set(_ENV_SCALARS) - _documented_env_vars() - {"SIFT_DATA_DIR"}
    )
    assert not undocumented, f"undocumented env vars: {undocumented}"


def test_no_documented_env_var_is_a_phantom() -> None:
    """An env var in the table that nothing reads silently does nothing."""
    real = set(_ENV_SCALARS) | {"SIFT_DATA_DIR"}
    phantom = sorted(_documented_env_vars() - real)
    assert not phantom, f"documented env vars that are never read: {phantom}"
