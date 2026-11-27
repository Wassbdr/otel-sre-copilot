from __future__ import annotations

from typing import cast

import pytest

from eval.grounding_verifier import verify
from src.agent import candidates
from src.agent.schemas import EvidenceItem, InvestigationReport, RootCauseHypothesis
from src.anomaly import MetricWindow
from src.datasources.protocol import DataSource

START = "2024-01-15T14:00:00+00:00"
END = "2024-01-15T14:10:00+00:00"


class Observations:
    def search_traces(self, *args: object, **kwargs: object) -> list[dict[str, object]]:
        return []

    def get_pod_events(self, *args: object, **kwargs: object) -> list[dict[str, object]]:
        return [{
            "involved_object_name": "heap-service-abc",
            "reason": "OOMKilled",
            "message": "Container exceeded its limit",
            "last_time": "2024-01-15T14:01:00+00:00",
        }, {
            "involved_object_name": "worker-xyz",
            "reason": "OOMKilled",
            "last_time": "2024-01-15T13:00:00+00:00",
        }]

    def get_service_topology(self, namespace: str) -> dict[str, list[str]]:
        return {"gateway": ["downstream"]}

    def query_loki(self, *args: object, **kwargs: object) -> list[dict[str, object]]:
        return []


def test_candidates_use_fault_fingerprints_and_cite_observations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows = [
        MetricWindow("heap-service", "pod_restarts", [0, 0], [0, 1]),
        MetricWindow("worker", "pod_restarts", [0, 0], [0, 2]),
        MetricWindow("processor", "cpu_throttle_ratio", [0.1, 0.12], [0.56, 0.55]),
        MetricWindow("gateway", "request_rate", [4, 4], [1, 1]),
        MetricWindow("downstream", "request_rate", [4, 4], [1, 1]),
    ]

    def get_windows(
        ds: DataSource, signals: list[str], start: str, end: str, *,
        services: list[str] | None = None, namespace: str = "otel-demo",
    ) -> list[MetricWindow]:
        return [w for w in windows if w.signal in signals]

    monkeypatch.setattr(candidates, "metric_windows", get_windows)
    ds = cast(DataSource, Observations())
    prior = candidates.rank_candidates(ds, START, END, "example", [
        "heap", "heap-service", "worker", "processor", "gateway", "downstream",
    ])
    assert [(h.service, h.fault_type) for h in prior] == [
        ("heap-service", "memory_stress"), ("processor", "cpu_stress"),
        ("worker", "pod_crash"), ("downstream", "http_abort"), ("gateway", "http_abort"),
    ]
    assert prior[0].evidence[0].observed_value == "mean=0.5, peak=1"
    assert prior[0].evidence[1].query_or_id == "k8s_event:heap-service-abc:OOMKilled"


def test_combine_drops_unknown_refs_allows_one_addition_and_fills() -> None:
    def cause(
        rank: int, service: str, fault: candidates.Fault, *cites: str,
    ) -> RootCauseHypothesis:
        return RootCauseHypothesis(
            rank=rank, service=service, fault_type=fault, description="Observation",
            confidence=0.5,
            evidence=[EvidenceItem(signal_type="metric", query_or_id=c, observed_value="2")
                      for c in cites],
        )

    memory = cause(1, "heap", "memory_stress", "metric:memory_usage:heap")
    crash = cause(2, "worker", "pod_crash", "metric:pod_restarts:worker")
    cpu = cause(3, "task", "cpu_stress", "metric:cpu_usage:task")
    added = cause(2, "edge", "http_abort", "metric:error_rate:edge")
    observed = {f"metric|{ev.query_or_id}" for h in (memory, crash, cpu, added)
                for ev in h.evidence}
    report = InvestigationReport(
        incident_id="incident", investigation_start_ts=START, investigation_end_ts=END,
        fault_type_classification="cpu_stress", remediation_steps=["Stale advice."],
        root_causes=[
            cause(1, "task", "cpu_stress", "metric:cpu_usage:task", "fabricated"),
            added, cause(3, "worker", "cpu_stress", "metric:pod_restarts:worker"),
        ],
    )
    result = candidates.combine_rankings(report, [memory, crash, cpu], observed)
    assert [(h.rank, h.service, h.fault_type) for h in result.root_causes] == [
        (1, "edge", "http_abort"), (2, "heap", "memory_stress"), (3, "worker", "pod_crash"),
    ]
    assert result.fault_type_classification == "http_abort"
    assert not result.remediation_steps
    grounding = verify(result, [{"evidence_ids": [ref.split("|")[1] for ref in observed]}])
    assert grounding.total_count == grounding.verified_count == 3

    reranked = candidates.combine_rankings(
        report.model_copy(update={"root_causes": [crash]}), [memory, crash, cpu], observed,
    )
    assert [h.service for h in reranked.root_causes] == ["worker", "heap", "task"]

    anchored = candidates.combine_rankings(
        report.model_copy(update={"root_causes": [
            h.model_copy(update={"rank": i}) for i, h in enumerate((added, cpu, memory), 1)
        ]}),
        [crash, memory, cpu], observed,
    )
    assert [h.service for h in anchored.root_causes] == ["worker", "edge", "task"]
