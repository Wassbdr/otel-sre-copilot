"""Provider resolution, fake LLM and full-graph plumbing (no network, no key)."""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

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


def test_fake_provider_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    assert llm_settings().is_fake
    assert isinstance(make_chat_model(max_tokens=10), FakeChatModel)


def test_fake_model_replays_scripted_responses() -> None:
    fake = FakeChatModel(responses=[AIMessage(content="a"), AIMessage(content="b")])
    assert fake.bind_tools([]) is fake
    assert [fake.invoke([]).content, fake.invoke([]).content] == ["a", "b"]
    assert len(fake.calls) == 2


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

    monkeypatch.setattr("time.sleep", lambda s: None)
    llm.rate_limit_wait_s(reset=True)
    model = _Flaky(failures=2)
    assert llm.invoke_with_backoff(model, []) == "ok"
    assert model.calls == 3


def test_backoff_does_not_retry_real_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.agent import llm

    monkeypatch.setattr("time.sleep", lambda s: None)
    model = _Flaky(failures=1, exc=ValueError)
    with pytest.raises(ValueError):
        llm.invoke_with_backoff(model, [])
    assert model.calls == 1
