"""LLM cost estimation from token counts.

NIM free-tier cost is $0, but we track tokens for comparison with paid tiers.
Prices are approximations for llama-3.1-70b-instruct on NIM cloud.
"""

from __future__ import annotations

# Approximate prices per 1M tokens (USD) for NIM meta/llama-3.1-70b-instruct
_INPUT_PRICE_PER_1M = 0.35
_OUTPUT_PRICE_PER_1M = 1.05


def estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """Return estimated USD cost for a single LLM call."""
    return (
        prompt_tokens / 1_000_000 * _INPUT_PRICE_PER_1M
        + completion_tokens / 1_000_000 * _OUTPUT_PRICE_PER_1M
    )
