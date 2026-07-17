"""The label-slice token budget seam (RAG-05).

`PromptBudget` estimates token counts — exactly via the server's ``/tokenize``
when available, else the ``len(text) // 4`` heuristic — and truncates a list of
per-cluster exemplar excerpts *breadth-first* so the whole set fits the context
budget without ever dropping a cluster entirely. This is the label-budgeting
slice only; full triage-prompt budgeting lands in Phase 4.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class _Tokenizer(Protocol):
    """The slice of `InferenceClient` that `PromptBudget` depends on."""

    has_tokenize: bool

    def tokenize(self, text: str) -> int | None: ...


class PromptBudget:
    """Estimate token counts and fit exemplar excerpts to a context budget.

    Args:
        client: Inference client for exact token counts, or ``None`` to always
            use the character heuristic.
        ctx_tokens: The model's context window in tokens.
        reserve_out: Tokens reserved for the model's own output (headroom).
    """

    def __init__(
        self, client: _Tokenizer | None, ctx_tokens: int, reserve_out: int
    ) -> None:
        self._client = client
        self._ctx_tokens = ctx_tokens
        self._reserve_out = reserve_out

    def estimate(self, text: str) -> int:
        """Return the token count for ``text`` (exact if available, else //4)."""
        if self._client is not None and self._client.has_tokenize:
            count = self._client.tokenize(text)
            if count is not None:
                return count
        return max(1, len(text) // 4)

    def fit(self, excerpts: Sequence[str]) -> list[str]:
        """Truncate excerpts breadth-first so the whole set fits the budget.

        Every excerpt keeps an equal share of the budget rather than dropping
        whole clusters — so a cluster is never lost before others are shortened.
        """
        if not excerpts:
            return []
        budget = max(1, self._ctx_tokens - self._reserve_out)
        if sum(self.estimate(excerpt) for excerpt in excerpts) <= budget:
            return list(excerpts)
        per_excerpt = max(1, budget // len(excerpts))
        # ponytail: char cap inverts the //4 heuristic — exact-tokenizer fitting
        # is Phase-4 triage-budget work, not needed for short labels.
        max_chars = per_excerpt * 4
        return [excerpt[:max_chars] for excerpt in excerpts]
