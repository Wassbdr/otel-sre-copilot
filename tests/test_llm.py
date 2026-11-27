"""Provider resolution, fake LLM and full-graph plumbing (no network, no key)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool

from src.agent.fake_llm import FakeChatModel
from src.agent.llm import DEFAULT_BASE_URL, DEFAULT_MODEL, llm_settings, make_chat_model

_ENV = ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
        "NIM_BASE_URL", "NIM_API_KEY", "NIM_MODEL")
FIXTURE = Path(__file__).parent / "fixtures" / "snapshot-fixture"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)


def test_defaults_to_nvidia_nim() -> None:
    s = llm_settings()
    assert (s.base_url, s.model, s.api_key) == (DEFAULT_BASE_URL, DEFAULT_MODEL, "")


def test_nim_variables_are_the_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIM_API_KEY", "nim-key")
    monkeypatch.setenv("NIM_MODEL", "nim/model")
    s = llm_settings()
    assert (s.api_key, s.model) == ("nim-key", "nim/model")


def test_llm_variables_win_over_nim(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in {"NIM_API_KEY": "nim", "NIM_MODEL": "nim/m", "NIM_BASE_URL": "http://nim",
                 "LLM_API_KEY": "llm", "LLM_MODEL": "gpt-x",
                 "LLM_BASE_URL": "http://localhost:11434/v1"}.items():
        monkeypatch.setenv(k, v)
    s = llm_settings()
    assert (s.api_key, s.model, s.base_url) == ("llm", "gpt-x", "http://localhost:11434/v1")


def test_blank_llm_variable_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "  ")
    monkeypatch.setenv("NIM_MODEL", "nim/m")
    assert llm_settings().model == "nim/m"


def test_missing_key_is_an_explicit_error() -> None:
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        make_chat_model(max_tokens=10)


def test_fast_nemotron_requests_disable_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIM_API_KEY", "example")
    expected = {"chat_template_kwargs": {"enable_thinking": False}}
    assert make_chat_model(4096, concise=True).extra_body == expected
    assert make_chat_model(8192, json_mode=True, concise=True).extra_body == expected
    assert make_chat_model(4096).extra_body is None
    monkeypatch.setenv("LLM_MODEL", "different-model")
    assert make_chat_model(4096, concise=True).extra_body is None


def test_fake_provider_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    assert llm_settings().is_fake
    assert isinstance(make_chat_model(max_tokens=10), FakeChatModel)


def test_fake_model_replays_scripted_responses() -> None:
    fake = FakeChatModel(responses=[AIMessage(content="a"), AIMessage(content="b")])
    assert fake.bind_tools([]) is fake
    assert [fake.invoke([]).content, fake.invoke([]).content] == ["a", "b"]
    assert len(fake.calls) == 2


def test_nim_requests_are_cached_and_paced_across_clients(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from src.agent import llm, llm_cache

    monkeypatch.setenv("NIM_API_KEY", "example")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(llm_cache, "_last_request_at", None)
    now = 40.0

    def advance(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr(llm_cache.time, "monotonic", lambda: now)
    monkeypatch.setattr(llm_cache.time, "sleep", advance)
    calls: list[float] = []

    def reply(request: httpx.Request) -> httpx.Response:
        calls.append(now)
        return httpx.Response(200, json={
            "id": f"answer-{len(calls)}",
            "object": "chat.completion",
            "model": llm.DEFAULT_MODEL,
            "created": 1,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": str(len(calls))},
                "finish_reason": "stop",
            }],
        })

    monkeypatch.setattr(
        llm, "CachedChatClient",
        lambda **kwargs: llm_cache.CachedChatClient(
            **kwargs, transport=httpx.MockTransport(reply),
        ),
    )
    with llm_cache.request_scope("bench:0") as stats:
        assert llm.make_chat_model(10).invoke("hello").content == "1"
        assert llm.make_chat_model(10).invoke("hello").content == "1"
        assert llm.make_chat_model(11, json_mode=True).invoke("hello").content == "2"
        assert stats.cached_requests == 1
        assert stats.wait_s == 4.0
    with llm_cache.request_scope("bench:1"):
        assert llm.make_chat_model(10).invoke("hello").content == "3"
    assert calls == [40.0, 44.0, 48.0]
    assert len(list(tmp_path.glob("*.json"))) == 3


def test_graph_runs_end_to_end_with_fake_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    from eval.grounding_verifier import verify
    from src.agent.graph import build_graph
    from src.agent.schemas import initial_state
    from src.datasources.replay import ReplayDataSource

    monkeypatch.setenv("LLM_PROVIDER", "fake")
    events: list[dict[str, object]] = []
    graph = build_graph(ReplayDataSource(FIXTURE), on_event=events.append)
    state = initial_state("fixture", "2024-01-15T14:00:00Z", "2024-01-15T14:10:00Z", "otel-demo")
    result = graph.invoke(state)

    report = result["final_report"]
    assert report.root_causes[0].service == "frontend"
    tool_names = [c["tool_name"] for c in result["tool_calls_log"]]
    assert tool_names == ["get_service_topology", "query_prometheus_range", "search_traces"]
    assert any(e["type"] == "tool_call" for e in events)
    # The fake cites exactly the PromQL it ran, so the external verifier must accept it.
    assert verify(report, result["tool_calls_log"]).grounding_score == 1.0


@pytest.mark.parametrize(
    ("react", "prior", "seeded"),
    [(False, True, ["rank_incident_anomalies", "rank_request_rate_drops"]),
     (False, False, ["rank_request_rate_drops"]), (True, False, [])],
)
def test_fast_graph_limits_llm_calls_and_seeds_only_available_prior(
    monkeypatch: pytest.MonkeyPatch, react: bool, prior: bool, seeded: list[str],
) -> None:
    from src.agent.graph import build_graph
    from src.agent.schemas import initial_state
    from src.datasources.replay import ReplayDataSource

    monkeypatch.setenv("LLM_PROVIDER", "fake")
    bound_tools = []
    bind_tools = FakeChatModel.bind_tools

    def capture_tools(model: FakeChatModel, tools: Sequence[BaseTool]) -> FakeChatModel:
        bound_tools.extend(tool.name for tool in tools)
        return bind_tools(model, tools)

    monkeypatch.setattr(FakeChatModel, "bind_tools", capture_tools)
    graph = build_graph(ReplayDataSource(FIXTURE), improved=not react, react=react, prior=prior)
    state = initial_state("fixture", "2024-01-15T14:00:00Z", "2024-01-15T14:10:00Z", "otel-demo")
    result = graph.invoke(state)
    assert result["token_usage"]["llm_calls"] == 3
    assert [call["tool_name"] for call in result["tool_calls_log"]] == [
        *seeded, "get_service_topology", "query_prometheus_range",
    ]
    assert "query_prometheus_range" in bound_tools
    assert set(seeded).isdisjoint(bound_tools)


def test_nim_429_slows_subsequent_requests_until_recovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from src.agent import llm_cache

    now = 40.0

    def advance(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(llm_cache, "_last_request_at", None)
    monkeypatch.setattr(llm_cache, "_slow_until", 0.0)
    monkeypatch.setattr(llm_cache.time, "monotonic", lambda: now)
    monkeypatch.setattr(llm_cache.time, "sleep", advance)
    sent: list[float] = []

    def respond(_: httpx.Request) -> httpx.Response:
        sent.append(now)
        return httpx.Response(429 if len(sent) == 1 else 200, json={})

    with llm_cache.CachedChatClient(transport=httpx.MockTransport(respond)) as client:
        endpoint = "https://integrate.api.nvidia.com/v1/chat/completions"
        for index in range(2):
            client.post(endpoint, json={"index": index})
        assert sent == pytest.approx([40, 40 + 60 / 9])
        now = 340.0
        for index in range(2, 4):
            client.post(endpoint, json={"index": index})
        assert sent[-2:] == pytest.approx([340, 344])


class RateLimitError(Exception):
    pass


class _Flaky:
    def __init__(self, failures: int, exc: type[Exception] = RateLimitError) -> None:
        self.failures, self.exc, self.calls = failures, exc, 0

    def invoke(self, messages: object) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exc("429")
        return "ok"


def test_backoff_waits_out_rate_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.agent import llm

    delays: list[float] = []
    monkeypatch.setattr("time.sleep", delays.append)
    monkeypatch.setattr("random.uniform", lambda low, high: 1.1)
    llm.rate_limit_wait_s(reset=True)
    model = _Flaky(failures=2)
    assert llm.invoke_with_backoff(model, []) == "ok"
    assert model.calls == 3
    assert delays == [pytest.approx(16.5), pytest.approx(33)]


def test_backoff_does_not_retry_real_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.agent import llm

    monkeypatch.setattr("time.sleep", lambda s: None)
    model = _Flaky(failures=1, exc=ValueError)
    with pytest.raises(ValueError):
        llm.invoke_with_backoff(model, [])
    assert model.calls == 1


def test_invalid_report_gets_one_repair_round(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.agent import graph as graph_mod
    from src.agent.schemas import initial_state
    from src.datasources.replay import ReplayDataSource

    monkeypatch.setenv("LLM_PROVIDER", "fake")
    original = graph_mod.make_chat_model
    report_models: list[FakeChatModel] = []

    def first_report_invalid(**kw: object) -> object:
        if not kw.get("json_mode"):
            return original(**kw)  # type: ignore[arg-type]
        report_models.append(FakeChatModel(responses=[AIMessage(content='{"root_causes": [1]}')]))
        return report_models[-1]

    monkeypatch.setattr(graph_mod, "make_chat_model", first_report_invalid)
    events: list[dict[str, object]] = []
    graph = graph_mod.build_graph(ReplayDataSource(FIXTURE), on_event=events.append)
    state = initial_state("fixture", "2024-01-15T14:00:00Z", "2024-01-15T14:10:00Z", "otel-demo")
    report = graph.invoke(state)["final_report"]

    assert report.root_causes[0].service == "frontend"
    assert len(report_models[0].calls) == 2
    assert any(e["type"] == "report_repair" for e in events)
