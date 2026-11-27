from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import numpy as np

from src.agent.schemas import InvestigationReport, RootCauseHypothesis
from src.datasources.live import ASTRONOMY_SHOP_SERVICES
from src.datasources.protocol import DataSource
from src.telemetry_queries import METRIC_QUERIES, SIGNAL_TO_FAULT

RCAEvalMethod = Literal["baro", "nsigma"]


def rank_signal(
    baseline: list[float], incident: list[float], method: RCAEvalMethod,
) -> float:
    if method == "baro":
        q1, median, q3 = np.percentile(baseline, [25, 50, 75])
        center, scale = float(median), float(q3 - q1)
    else:
        center, scale = float(np.mean(baseline)), float(np.std(baseline))
    if scale < 10 * np.finfo(float).eps:
        scale = 1.0
    return (max(incident) - center) / scale


class RCAEvalBaseline:
    """RCAEval's per-metric BARO/N-Sigma ranking, projected to unique services."""

    def __init__(self, method: RCAEvalMethod) -> None:
        self.method = method

    def predict(
        self, ds: DataSource, start: str, end: str, namespace: str, scenario_id: str,
    ) -> InvestigationReport:
        baseline_start = (datetime.fromisoformat(start) - timedelta(minutes=30)).isoformat()
        scores: list[tuple[float, str, str]] = []
        for service in ASTRONOMY_SHOP_SERVICES:
            for signal in SIGNAL_TO_FAULT:
                query = METRIC_QUERIES[signal].format(svc=service)
                baseline = _values(ds.query_prometheus_range(query, baseline_start, start))
                incident = _values(ds.query_prometheus_range(query, start, end))
                if baseline and incident:
                    scores.append((rank_signal(baseline, incident, self.method), service, signal))

        hypotheses: list[RootCauseHypothesis] = []
        seen: set[str] = set()
        for score, service, signal in sorted(scores, key=lambda item: -item[0]):
            if service in seen:
                continue
            seen.add(service)
            hypotheses.append(RootCauseHypothesis(
                rank=len(hypotheses) + 1,
                service=service,
                fault_type=SIGNAL_TO_FAULT[signal],  # type: ignore[arg-type]
                description=f"{self.method}: {signal} standardized maximum {score:.2f}",
                confidence=0.0,
            ))
            if len(hypotheses) == 3:
                break

        payload: dict[str, Any] = {
            "incident_id": scenario_id,
            "investigation_start_ts": start,
            "investigation_end_ts": datetime.now(UTC).isoformat(),
            "root_causes": hypotheses,
            "fault_type_classification": hypotheses[0].fault_type if hypotheses else "unknown",
            "llm_model": self.method,
        }
        if not hypotheses:
            return InvestigationReport.model_construct(**payload)
        return InvestigationReport.model_validate(payload)


def _values(series: list[dict[str, object]]) -> list[float]:
    values: list[float] = []
    for entry in series:
        samples = entry.get("values")
        if not isinstance(samples, list):
            continue
        for _, raw in samples:
            try:
                value = float(raw)
            except (ValueError, TypeError):
                continue
            if np.isfinite(value):
                values.append(value)
    return values
