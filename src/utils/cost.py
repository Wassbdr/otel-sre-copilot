"""LLM cost estimation from token counts.

The NIM free tier costs $0, so prices default to 0. Set LLM_PRICE_INPUT_PER_1M and
LLM_PRICE_OUTPUT_PER_1M (USD per million tokens) to estimate a paid endpoint.
Tokens are always reported; they are the provider-independent measure.
"""

from __future__ import annotations

import os


def _price(name: str) -> float:
    try:
        return float(os.getenv(name) or 0.0)
    except ValueError:
        return 0.0


def estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """Return estimated USD cost for a single LLM call."""
    return (
        prompt_tokens / 1_000_000 * _price("LLM_PRICE_INPUT_PER_1M")
        + completion_tokens / 1_000_000 * _price("LLM_PRICE_OUTPUT_PER_1M")
    )
