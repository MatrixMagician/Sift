"""Advisory LLM-as-judge grade for a case's hypotheses (EVAL-04, D-08).

Opt-in second opinion: grades how well a case's generated hypotheses match its
frozen ground-truth ``root_cause``, using the SAME local model via the sole HTTP
boundary ``InferenceClient.chat`` — no framework, no new HTTP path. The score is
ADVISORY: ``sift eval --judge`` reports it alongside the keyword metrics but it
NEVER enters the threshold gate or the exit code (D-08).

Parsing is lenient, in the project's established never-crash-on-model-output
idiom (mirrors ``hypothesise._validate``): any parse/transport error degrades to
``None`` (ungraded) rather than raising, so a malformed judge reply can neither
crash the eval run nor alter its verdict.
"""

from __future__ import annotations

import importlib.resources
from typing import TYPE_CHECKING, Annotated

import httpx
from pydantic import Field, TypeAdapter
from pydantic.dataclasses import dataclass

if TYPE_CHECKING:
    from sift.eval.truth import Truth
    from sift.llm.client import InferenceClient
    from sift.store import StoredHypothesis

_PROMPT_PACKAGE = "sift.prompts"
_PROMPT_FILE = "judge.md"


@dataclass(frozen=True)
class JudgeScore:
    """A parsed, validated advisory judge grade.

    ``score`` is constrained to [0.0, 1.0] by Pydantic on construction; an
    out-of-range or malformed reply raises ``ValidationError`` (a ``ValueError``)
    that ``judge_case`` swallows into ``None`` (degrade, never crash).
    """

    score: Annotated[float, Field(ge=0.0, le=1.0)]
    justification: str


_JUDGE_ADAPTER = TypeAdapter(JudgeScore)


def load_judge_template() -> str:
    """Load the versioned judge prompt from package data (CLI-02)."""
    return (
        importlib.resources.files(_PROMPT_PACKAGE)
        .joinpath(_PROMPT_FILE)
        .read_text(encoding="utf-8")
    )


def _schema_rf(schema: dict[str, object]) -> dict[str, object]:
    """The llama.cpp constrained-decoding shape (mirrors hypothesise._schema_rf).

    ``{"type": "json_schema", "schema": <schema>}`` — schema at
    ``response_format.schema`` top-level, never alongside a ``grammar`` field.
    Best-effort: Pydantic validation is the backstop if a server ignores it.
    """
    return {"type": "json_schema", "schema": schema}


def _render_hypotheses(hypotheses: list[StoredHypothesis]) -> str:
    if not hypotheses:
        return "(no hypotheses were generated)"
    return "\n".join(
        f"{i}. {hyp.title}\n   {hyp.narrative}"
        for i, hyp in enumerate(hypotheses, start=1)
    )


def _build_prompt(
    template: str, truth: Truth, hypotheses: list[StoredHypothesis]
) -> str:
    return (
        f"{template}\n"
        f"Ground-truth root cause:\n{truth.root_cause}\n\n"
        f"Generated hypotheses:\n{_render_hypotheses(hypotheses)}\n"
    )


def judge_case(
    client: InferenceClient,
    truth: Truth,
    hypotheses: list[StoredHypothesis],
) -> JudgeScore | None:
    """Grade the hypotheses against ``truth.root_cause`` — advisory, never raises.

    Assembles the versioned judge prompt, calls the sole HTTP boundary
    ``InferenceClient.chat`` (constrained decoding when the server honours it),
    and validates the reply with Pydantic. Any transport failure or malformed /
    empty / schema-invalid reply degrades to ``None`` (ungraded) — the
    never-crash-on-model-output idiom. The judge NEVER touches the gate (D-08).
    """
    prompt = _build_prompt(load_judge_template(), truth, hypotheses)
    messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]
    rf = _schema_rf(_JUDGE_ADAPTER.json_schema())
    try:
        raw = client.chat(messages, response_format=rf)
        return _JUDGE_ADAPTER.validate_json(raw)
    except (httpx.HTTPError, ValueError):
        return None


__all__ = ["JudgeScore", "judge_case", "load_judge_template"]
