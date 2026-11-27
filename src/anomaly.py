"""Per-service anomaly scores over the canonical signals.

Same statistic as the composite Z-score baseline (mean of the incident window against the
pre-incident baseline), exposed to the agent as a tool so it can sweep 15 services in one call
instead of spending its tool budget on one PromQL query per service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from src.datasources.live import ASTRONOMY_SHOP_SERVICES
from src.datasources.protocol import DataSource
from src.telemetry_queries import METRIC_QUERIES

# Live mode reads 30 minutes before the window. Recorded snapshots hold a shorter baseline
# (8 min by default); ReplayDataSource serves it because it matches on the window end.
BASELINE_MINUTES = 30


@dataclass(frozen=True)
class ServiceScore:
    service: str
    z: float
    window_mean: float
    baseline_mean: float
    baseline_std: float
    query: str
    has_data: bool


def values(series: list[dict[str, Any]]) -> list[float]:
    out: list[float] = []
    for s in series:
        for _ts, val in s.get("values", []):
            try:
                v = float(val)
            except (ValueError, TypeError):
                continue
            if v == v:  # drop NaN
                out.append(v)
    return out


def minus_minutes(iso_ts: str, minutes: int) -> str:
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return (dt - timedelta(minutes=minutes)).isoformat()


def rank_services(ds: DataSource, signal: str, start: str, end: str,
                  services: list[str] | None = None) -> list[ServiceScore]:
    """Score every service on one signal, most anomalous first."""
    if signal not in METRIC_QUERIES:
        raise ValueError(f"unknown signal {signal!r}; choose one of {sorted(METRIC_QUERIES)}")
    baseline_start = minus_minutes(start, BASELINE_MINUTES)
    scores: list[ServiceScore] = []
    for svc in services or ASTRONOMY_SHOP_SERVICES:
        query = METRIC_QUERIES[signal].format(svc=svc)
        win = values(ds.query_prometheus_range(query, start, end))
        base = values(ds.query_prometheus_range(query, baseline_start, start))
        if not win or not base:
            scores.append(ServiceScore(svc, 0.0, float("nan"), float("nan"), float("nan"),
                                       query, False))
            continue
        mu, sigma = float(np.mean(base)), float(np.std(base))
        z = (float(np.mean(win)) - mu) / (sigma + 1e-9)
        scores.append(ServiceScore(svc, z, float(np.mean(win)), mu, sigma, query, True))
    return sorted(scores, key=lambda s: -s.z)


@dataclass(frozen=True)
class MetricWindow:
    service: str
    signal: str
    baseline: list[float]
    incident: list[float]

    @property
    def baseline_mean(self) -> float:
        return float(np.mean(self.baseline))

    @property
    def incident_mean(self) -> float:
        return float(np.mean(self.incident))

    @property
    def ratio(self) -> float | None:
        return self.incident_mean / self.baseline_mean if self.baseline_mean > 0 else None

    @property
    def composite(self) -> float:
        return max(
            0.0, (self.incident_mean - self.baseline_mean) / (float(np.std(self.baseline)) + 1e-9),
        )

    @property
    def nsigma(self) -> float:
        return max_standardized(self.baseline, self.incident)


def max_standardized(baseline: list[float], incident: list[float]) -> float:
    scale = float(np.std(baseline))
    if scale < 10 * np.finfo(float).eps:
        scale = 1.0
    return (max(incident) - float(np.mean(baseline))) / scale


def metric_windows(
    ds: DataSource, signals: list[str], start: str, end: str,
) -> list[MetricWindow]:
    baseline_start = minus_minutes(start, BASELINE_MINUTES)
    windows = []
    for service in ASTRONOMY_SHOP_SERVICES:
        for signal in signals:
            query = METRIC_QUERIES[signal].format(svc=service)
            base = [v for v in values(ds.query_prometheus_range(query, baseline_start, start))
                    if np.isfinite(v)]
            current = [v for v in values(ds.query_prometheus_range(query, start, end))
                       if np.isfinite(v)]
            if base and current:
                windows.append(MetricWindow(service, signal, base, current))
    return windows
