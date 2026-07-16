"""Configuration resolution.

Phase 1 subset: only ``data_dir`` (D-04). The full precedence layering
(flags > SIFT_* env > config.toml > defaults, D-08) with the remaining keys
lands in plan 01-04; this module keeps the same shape so nothing moves.
"""

import os
from pathlib import Path

from pydantic import BaseModel


class SiftConfig(BaseModel):
    data_dir: Path


def load_config(flag_overrides: dict[str, object] | None = None) -> SiftConfig:
    """Resolve settings: defaults, then SIFT_* env, then non-None flag overrides."""
    xdg_data = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser()
    layers: dict[str, object] = {"data_dir": xdg_data / "sift"}
    if env_dir := os.environ.get("SIFT_DATA_DIR"):
        layers["data_dir"] = env_dir
    if flag_overrides:
        layers |= {k: v for k, v in flag_overrides.items() if v is not None}
    return SiftConfig.model_validate(layers)
