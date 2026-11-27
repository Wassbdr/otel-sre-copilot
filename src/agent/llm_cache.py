from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Any

import httpx

_NIM_INTERVAL_S = 60 / 15
_NIM_SLOW_INTERVAL_S = 60 / 9
_NIM_RECOVERY_S = 300
_limiter_lock = Lock()
_last_request_at: float | None = None
_slow_until = 0.0


@dataclass
class RequestStats:
    scope: str
    wait_s: float = 0.0
    replay_adjustment_s: float = 0.0
    cached_requests: int = 0


_stats: ContextVar[RequestStats | None] = ContextVar("llm_request_stats", default=None)


@contextmanager
def request_scope(scope: str) -> Iterator[RequestStats]:
    stats = RequestStats(scope)
    token = _stats.set(stats)
    try:
        yield stats
    finally:
        _stats.reset(token)


def request_stats() -> RequestStats | None:
    return _stats.get()


def _wait_for_nim() -> float:
    global _last_request_at
    entered = time.monotonic()
    with _limiter_lock:
        if _last_request_at is not None:
            now = time.monotonic()
            interval = _NIM_SLOW_INTERVAL_S if now < _slow_until else _NIM_INTERVAL_S
            remaining = _last_request_at + interval - now
            if remaining > 0:
                time.sleep(remaining)
        sent_at = _last_request_at = time.monotonic()
    return sent_at - entered


def _slow_nim() -> None:
    global _slow_until
    with _limiter_lock:
        _slow_until = time.monotonic() + _NIM_RECOVERY_S


class CachedChatClient(httpx.Client):
    def send(
        self, request: httpx.Request, *, stream: bool = False, **kwargs: Any
    ) -> httpx.Response:
        if request.method != "POST" or not request.url.path.endswith("/chat/completions"):
            return super().send(request, stream=stream, **kwargs)

        stats = request_stats()
        cache_path = None
        payload = json.loads(request.content)
        if not payload.get("stream"):
            started = time.monotonic()
            cache_root = Path(os.getenv("XDG_CACHE_HOME") or Path.home() / ".cache")
            cache_dir = Path(os.getenv("LLM_CACHE_DIR") or cache_root / "otel-sre-copilot/llm")
            key = json.dumps(
                [str(request.url), stats.scope if stats else "", payload],
                sort_keys=True,
                separators=(",", ":"),
            )
            cache_path = cache_dir / f"{hashlib.sha256(key.encode()).hexdigest()}.json"
            if cache_path.is_file():
                cached = json.loads(cache_path.read_text())
                hit = httpx.Response(200, json=cached["body"], request=request)
                if stats is not None:
                    stats.cached_requests += 1
                    stats.replay_adjustment_s += cached["elapsed_s"] - (time.monotonic() - started)
                return hit

        if request.url.host == "integrate.api.nvidia.com":
            wait_s = _wait_for_nim()
            if stats is not None:
                stats.wait_s += wait_s

        started = time.monotonic()
        response = super().send(request, stream=stream, **kwargs)
        if response.status_code == 429 and request.url.host == "integrate.api.nvidia.com":
            _slow_nim()
        if cache_path is not None and response.status_code == 200:
            response.read()
            record = {"body": response.json(), "elapsed_s": time.monotonic() - started}
            cache_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with NamedTemporaryFile(mode="w", dir=cache_path.parent, delete=False) as f:
                temp_path = Path(f.name)
                try:
                    json.dump(record, f)
                    f.close()
                    temp_path.replace(cache_path)
                finally:
                    temp_path.unlink(missing_ok=True)
        return response
