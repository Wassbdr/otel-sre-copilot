"""Capture a telemetry snapshot for a given time window.

Queries Prometheus, Tempo, Loki, and K8s events for all Astronomy Shop services
and writes the results to a snapshot directory in the format expected by ReplayDataSource.

Usage:
    python scripts/snapshot_telemetry.py \\
        --output-dir snapshots/my-scenario \\
        --start 2024-01-15T14:00:00Z \\
        --end 2024-01-15T14:10:00Z \\
        --namespace otel-demo
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import structlog
from dotenv import load_dotenv

load_dotenv()

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.datasources.live import LiveDataSource, ASTRONOMY_SHOP_SERVICES

log = structlog.get_logger()

# PromQL queries snapshotted for each service (parametrized by service name label)
_METRIC_QUERIES = [
    # Error rate (HTTP 5xx / total)
    'sum(rate(http_server_request_duration_seconds_count{{http_response_status_code=~"5..",service_name="{svc}"}}[2m])) '
    '/ sum(rate(http_server_request_duration_seconds_count{{service_name="{svc}"}}[2m]))',
    # Request rate
    'sum(rate(http_server_request_duration_seconds_count{{service_name="{svc}"}}[2m]))',
    # P99 latency
    'histogram_quantile(0.99, sum(rate(http_server_request_duration_seconds_bucket{{service_name="{svc}"}}[2m])) by (le))',
    # CPU usage
    'sum(rate(container_cpu_usage_seconds_total{{pod=~"{svc}.*"}}[2m]))',
    # Memory usage
    'sum(container_memory_working_set_bytes{{pod=~"{svc}.*"}})',
    # Pod restarts
    'sum(kube_pod_container_status_restarts_total{{pod=~"{svc}.*"}})',
]

_LOKI_QUERIES = [
    # Error logs
    '{{service_name="{svc}"}} |= "error" | json',
    # Warning logs
    '{{service_name="{svc}"}} |= "warn" | json',
]


def snapshot(
    output_dir: Path,
    start: str,
    end: str,
    namespace: str,
    baseline_start: str | None = None,
) -> None:
    """Capture all telemetry signals into output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "prometheus").mkdir(exist_ok=True)
    (output_dir / "tempo").mkdir(exist_ok=True)
    (output_dir / "tempo" / "traces").mkdir(exist_ok=True)
    (output_dir / "loki").mkdir(exist_ok=True)
    (output_dir / "k8s").mkdir(exist_ok=True)

    ds = LiveDataSource()
    prom_results: list[dict[str, object]] = []
    loki_results: list[dict[str, object]] = []
    trace_summaries: list[dict[str, object]] = []

    # Snapshot a baseline window too (30min before start) for Z-score baselines
    actual_baseline_start = baseline_start or _subtract_minutes(start, 30)

    log.info("snapshotting_metrics", services=len(ASTRONOMY_SHOP_SERVICES))
    for svc in ASTRONOMY_SHOP_SERVICES:
        for tpl in _METRIC_QUERIES:
            query = tpl.format(svc=svc)
            # Fault window
            result = ds.query_prometheus_range(query, start, end)
            prom_results.append({"type": "range", "query": query, "start": start,
                                  "end": end, "step": "30s", "result": result})
            # Baseline window
            bl_result = ds.query_prometheus_range(query, actual_baseline_start, start)
            prom_results.append({"type": "range", "query": query,
                                  "start": actual_baseline_start, "end": start,
                                  "step": "30s", "result": bl_result,
                                  "is_baseline": True})

    log.info("snapshotting_traces", services=len(ASTRONOMY_SHOP_SERVICES))
    for svc in ASTRONOMY_SHOP_SERVICES:
        traces = ds.search_traces(svc, start, end, error_only=True, limit=20)
        trace_summaries.extend(traces)
        # Also fetch a few slow traces
        slow = ds.search_traces(svc, start, end, min_duration_ms=500, limit=5)
        trace_summaries.extend(t for t in slow if t not in trace_summaries)

    # Deduplicate traces by traceID and fetch full span trees for top 10
    seen: set[str] = set()
    unique_traces: list[dict[str, object]] = []
    for t in trace_summaries:
        tid = str(t.get("traceID", ""))
        if tid and tid not in seen:
            seen.add(tid)
            unique_traces.append(t)
    trace_summaries = unique_traces[:50]

    log.info("fetching_full_traces", count=min(10, len(trace_summaries)))
    for t in trace_summaries[:10]:
        tid = str(t.get("traceID", ""))
        if tid:
            try:
                full = ds.get_trace(tid)
                with open(output_dir / "tempo" / "traces" / f"{tid}.json", "w") as f:
                    json.dump(full, f, indent=2)
            except Exception as e:
                log.warning("trace_fetch_failed", trace_id=tid, error=str(e))

    log.info("snapshotting_logs", services=len(ASTRONOMY_SHOP_SERVICES))
    for svc in ASTRONOMY_SHOP_SERVICES:
        for tpl in _LOKI_QUERIES:
            query = tpl.format(svc=svc)
            result = ds.query_loki(query, start, end, limit=100)
            loki_results.append({"logql": query, "start": start, "end": end, "result": result})

    log.info("snapshotting_k8s_events", namespace=namespace)
    events = ds.get_pod_events(namespace)
    topology = ds.get_service_topology(namespace)

    # Write all files
    with open(output_dir / "prometheus" / "raw_queries.json", "w") as f:
        json.dump(prom_results, f, indent=2)
    with open(output_dir / "tempo" / "trace_summaries.json", "w") as f:
        json.dump(trace_summaries, f, indent=2)
    with open(output_dir / "loki" / "raw_queries.json", "w") as f:
        json.dump(loki_results, f, indent=2)
    with open(output_dir / "k8s" / "events.json", "w") as f:
        json.dump(events, f, indent=2)

    metadata = {
        "snapshot_ts": datetime.now(timezone.utc).isoformat(),
        "window_start": start,
        "window_end": end,
        "namespace": namespace,
        "services_snapshotted": ASTRONOMY_SHOP_SERVICES,
        "service_topology": topology,
    }
    with open(output_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    ds.close()
    log.info("snapshot_complete", output_dir=str(output_dir))


def _subtract_minutes(iso_ts: str, minutes: int) -> str:
    from datetime import timedelta
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return (dt - timedelta(minutes=minutes)).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description="Snapshot telemetry for a time window")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--start", required=True, help="ISO-8601 UTC start")
    parser.add_argument("--end", required=True, help="ISO-8601 UTC end")
    parser.add_argument("--namespace", default=os.getenv("K8S_NAMESPACE", "otel-demo"))
    parser.add_argument("--baseline-start", default=None,
                        help="Start of baseline window (default: start - 30min)")
    args = parser.parse_args()

    snapshot(
        output_dir=args.output_dir,
        start=args.start,
        end=args.end,
        namespace=args.namespace,
        baseline_start=args.baseline_start,
    )


if __name__ == "__main__":
    main()
