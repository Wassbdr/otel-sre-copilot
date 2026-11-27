"""Agent tool functions — thin wrappers around DataSource with Layer 1+2 compression.

These functions are bound to the LLM via LangChain's bind_tools().
They never import HTTP libraries directly — all I/O goes through a DataSource.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog
from langchain_core.tools import BaseTool, tool

from src.agent.context_manager import (
    ContextBudget,
    compress_loki,
    compress_prometheus_range,
    compress_traces,
)
from src.anomaly import MetricWindow, metric_windows
from src.telemetry_queries import SIGNAL_TO_FAULT
from src.trace_timing import Timing, exclusive_timings

if TYPE_CHECKING:
    from src.datasources.protocol import DataSource

log = structlog.get_logger()

def make_tools(
    ds: DataSource, budget: ContextBudget, *, improved: bool = False, prior: bool = False,
) -> list[BaseTool]:
    """Return LangChain tool functions bound to a specific DataSource and budget."""

    @tool
    def query_prometheus_range(
        query: str,
        start: str,
        end: str,
        step: str = "30s",
    ) -> str:
        """Execute a PromQL range query against Prometheus.

        Returns a compressed statistical summary (mean, p50, p95, p99, max, anomaly window).
        Use this to detect anomalies in metrics like error_rate, p99_latency, cpu_usage.

        Args:
            query: PromQL expression. Use service_name label to filter by service.
            start: ISO-8601 UTC start time.
            end: ISO-8601 UTC end time.
            step: Resolution step (default: 30s). Use 30s for incident windows.
        """
        try:
            results = ds.query_prometheus_range(query, start, end, step)
            compressed = compress_prometheus_range(results, query)
            return budget.consume(compressed)
        except Exception as e:
            log.warning("tool_error", tool="query_prometheus_range", error=str(e))
            return f"[ERROR: {e}]"

    @tool
    def query_prometheus_instant(query: str, time: str) -> str:
        """Execute a PromQL instant query for a single point in time.

        Args:
            query: PromQL expression.
            time: ISO-8601 UTC timestamp.
        """
        try:
            result = ds.query_prometheus_instant(query, time)
            if not result:
                return "[no data]"
            return budget.consume(str(result)[:500])
        except Exception as e:
            log.warning("tool_error", tool="query_prometheus_instant", error=str(e))
            return f"[ERROR: {e}]"

    @tool
    def search_traces(
        service_name: str,
        start: str,
        end: str,
        min_duration_ms: int = 0,
        error_only: bool = False,
        limit: int = 20,
    ) -> str:
        """Search Tempo for distributed traces matching criteria.

        Returns a summary: total count, error count, p95 duration, and top-3 trace IDs.
        Use error_only=True when investigating error rate anomalies.
        Use min_duration_ms when investigating latency anomalies.

        Args:
            service_name: Exact service name (e.g. 'checkoutservice').
            start: ISO-8601 UTC start.
            end: ISO-8601 UTC end.
            min_duration_ms: Only include traces longer than this (0 = all).
            error_only: Only include traces with errors.
            limit: Max traces to fetch (default 20).
        """
        try:
            traces = ds.search_traces(
                service_name, start, end,
                min_duration_ms=min_duration_ms if min_duration_ms > 0 else None,
                error_only=error_only,
                limit=limit,
            )
            compressed = compress_traces(traces, full_ids=improved)
            return budget.consume(compressed)
        except Exception as e:
            log.warning("tool_error", tool="search_traces", error=str(e))
            return f"[ERROR: {e}]"

    @tool
    def get_trace(trace_id: str) -> str:
        """Fetch a full trace by ID to inspect individual span errors and timings.

        Use this on a specific trace_id you found from search_traces.

        Args:
            trace_id: Exact trace ID returned by search_traces.
        """
        try:
            trace = ds.get_trace(trace_id)
            if not trace:
                return f"[trace {trace_id} not found]"
            if improved:
                timings = exclusive_timings(trace)
                return budget.consume(_timing_lines([(trace_id, t) for t in timings[:6]]))
            return budget.consume(str(trace)[:1000])
        except Exception as e:
            log.warning("tool_error", tool="get_trace", error=str(e))
            return f"[ERROR: {e}]"

    @tool
    def query_loki(
        logql: str,
        start: str,
        end: str,
        limit: int = 100,
    ) -> str:
        """Execute a LogQL query against Loki to retrieve logs.

        Returns deduplicated error patterns and log level counts.
        Use label selectors like {service_name="checkoutservice"} and filter with |= "error".

        Args:
            logql: LogQL query string.
            start: ISO-8601 UTC start.
            end: ISO-8601 UTC end.
            limit: Max log lines (default 100).
        """
        try:
            results = ds.query_loki(logql, start, end, limit=limit)
            compressed = compress_loki(results, compact=improved)
            return budget.consume(compressed)
        except Exception as e:
            log.warning("tool_error", tool="query_loki", error=str(e))
            return f"[ERROR: {e}]"

    @tool
    def get_pod_events(
        namespace: str,
        pod_name_prefix: str = "",
        since_seconds: int = 600,
    ) -> str:
        """Fetch Kubernetes pod events (OOMKilled, BackOff, FailedMount, etc.).

        Useful to detect pod crash loops and resource pressure.

        Args:
            namespace: Kubernetes namespace (e.g. 'otel-demo').
            pod_name_prefix: Filter to pods starting with this string.
            since_seconds: Look back this many seconds (default 600 = 10 min).
        """
        try:
            events = ds.get_pod_events(namespace, pod_name_prefix or None, since_seconds)
            if not events:
                return "[no K8s events found]"
            lines = [
                f"  {e.get('reason')}: {str(e.get('message', ''))[:120]} (count={e.get('count')})"
                for e in events[:10]
            ]
            return budget.consume("K8s events:\n" + "\n".join(lines))
        except Exception as e:
            log.warning("tool_error", tool="get_pod_events", error=str(e))
            return f"[ERROR: {e}]"

    @tool
    def get_service_topology(namespace: str) -> str:
        """Return the service dependency graph for the given namespace.

        Use this first to understand which services call which, so you can
        identify upstream vs downstream failure propagation.

        Args:
            namespace: Kubernetes namespace.
        """
        try:
            topo = ds.get_service_topology(namespace)
            lines = [
                f"  {svc} → {', '.join(deps) or '(leaf)'}" for svc, deps in sorted(topo.items())
            ]
            return budget.consume("Service topology:\n" + "\n".join(lines))
        except Exception as e:
            log.warning("tool_error", tool="get_service_topology", error=str(e))
            return f"[ERROR: {e}]"

    @tool
    def rank_services_by_signal(signal: str, start: str, end: str) -> str:
        """Rank ALL services by how anomalous one signal is in the window (Z-score).

        Compares the window mean of the signal with the minutes before `start`, for every
        service at once. Use it first to find suspects, then confirm with traces, logs and
        pod events. Cite the PromQL printed next to a service as metric evidence.

        Args:
            signal: one of error_rate, request_rate, p99_latency_ms, cpu_usage,
                memory_usage, pod_restarts.
            start: ISO-8601 UTC start of the incident window.
            end: ISO-8601 UTC end of the incident window.
        """
        from src.anomaly import rank_services

        try:
            scores = rank_services(ds, signal, start, end)
            lines = [f"{signal}: window mean vs pre-incident baseline, most anomalous first"]
            displayed = [sc for sc in scores if sc.has_data][:5] if improved else scores
            for sc in displayed:
                if not sc.has_data:
                    lines.append(f"  {sc.service:<16} no data")
                    continue
                z = f"{sc.z:+8.2f}" if abs(sc.z) < 1000 else (
                    "   >1000" if sc.z > 0 else "  <-1000")
                lines.append(
                    f"  {sc.service:<16} z={z}  window={sc.window_mean:.4g}  "
                    f"baseline={sc.baseline_mean:.4g}±{sc.baseline_std:.2g}  "
                    + (f"citation: metric:{signal}:{sc.service}" if improved else
                       f"promql: {sc.query}")
                )
            return budget.consume("\n".join(lines))
        except Exception as e:
            log.warning("tool_error", tool="rank_services_by_signal", error=str(e))
            return f"[ERROR: {e}]"

    @tool
    def rank_incident_anomalies(start: str, end: str) -> str:
        """Compare composite z-score and N-Sigma rankings against pre-incident metrics."""
        windows = metric_windows(ds, list(SIGNAL_TO_FAULT), start, end)
        composite = _rank_windows(windows, lambda w: w.composite)
        nsigma = _rank_windows(windows, lambda w: w.nsigma)
        sections = [
            heading + ":\n" + "\n".join(_metric_line(w, score) for w, score in ranking)
            for heading, ranking in (("composite", composite), ("n-sigma", nsigma))
        ]
        candidates = list(dict.fromkeys(w.service for w, _ in composite[:2] + nsigma[:2]))[:3]
        sections.append("Candidate signals (before and during):\n" + "\n".join(
            f"metric:{w.signal}:{w.service} {w.baseline_mean:.3g} -> {w.incident_mean:.3g}"
            for service in candidates for w in windows if w.service == service
        ))
        latency = [w for w in windows if w.signal == "p99_latency_ms" and w.ratio is not None]
        latency.sort(key=lambda w: -(w.ratio or 0))
        sections.append("p99 ratio, caller spans include downstream time:\n" + "\n".join(
            _metric_line(w, w.ratio or 0) for w in latency[:4]
        ))
        return budget.consume("\n".join(sections))

    @tool
    def rank_request_rate_drops(start: str, end: str) -> str:
        """Compare incoming request rates against baseline and rank decreases, not error spikes."""
        windows = metric_windows(ds, ["request_rate"], start, end)
        drops = [w for w in windows if w.baseline_mean > 0 and w.incident_mean < w.baseline_mean]
        drops.sort(key=lambda w: w.incident_mean / w.baseline_mean)
        lines = [_metric_line(w, 1 - (w.ratio or 0)) for w in drops[:6]]
        return budget.consume("Request-rate decreases (score is fraction lost):\n" + (
            "\n".join(lines) or "none among services with baseline traffic"
        ))

    @tool
    def summarize_trace_latency(start: str, end: str) -> str:
        """Summarize server self time and matched remote waits across sampled slow traces."""
        sample = ds.search_traces("", start, end, min_duration_ms=200, limit=8)
        per_kind: dict[str, dict[str, tuple[str, Timing]]] = {}
        for summary in sample:
            trace_id = str(summary.get("traceID", ""))
            if not trace_id:
                continue
            try:
                trace = ds.get_trace(trace_id)
            except Exception:
                continue
            for timing in exclusive_timings(trace):
                by_service = per_kind.setdefault(timing.kind, {})
                current = by_service.get(timing.service)
                if current is None or current[1].exclusive_ms < timing.exclusive_ms:
                    by_service[timing.service] = (trace_id, timing)
        lines = [
            line
            for group in per_kind.values()
            for line in sorted(group.values(), key=lambda row: -row[1].exclusive_ms)[:3]
        ]
        return budget.consume(_timing_lines(lines))

    tools = [
        rank_services_by_signal,
        query_prometheus_range,
        query_prometheus_instant,
        search_traces,
        get_trace,
        query_loki,
        get_pod_events,
        get_service_topology,
    ]
    if improved:
        tools.extend([rank_request_rate_drops, summarize_trace_latency])
    if prior:
        tools.append(rank_incident_anomalies)
    return tools


def _metric_line(window: MetricWindow, score: float) -> str:
    return (
        f"metric:{window.signal}:{window.service} score={score:.3g} "
        f"before={window.baseline_mean:.3g} during={window.incident_mean:.3g}"
    )


def _rank_windows(
    windows: list[MetricWindow], score: Callable[[MetricWindow], float],
) -> list[tuple[MetricWindow, float]]:
    top: list[tuple[MetricWindow, float]] = []
    seen: set[str] = set()
    for window, value in sorted(((w, score(w)) for w in windows), key=lambda row: -row[1]):
        if window.service not in seen:
            top.append((window, value))
            seen.add(window.service)
        if len(top) == 5:
            break
    return top


def _timing_lines(timings: list[tuple[str, Timing]]) -> str:
    if not timings:
        return "No sampled span timing available."
    return "\n".join(
        f"trace:{trace_id} {timing.service} {timing.kind} "
        f"exclusive={timing.exclusive_ms:.0f}ms total={timing.inclusive_ms:.0f}ms "
        f"operation={json.dumps(timing.operation[:70])}"
        for trace_id, timing in timings
    )
