"""Per-service anomaly scores over the canonical signals.

Same statistic as the composite Z-score baseline (mean of the incident window against the
30 minutes before it), exposed to the agent as a tool so it can sweep 15 services in one call
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
