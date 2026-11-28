"""LLM provider resolution.

Any OpenAI-compatible endpoint works. Resolution order for each setting:
``LLM_*`` → ``NIM_*`` → built-in NVIDIA NIM default. ``LLM_PROVIDER=fake`` swaps in the
deterministic :class:`~src.agent.fake_llm.FakeChatModel` (tests, CI, offline smoke runs).
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import structlog

from src.agent.llm_cache import CachedChatClient, request_stats

log = structlog.get_logger(__name__)
_waited_s = [0.0]

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


def make_chat_model(
    max_tokens: int, json_mode: bool = False, *, concise: bool = False,
) -> Any:  # noqa: ANN401
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
    is_nim = urlsplit(settings.base_url).hostname == "integrate.api.nvidia.com"
    if concise and is_nim and settings.model == DEFAULT_MODEL:
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    timeout = float(os.getenv("LLM_TIMEOUT_S", "90"))
    return ChatOpenAI(
        model=settings.model,
        api_key=settings.api_key,  # type: ignore[arg-type]
        base_url=settings.base_url,
        temperature=0,
        max_tokens=max_tokens,  # type: ignore[call-arg]
        timeout=timeout,
        http_client=CachedChatClient(timeout=timeout),
        max_retries=(
            0 if is_nim
            else int(os.getenv("LLM_MAX_RETRIES", "2"))
        ),
        **kwargs,
    )


_TRANSIENT = ("RateLimit", "Timeout", "APIConnectionError", "InternalServerError")


def invoke_with_backoff(model: Any, messages: Any) -> Any:
    """`model.invoke` that waits out provider rate limits (429), timeouts and 5xx.

    The OpenAI client's own retries back off for seconds; free tiers such as NIM need minutes.
    Time lost to failed attempts and waits is excluded from the reported latency.
    """
    attempts = int(os.getenv("LLM_RATE_LIMIT_RETRIES", "6"))
    for i in range(attempts + 1):
        t0 = time.monotonic()
        stats = request_stats()
        prior_wait = stats.wait_s if stats is not None else 0.0
        try:
            return model.invoke(messages)
        except Exception as e:
            if not any(k in type(e).__name__ for k in _TRANSIENT) or i == attempts:
                raise
            wait_s = min(15 * 2**i, 120) * random.uniform(0.8, 1.2)
            log.warning("llm_transient_error", error=type(e).__name__, attempt=i + 1,
                        wait_s=wait_s)
            time.sleep(wait_s)
            waited = time.monotonic() - t0
            if stats is not None:
                stats.wait_s = prior_wait + waited
            else:
                _waited_s[0] += waited
    raise AssertionError("unreachable")


def rate_limit_wait_s(reset: bool = False) -> float:
    """Seconds lost to provider errors since the last reset (excluded from reported latency)."""
    stats = request_stats()
    if stats is not None:
        waited = stats.wait_s
        if reset:
            stats.wait_s = 0.0
        return waited
    waited = _waited_s[0]
    if reset:
        _waited_s[0] = 0.0
    return waited
