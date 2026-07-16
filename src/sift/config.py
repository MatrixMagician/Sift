"""Configuration resolution (D-08).

Precedence: CLI flags > ``SIFT_*`` env > ``$XDG_CONFIG_HOME/sift/config.toml``
> defaults. Layered plain dicts merged in that order (later wins per key),
validated once with plain Pydantic — no pydantic-settings (D-08).

Phase 1 env surface is ``SIFT_DATA_DIR`` only; the ``timezones``/``adapters``
mappings are expressible via TOML and flags, which satisfies D-05/D-08's
"mechanism must exist". A generalised ``SIFT_*`` -> key mapping arrives when
later phases add scalar config keys.
"""

import os
import tomllib
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, field_validator


class SiftConfig(BaseModel):
    # T-04-02: a typo'd key must fail loudly, never be silently dropped.
    model_config = ConfigDict(extra="forbid")

    data_dir: Path
    timezones: dict[str, str] = {}  # glob -> IANA zone name (D-05 override mechanism)
    adapters: dict[str, str] = {}  # glob -> adapter name (same semantics as --adapter)

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
    if flag_overrides:
        layers |= {k: v for k, v in flag_overrides.items() if v is not None}
    return SiftConfig.model_validate(layers)
