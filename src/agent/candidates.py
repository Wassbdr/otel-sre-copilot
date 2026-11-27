from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

import structlog

from src.agent.schemas import EvidenceItem, InvestigationReport, RootCauseHypothesis
from src.anomaly import BASELINE_MINUTES, MetricWindow, metric_windows, signal_query
from src.datasources.live import ASTRONOMY_SHOP_SERVICES
from src.datasources.replay import ReplayDataSource
from src.telemetry_queries import FINGERPRINT_QUERIES, LOKI_QUERIES, SIGNAL_TO_FAULT
from src.trace_timing import Timing, exclusive_timings

if TYPE_CHECKING:
    from src.datasources.protocol import DataSource

log = structlog.get_logger()
Fault = Literal["pod_crash", "high_latency", "cpu_stress", "memory_stress",
                "http_abort", "dependency_failure"]
_TIMEOUT = re.compile(r"timed? out|timeout|deadline exceeded|connection reset", re.I)


def _metric(window: MetricWindow) -> EvidenceItem:
    return EvidenceItem(
        signal_type="metric", query_or_id=f"metric:{window.signal}:{window.service}",
        observed_value=f"mean={window.incident_mean:.3g}, peak={max(window.incident):.3g}",
        expected_baseline=f"mean={window.baseline_mean:.3g}, peak={max(window.baseline):.3g}",
    )


def _in_window(value: object, start: datetime, end: datetime) -> bool:
    try:
        timestamp = datetime.fromisoformat(str(value))
        return start <= timestamp <= end
    except (ValueError, TypeError):
        return False


def _trace_times(
    ds: DataSource, start: datetime, end: datetime,
) -> dict[tuple[str, str, str], tuple[Timing, str]]:
    groups: dict[tuple[str, str, str], tuple[Timing, str]] = {}
    try:
        traces = ds.search_traces("", start.isoformat(), end.isoformat(), limit=20)
    except Exception as error:
        log.info("candidate_traces_unavailable", error=type(error).__name__)
        return groups
    for trace in traces:
        trace_id = str(trace.get("traceID", ""))
        try:
            seconds = int(str(trace["startTimeUnixNano"])) / 1e9
            if not trace_id or not start.timestamp() <= seconds < end.timestamp():
                continue
            if isinstance(ds, ReplayDataSource) and not ds.has_trace(trace_id):
                continue
            timings = exclusive_timings(ds.get_trace(trace_id))
        except (ValueError, TypeError, LookupError, OSError):
            continue
        except Exception as error:
            log.info("candidate_trace_unavailable", error=type(error).__name__)
            continue
        for measure in timings:
            key = (measure.service, measure.operation, measure.kind)
            if key not in groups or measure.exclusive_ms > groups[key][0].exclusive_ms:
                groups[key] = (measure, trace_id)
    return groups


def _above(window: MetricWindow | None, ratio: float, absolute: float) -> bool:
    return bool(window and window.incident_mean >= ratio * window.baseline_mean
                and window.incident_mean - window.baseline_mean >= absolute)


def rank_candidates(
    ds: DataSource, start: str, end: str, namespace: str, services: list[str] | None,
) -> list[RootCauseHypothesis]:
    begin, finish = datetime.fromisoformat(start), datetime.fromisoformat(end)
    monitored = services or ASTRONOMY_SHOP_SERVICES
    windows = []
    for signal in (*SIGNAL_TO_FAULT, "request_rate", *FINGERPRINT_QUERIES):
        available = [svc for svc in monitored if not isinstance(ds, ReplayDataSource)
                     or ds.has_prometheus_range(signal_query(signal, svc, namespace))]
        if available:
            try:
                windows.extend(metric_windows(
                    ds, [signal], start, end, services=available, namespace=namespace,
                ))
            except Exception as error:
                log.info("candidate_metrics_unavailable", signal=signal, error=type(error).__name__)
    by_service: dict[str, dict[str, MetricWindow]] = defaultdict(dict)
    for window in windows:
        by_service[window.service][window.signal] = window

    event_map: dict[str, list[EvidenceItem]] = defaultdict(list)
    try:
        events = ds.get_pod_events(namespace, since_seconds=max(
            600, int((datetime.now(begin.tzinfo) - begin).total_seconds()),
        ))
    except Exception as error:
        log.info("candidate_events_unavailable", error=type(error).__name__)
        events = []
    for event in events:
        pod, reason = str(event.get("involved_object_name", "")), str(event.get("reason", ""))
        message = str(event.get("message", ""))
        if not _in_window(event.get("last_time") or event.get("first_time"), begin, finish):
            continue
        if not re.search(r"\bOOMKilled\b", f"{reason} {message}", re.I):
            continue
        service = max((svc for svc in monitored if pod.startswith(svc + "-")),
                      key=len, default="")
        if service:
            event_map[service].append(EvidenceItem(
                signal_type="k8s_event", query_or_id=f"k8s_event:{pod}:OOMKilled",
                observed_value=f"{reason}: {message[:100]}",
            ))

    current = _trace_times(ds, begin, finish)
    baseline = (
        _trace_times(ds, begin - timedelta(minutes=BASELINE_MINUTES), begin) if current else {}
    )
    ranked: dict[tuple[str, Fault], tuple[float, str, list[EvidenceItem]]] = {}

    def offer(service: str, fault: Fault, score: float, why: str, *items: EvidenceItem) -> None:
        key = (service, fault)
        if key not in ranked or score > ranked[key][0]:
            ranked[key] = (score, why, list(items))

    drops: dict[str, float] = {}
    for svc, series in by_service.items():
        restarts = series.get("pod_restarts")
        lost_ready = series.get("pod_not_ready")
        memory = series.get("memory_usage")
        limit = series.get("memory_limit_ratio")
        cpu = series.get("cpu_usage")
        throttle = series.get("cpu_throttle_ratio")
        has_restart = restarts is not None and max(restarts.incident) >= max(restarts.baseline) + 1
        memory_grew = _above(memory, 1.1, 8 * 1024**2)
        if has_restart and restarts:
            pressure = event_map[svc][:1]
            if limit and max(limit.incident) >= 0.9:
                pressure.append(_metric(limit))
            if pressure:
                offer(svc, "memory_stress", 6, "Restart coincided with memory pressure.",
                      _metric(restarts), *pressure)
            else:
                offer(svc, "pod_crash", 4, "Restart increased without recorded OOM evidence.",
                      _metric(restarts))
        elif lost_ready and _above(lost_ready, 2, 0.2):
            offer(svc, "pod_crash", 4, "Pods spent more time not ready.", _metric(lost_ready))
        if memory and memory_grew and memory.nsigma >= 3:
            items = [_metric(memory)]
            if restarts and has_restart:
                items.append(_metric(restarts))
            offer(svc, "memory_stress", 3 + min((memory.ratio or 1) - 1, 0.9),
                  "Working set rose above its baseline; an OOM kill is not established.", *items)
        if throttle and _above(throttle, 2, 0.15):
            offer(svc, "cpu_stress", 5, "CPU throttling increased.", _metric(throttle))
        if cpu and _above(cpu, 2, 0.05) and cpu.nsigma >= 3:
            offer(svc, "cpu_stress", 3 + min(cpu.incident_mean - cpu.baseline_mean, 0.9),
                  "CPU consumption increased against baseline.", _metric(cpu))
        errors = series.get("error_rate")
        if errors and _above(errors, 2, 0.01):
            offer(svc, "http_abort", 2 + min(errors.incident_mean, 0.9),
                  "Inbound server errors increased.", _metric(errors))
        packets = series.get("network_drop_rate")
        if packets and _above(packets, 2, 0.05):
            offer(svc, "http_abort", 5, "Pod network packet drops increased.", _metric(packets))
        requests = series.get("request_rate")
        if requests and requests.baseline_mean >= 0.005 and (requests.ratio or 0) <= 0.65:
            drops[svc] = 1 - (requests.ratio or 0)

    if drops:
        try:
            topology = ds.get_service_topology(namespace)
        except Exception as error:
            log.info("candidate_topology_unavailable", error=type(error).__name__)
            topology = {}
        for svc, drop in drops.items():
            downstream = any(drop <= drops.get(dep, 0) + 0.1 for dep in topology.get(svc, []))
            offer(svc, "http_abort", 2 + drop - 0.5 * downstream,
                  "Inbound request rate declined; correlated drops can reflect propagation.",
                  _metric(by_service[svc]["request_rate"]))
            query = LOKI_QUERIES["error_logs"].format(svc=svc)
            try:
                logs = ds.query_loki(query, start, end, limit=10)
            except Exception as error:
                log.info("candidate_logs_unavailable", error=type(error).__name__)
                continue
            for stream in logs:
                values = stream.get("values")
                if not isinstance(values, list):
                    continue
                line = next((str(row[1]) for row in values if _TIMEOUT.search(str(row[1]))), "")
                if line:
                    match = _TIMEOUT.search(line)
                    offer(svc, "dependency_failure", 2.5 + drop, "Request loss and timeout logs.",
                          _metric(by_service[svc]["request_rate"]),
                          EvidenceItem(signal_type="log", query_or_id=query,
                                       observed_value=match[0] if match else line[:100]))
                    break

    for key, (timing, trace_id) in current.items():
        svc = timing.service
        if svc not in monitored:
            continue
        latency = by_service.get(svc, {}).get("p99_latency_ms")
        prior = baseline.get(key)
        own_ms = timing.exclusive_ms
        trace_evidence = EvidenceItem(
            signal_type="trace", query_or_id=f"trace:{trace_id}",
            observed_value=f"{timing.kind}, {timing.operation}: {own_ms:.1f} ms",
        )
        if prior and own_ms >= max(3 * prior[0].exclusive_ms, prior[0].exclusive_ms + 20):
            trace_evidence.expected_baseline = f"{prior[0].exclusive_ms:.1f} ms; trace:{prior[1]}"
            offer(svc, "high_latency", 5, f"{timing.kind.capitalize()} increased.",
                  trace_evidence, EvidenceItem(
                      signal_type="trace", query_or_id=f"trace:{prior[1]}",
                      observed_value=f"Baseline {timing.kind}: {prior[0].exclusive_ms:.1f} ms",
                  ))
        elif not prior and latency and _above(latency, 2, 20) and own_ms >= 20:
            offer(svc, "high_latency", 3 + min(own_ms / 1000, 0.9),
                  f"Server p99 rose and sampled {timing.kind} was high.",
                  _metric(latency), trace_evidence)

    return [
        RootCauseHypothesis(rank=i, service=service, fault_type=fault, description=why,
                            confidence=0.5, evidence=evidence)
        for i, ((service, fault), (_, why, evidence)) in enumerate(
            sorted(ranked.items(), key=lambda item: (-item[1][0], *item[0]))[:8], 1,
        )
    ]


def combine_rankings(
    report: InvestigationReport, prior: list[RootCauseHypothesis],
    observed: set[str],
) -> InvestigationReport:
    candidates = {(h.service, h.fault_type): h for h in prior}
    selected: list[RootCauseHypothesis] = []
    seen: set[tuple[str, str]] = set()
    added = False

    def verified(hypothesis: RootCauseHypothesis) -> bool:
        return bool(hypothesis.evidence) and all(
            f"{item.signal_type}|{item.query_or_id}" in observed
            and (not item.query_or_id.startswith("metric:") or
                 item.query_or_id.rsplit(":", 1)[-1] == hypothesis.service)
            for item in hypothesis.evidence
        )

    for hypothesis in sorted(report.root_causes, key=lambda item: item.rank):
        key = (hypothesis.service, hypothesis.fault_type)
        if key in seen or not verified(hypothesis):
            continue
        candidate = candidates.get(key)
        if candidate is None and (added or hypothesis.fault_type == "unknown"):
            continue
        if candidate is not None and not verified(candidate):
            continue
        selected.append(candidate or hypothesis)
        seen.add(key)
        added |= candidate is None

    for hypothesis in prior:
        if len(selected) >= 3:
            break
        key = (hypothesis.service, hypothesis.fault_type)
        if key not in seen and verified(hypothesis):
            selected.append(hypothesis)
            seen.add(key)

    anchor = next((hypothesis for hypothesis in prior if verified(hypothesis)), None)
    if anchor and _direct_fault_signal(anchor):
        key = (anchor.service, anchor.fault_type)
        position = next((i for i, h in enumerate(selected)
                         if (h.service, h.fault_type) == key), len(selected))
        if position < len(selected):
            selected.pop(position)
        while position and not _direct_fault_signal(selected[position - 1]):
            position -= 1
        selected.insert(min(position, 2), anchor)

    ranked = [h.model_copy(update={"rank": i}) for i, h in enumerate(selected[:3], 1)]
    unchanged = bool(ranked and report.root_causes
                     and ranked[0].service == report.root_causes[0].service
                     and ranked[0].fault_type == report.root_causes[0].fault_type)
    return report.model_copy(update={
        "root_causes": ranked,
        "fault_type_classification": ranked[0].fault_type if ranked else "unknown",
        "remediation_steps": report.remediation_steps if unchanged else [],
    })


def _direct_fault_signal(hypothesis: RootCauseHypothesis) -> bool:
    citations = [item.query_or_id for item in hypothesis.evidence]
    if hypothesis.fault_type == "memory_stress" and all(
        any(citation.startswith(prefix) for citation in citations)
        for prefix in ("metric:pod_restarts:", "metric:memory_usage:")
    ):
        return True
    prefixes = {
        "pod_crash": ("metric:pod_restarts:", "metric:pod_not_ready:"),
        "memory_stress": ("k8s_event:", "metric:memory_limit_ratio:"),
        "cpu_stress": ("metric:cpu_throttle_ratio:",),
        "high_latency": ("trace:",),
        "http_abort": ("metric:network_drop_rate:",),
    }.get(hypothesis.fault_type, ())
    return any(citation.startswith(prefixes) for citation in citations)
