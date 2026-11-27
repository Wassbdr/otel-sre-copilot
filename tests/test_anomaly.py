"""rank_services_by_signal: one call scores every service on a canonical signal."""

from __future__ import annotations

import json
from pathlib import Path

from src.agent.context_manager import ContextBudget
from src.agent.graph import _extract_query_or_id
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
