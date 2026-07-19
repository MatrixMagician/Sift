"""Configuration resolution (D-08).

Precedence: CLI flags > ``SIFT_*`` env > ``$XDG_CONFIG_HOME/sift/config.toml``
> defaults. Layered plain dicts merged in that order (later wins per key),
validated once with plain Pydantic — no pydantic-settings (D-08).

Phase 1 exposed only ``SIFT_DATA_DIR``; Phase 3 adds the generalised
``SIFT_*`` -> nested-key scalar mapping (``_ENV_SCALARS``) for the new
``[generation]``, ``[embeddings]`` and ``[clustering]`` sections. The
``timezones``/``adapters`` mappings remain TOML/flag-only (nested mappings,
not scalars), which satisfies D-05/D-08's "mechanism must exist".
"""

import os
import tomllib
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, field_validator


class GenerationConfig(BaseModel):
    """OpenAI-compatible generation endpoint knobs (LLM-01)."""

    # T-04-02: a typo'd key must fail loudly, never be silently dropped.
    model_config = ConfigDict(extra="forbid")

    base_url: str = "http://localhost:13305/v1"
    model: str | None = None  # D-03: config-only identity, no baked default.
    timeout: float = 60.0
    retries: int = 2
    backoff_base: float = 0.5


class EmbeddingsConfig(BaseModel):
    """OpenAI-compatible embeddings endpoint knobs (LLM-01, STORE-03)."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = "http://localhost:13305/v1"
    model: str | None = None  # D-03: NO baked default — identity comes from config.
    timeout: float = 60.0
    batch_size: int = 64
    # Cap each embedding input to this many characters before sending. A large
    # multi-line record (MCM memory dump, stack trace) can exceed the model's
    # context window; the backend then rejects the whole request and aborts
    # analyze. 8000 chars is ~2000-2700 tokens, safely under an 8192-token
    # context; lower it for a small-context model (e.g. bge-small = 512).
    max_input_chars: int = 8000


class ClusteringConfig(BaseModel):
    """HDBSCAN + agglomerative-fallback parameters (CLUS-02, D-04)."""

    model_config = ConfigDict(extra="forbid")

    algorithm: str = "hdbscan"
    min_cluster_size: int = 2
    # sklearn.cluster.HDBSCAN counts the point itself, so this is +1 versus
    # standalone hdbscan semantics (research-locked; keep the default explicit).
    min_samples: int = 1
    epsilon: float = 0.0
    distance_threshold: float = 0.3  # cosine threshold for the agglomerative fallback.


class SiftConfig(BaseModel):
    # T-04-02: a typo'd key must fail loudly, never be silently dropped.
    model_config = ConfigDict(extra="forbid")

    data_dir: Path
    timezones: dict[str, str] = {}  # glob -> IANA zone name (D-05 override mechanism)
    adapters: dict[str, str] = {}  # glob -> adapter name (same semantics as --adapter)
    generation: GenerationConfig = GenerationConfig()
    embeddings: EmbeddingsConfig = EmbeddingsConfig()
    clustering: ClusteringConfig = ClusteringConfig()

    @field_validator("timezones")
    @classmethod
    def _zones_must_exist(cls, value: dict[str, str]) -> dict[str, str]:
        """Bad zone names fail at config time, not mid-ingest (T-04-02)."""
        for glob, zone in value.items():
            try:
                ZoneInfo(zone)
            except (KeyError, ValueError) as exc:
                raise ValueError(
                    f"invalid timezone {zone!r} for glob {glob!r}: "
                    "not a known IANA zone name"
                ) from exc
        return value


# Scalar SIFT_* env -> (section, field). Only scalars belong here; the nested
# timezones/adapters mappings stay TOML/flag-only. Values arrive as strings and
# are coerced by pydantic on validation (e.g. "64" -> int batch_size).
_ENV_SCALARS: dict[str, tuple[str, str]] = {
    "SIFT_GENERATION_BASE_URL": ("generation", "base_url"),
    "SIFT_GENERATION_MODEL": ("generation", "model"),
    "SIFT_GENERATION_TIMEOUT": ("generation", "timeout"),
    "SIFT_GENERATION_RETRIES": ("generation", "retries"),
    "SIFT_EMBEDDINGS_BASE_URL": ("embeddings", "base_url"),
    "SIFT_EMBEDDINGS_MODEL": ("embeddings", "model"),
    "SIFT_EMBEDDINGS_TIMEOUT": ("embeddings", "timeout"),
    "SIFT_EMBEDDINGS_BATCH_SIZE": ("embeddings", "batch_size"),
    "SIFT_EMBEDDINGS_MAX_INPUT_CHARS": ("embeddings", "max_input_chars"),
}


def _set_nested(
    layers: dict[str, object], section: str, field: str, value: object
) -> None:
    """Merge one scalar into a nested section dict without clobbering siblings."""
    current = layers.get(section)
    section_dict: dict[str, object] = {}
    if isinstance(current, dict):
        section_dict.update(cast("dict[str, object]", current))
    section_dict[field] = value
    layers[section] = section_dict


def load_config(flag_overrides: dict[str, object] | None = None) -> SiftConfig:
    """Resolve settings: defaults, then config.toml, then SIFT_* env, then flags."""
    xdg_data = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser()
    layers: dict[str, object] = {"data_dir": xdg_data / "sift"}
    xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
    cfg_path = xdg_config / "sift" / "config.toml"
    if cfg_path.exists():
        try:
            layers |= tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            # Never fall back to defaults silently on a malformed file (T-04-02).
            raise ValueError(f"invalid config file {cfg_path}: {exc}") from exc
    if env_dir := os.environ.get("SIFT_DATA_DIR"):
        layers["data_dir"] = env_dir
    # SIFT_* scalar env sits above toml, below flags (deep-merged per section).
    for env_key, (section, field) in _ENV_SCALARS.items():
        if (value := os.environ.get(env_key)) is not None:
            _set_nested(layers, section, field, value)
    if flag_overrides:
        for key, value in flag_overrides.items():
            if value is None:
                continue
            existing = layers.get(key)
            if isinstance(value, dict) and isinstance(existing, dict):
                # Deep-merge so a nested flag override wins per field without
                # discarding toml/env siblings (flags > env > toml).
                merged: dict[str, object] = {}
                merged.update(cast("dict[str, object]", existing))
                merged.update(cast("dict[str, object]", value))
                layers[key] = merged
            else:
                layers[key] = value
    return SiftConfig.model_validate(layers)
