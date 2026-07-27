"""Frozen ground-truth model + safe loader for a golden case's ``truth.yaml``.

``load_truth`` uses ``yaml.safe_load`` ONLY — never ``yaml.load``/``full_load``,
which construct arbitrary Python objects and are a code-execution vector
(T-07-01). The parsed data is then validated through the ``Truth`` Pydantic model
with ``extra="forbid"`` (mirroring ``config.py``), so a typo'd truth key fails
loudly rather than being silently dropped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict


class ExpectEustack(BaseModel):
    """An eu-stack golden case's expected deterministic figures (EUS-12).

    Detection here is FIGURE REPRODUCTION, never flag presence (D-19-17):
    a case passes when ``analyse_eustack_bundle`` reproduces every declared
    figure exactly, not when ``bundle.saturation.flags`` is merely non-empty.
    ``analyse_saturation`` grades only three dimensions and both percentage
    flags append unconditionally for any non-empty dump (D-19-18), so the
    expected flag set is declared by severity bucket rather than as a bare
    count: zero ``warn``/``critical`` on the healthy case, and the expected
    ``info`` dimension names stated explicitly so an ``info`` dimension
    escalating to ``warn`` fails the case instead of passing unnoticed.

    Own ``extra="forbid"`` independent of ``Truth``'s, so a typo'd key inside
    this block fails loudly rather than being silently dropped (T-07-01).
    """

    model_config = ConfigDict(extra="forbid")

    provenance: Literal["authored", "observed"]
    hang_detected: bool
    total_threads: int
    warn: int = 0
    critical: int = 0
    info_dimensions: list[str] = []
    pools: dict[str, int] = {}
    dependencies: dict[str, int] = {}


class Truth(BaseModel):
    """A golden case's frozen ground truth (D-03/D-04).

    ``required_evidence`` are regex patterns matched against the cluster
    exemplars fed to the model; ``acceptable_keywords`` drive the any-of hit@k
    match against a hypothesis's title + narrative. ``expect_no_incident`` marks
    the negative case, scored by the no-confident-hypothesis predicate.
    ``expect_eustack`` marks an LLM-free eu-stack case (EUS-12), scored
    directly against ``analyse_eustack_bundle`` instead.
    """

    # A typo'd truth key must fail loudly, never be silently dropped (T-07-01).
    model_config = ConfigDict(extra="forbid")

    root_cause: str
    required_evidence: list[str] = []
    acceptable_keywords: list[str] = []
    expect_no_incident: bool = False
    expect_eustack: ExpectEustack | None = None


def load_truth(path: Path) -> Truth:
    """Parse and validate a ``truth.yaml`` file into a ``Truth``.

    Reads the file text, parses it with the SAFE YAML loader, then validates the
    shape. Any custom-tag payload is refused by ``safe_load`` (a ``yaml.YAMLError``)
    and never executed — the anti-RCE guarantee for the eval trust boundary.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Truth.model_validate(data or {})
