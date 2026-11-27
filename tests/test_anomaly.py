"""rank_services_by_signal: one call scores every service on a canonical signal."""

from __future__ import annotations

import json
from pathlib import Path

from src.agent.context_manager import ContextBudget
from src.agent.graph import _evidence_ids, _extract_query_or_id
from src.agent.tools import make_tools
from src.anomaly import rank_services
from src.datasources.replay import ReplayDataSource
from src.telemetry_queries import METRIC_QUERIES

FIXTURE = Path(__file__).parent / "fixtures" / "snapshot-fixture"


def _window() -> tuple[str, str]:
    meta = json.loads((FIXTURE / "metadata.json").read_text())
    return meta["window_start"], meta["window_end"]


def test_rank_services_sorted_and_covers_all_services() -> None:
    start, end = _window()
    scores = rank_services(ReplayDataSource(FIXTURE), "error_rate", start, end)
    assert len(scores) == 15
    zs = [s.z for s in scores]
    assert zs == sorted(zs, reverse=True)


def test_tool_output_carries_citable_promql() -> None:
    start, end = _window()
    tools = {t.name: t for t in make_tools(ReplayDataSource(FIXTURE), ContextBudget())}
    out = tools["rank_services_by_signal"].invoke(
        {"signal": "pod_restarts", "start": start, "end": end})
    assert METRIC_QUERIES["pod_restarts"].format(svc="checkout") in out
    qids = _extract_query_or_id("rank_services_by_signal", {"signal": "pod_restarts"})
    assert METRIC_QUERIES["pod_restarts"].format(svc="checkout") in qids


def test_unknown_signal_is_reported_not_raised() -> None:
    start, end = _window()
    tools = {t.name: t for t in make_tools(ReplayDataSource(FIXTURE), ContextBudget())}
    out = tools["rank_services_by_signal"].invoke({"signal": "nope", "start": start, "end": end})
    assert out.startswith("[ERROR")


def test_full_agent_prior_and_no_prior_ablation() -> None:
    ds = ReplayDataSource(FIXTURE)
    start, end = _window()
    full = {t.name: t for t in make_tools(ds, ContextBudget(), improved=True, prior=True)}
    ablation = {t.name for t in make_tools(ds, ContextBudget(), improved=True)}
    assert full.keys() - ablation == {"rank_incident_anomalies"}
    result = full["rank_incident_anomalies"].invoke({"start": start, "end": end})
    assert "composite:" in result and "n-sigma:" in result
    assert _evidence_ids("rank_incident_anomalies", result)
    assert not _evidence_ids("query_loki", result)


def test_request_rate_tool_surfaces_recorded_payment_drop() -> None:
    snapshot = Path(__file__).parents[1] / "snapshots/payment-http_abort-seed7"
    meta = json.loads((snapshot / "metadata.json").read_text())
    tools = {
        t.name: t for t in make_tools(ReplayDataSource(snapshot), ContextBudget(), improved=True)
    }
    result = tools["rank_request_rate_drops"].invoke(
        {"start": meta["window_start"], "end": meta["window_end"]},
    )
    assert result.splitlines()[1].startswith("metric:request_rate:payment ")


def test_trace_tool_exposes_shipping_wait_with_complete_trace_citation() -> None:
    snapshot = Path(__file__).parents[1] / "snapshots/shipping-high_latency-seed42"
    meta = json.loads((snapshot / "metadata.json").read_text())
    tools = {
        t.name: t for t in make_tools(ReplayDataSource(snapshot), ContextBudget(), improved=True)
    }
    result = tools["summarize_trace_latency"].invoke(
        {"start": meta["window_start"], "end": meta["window_end"]},
    )
    assert "shipping client wait outside paired server" in result
    for citation in _evidence_ids("summarize_trace_latency", result):
        assert (snapshot / "tempo" / "traces" / f"{citation.removeprefix('trace:')}.json").exists()
