"""Inference boundary (SPEC.md §5.6): the only package in Sift that talks HTTP.

`client.py` holds the single injectable `InferenceClient` (SSRF-guarded,
retry-capable) and `budget.py` the label-slice `PromptBudget` token seam.
"""
