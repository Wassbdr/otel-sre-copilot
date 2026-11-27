"""LLM provider resolution.

Any OpenAI-compatible endpoint works. Resolution order for each setting:
``LLM_*`` → ``NIM_*`` → built-in NVIDIA NIM default. ``LLM_PROVIDER=fake`` swaps in the
deterministic :class:`~src.agent.fake_llm.FakeChatModel` (tests, CI, offline smoke runs).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
# meta/llama-3.1-70b-instruct was retired from the NIM catalog on 2026-08-26 (HTTP 410).
DEFAULT_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    base_url: str
    api_key: str
    model: str

    @property
    def is_fake(self) -> bool:
        return self.provider == "fake"


def _first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def llm_settings() -> LLMSettings:
    """Resolve the LLM endpoint from the environment (LLM_* first, NIM_* as fallback)."""
    provider = _first("LLM_PROVIDER", default="openai-compatible").lower()
    model = _first("LLM_MODEL", "NIM_MODEL", default=DEFAULT_MODEL)
    if provider == "fake" or model == "fake":
        return LLMSettings("fake", "", "", "fake-scripted")
    return LLMSettings(
        provider=provider,
        base_url=_first("LLM_BASE_URL", "NIM_BASE_URL", default=DEFAULT_BASE_URL),
        api_key=_first("LLM_API_KEY", "NIM_API_KEY"),
        model=model,
    )


def make_chat_model(max_tokens: int, json_mode: bool = False) -> Any:  # noqa: ANN401
    """Build the chat model for the current settings (temperature 0 for reproducibility)."""
    settings = llm_settings()
    if settings.is_fake:
        from src.agent.fake_llm import FakeChatModel

        return FakeChatModel.from_env()

    from langchain_openai import ChatOpenAI

    if not settings.api_key:
        raise RuntimeError(
            "No LLM API key: set LLM_API_KEY (or NIM_API_KEY), or LLM_PROVIDER=fake for an "
            "offline scripted run."
        )
    kwargs: dict[str, Any] = {}
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    return ChatOpenAI(
        model=settings.model,
        api_key=settings.api_key,  # type: ignore[arg-type]
        base_url=settings.base_url,
        temperature=0,
        max_tokens=max_tokens,  # type: ignore[call-arg]
        timeout=float(os.getenv("LLM_TIMEOUT_S", "180")),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
        **kwargs,
    )
