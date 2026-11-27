import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from eval import holmes
from src.agent.llm_cache import CachedChatClient
from src.telemetry_queries import METRIC_QUERIES

SNAPSHOT = Path(__file__).parents[1] / "snapshots/cart-memory_stress-seed42"


def test_holmes_scores_via_paced_cache_and_observed_replay_queries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOLMES_PYTHON", "holmes-python")
    monkeypatch.setenv("LLM_API_KEY", "example-upstream")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LLM_BASE_URL", holmes.DEFAULT_BASE_URL)
    upstream = Mock(return_value=httpx.Response(200, json={"id": "completion"}))
    monkeypatch.setattr(holmes, "CachedChatClient", lambda **kw: CachedChatClient(
        **kw, transport=httpx.MockTransport(upstream),
    ))
    query = METRIC_QUERIES["memory_usage"].format(svc="cart")

    def worker(args: list[str], *, env: dict[str, str], **_kwargs: object) -> None:
        _, _, url, model, _, output = args
        assert "LLM_API_KEY" not in env
        body = {"model": model, "messages": [{"role": "user", "content": "incident"}]}
        with httpx.Client(base_url=url) as client:
            assert client.post("/v1/chat/completions", json=body).status_code == 401
            for _ in range(2):
                response = client.post("/v1/chat/completions", json=body, headers={
                    "Authorization": f"Bearer {env['NVIDIA_NIM_API_KEY']}",
                })
                assert response.json() == {"id": "completion"}
            response = client.get("/api/v1/query_range", params={"query": query})
            assert response.json()["data"]["result"]
        report = {"root_causes": [{
            "rank": 1, "service": "cart", "fault_type": "memory_stress",
            "description": "Memory rose", "confidence": 0.9, "evidence": [{
                "signal_type": "metric", "query_or_id": query, "observed_value": "memory rose",
            }],
        }]}
        Path(output).write_text(json.dumps({
            "num_llm_calls": 2, "prompt_tokens": 3, "completion_tokens": 2,
            "result": json.dumps(report),
        }))

    monkeypatch.setattr(holmes.subprocess, "run", worker)
    result = holmes.run_holmes(SNAPSHOT, tmp_path / "trace.json", "benchmark")
    assert upstream.call_count == result["cached_requests"] == 1
    assert upstream.call_args.args[0].headers["Authorization"] == "Bearer example-upstream"
    assert result["accuracy_at_1"] == result["verified_evidence_count"] == 1
