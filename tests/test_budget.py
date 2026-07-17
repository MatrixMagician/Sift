"""PromptBudget tests: /tokenize-or-chars//4 estimate + breadth-first fit.

The label-slice budget seam (RAG-05). The client is stubbed — no HTTP, no
socket — so estimate/fit are exercised deterministically.
"""

from sift.llm.budget import PromptBudget


class _FakeClient:
    """Minimal stand-in exposing only what PromptBudget touches."""

    def __init__(self, has_tokenize: bool, count: int | None = None) -> None:
        self.has_tokenize = has_tokenize
        self._count = count

    def tokenize(self, text: str) -> int | None:
        return self._count


def test_estimate_falls_back_to_chars_over_four_without_client() -> None:
    budget = PromptBudget(client=None, ctx_tokens=100, reserve_out=10)
    assert budget.estimate("abcdefgh") == 2  # 8 // 4


def test_estimate_uses_tokenize_when_available() -> None:
    budget = PromptBudget(_FakeClient(True, 7), ctx_tokens=100, reserve_out=10)
    assert budget.estimate("whatever length") == 7


def test_estimate_falls_back_when_tokenize_returns_none() -> None:
    budget = PromptBudget(_FakeClient(True, None), ctx_tokens=100, reserve_out=10)
    assert budget.estimate("abcd") == 1  # 4 // 4


def test_estimate_ignores_tokenize_when_unsupported() -> None:
    budget = PromptBudget(_FakeClient(False, 999), ctx_tokens=100, reserve_out=10)
    assert budget.estimate("abcd") == 1  # chars//4, not the (ignored) 999


def test_fit_returns_all_when_within_budget() -> None:
    excerpts = ["short", "text"]
    budget = PromptBudget(client=None, ctx_tokens=1000, reserve_out=0)
    assert budget.fit(excerpts) == excerpts


def test_fit_shortens_breadth_first_never_dropping_a_cluster() -> None:
    excerpts = ["x" * 400, "y" * 400, "z" * 400]  # ~100 tokens each, 300 total
    budget = PromptBudget(client=None, ctx_tokens=60, reserve_out=0)
    out = budget.fit(excerpts)

    assert len(out) == 3  # every cluster survives — none dropped whole
    assert all(len(e) > 0 for e in out)  # each shortened, not emptied
    assert all(len(a) < len(b) for a, b in zip(out, excerpts))  # all truncated
    total = sum(budget.estimate(e) for e in out)
    assert total <= 60  # result fits the budget
