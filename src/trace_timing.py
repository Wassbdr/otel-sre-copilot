from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Span:
    span_id: str
    parent: str
    service: str
    name: str
    kind: str
    start: int
    end: int


@dataclass(frozen=True)
class Timing:
    service: str
    operation: str
    kind: str
    exclusive_ms: float
    inclusive_ms: float


def _spans(trace: dict[str, Any]) -> list[Span]:
    result = []
    for batch in trace.get("batches") or trace.get("resourceSpans") or []:
        attrs = batch.get("resource", {}).get("attributes", [])
        service = next(
            (a.get("value", {}).get("stringValue") for a in attrs
             if a.get("key") == "service.name"),
            None,
        )
        if not service:
            continue
        for scope in batch.get("scopeSpans") or batch.get("instrumentationLibrarySpans") or []:
            for span in scope.get("spans", []):
                try:
                    start = int(span["startTimeUnixNano"])
                    end = int(span["endTimeUnixNano"])
                    span_id = span["spanId"]
                except (KeyError, ValueError, TypeError):
                    continue
                if span_id and end > start:
                    result.append(Span(
                        span_id, span.get("parentSpanId", ""), service, span.get("name", ""),
                        str(span.get("kind", "")), start, end,
                    ))
    return result


def _covered_ns(parent: Span, children: list[Span]) -> int:
    intervals = sorted(
        (max(parent.start, child.start), min(parent.end, child.end)) for child in children
    )
    covered = 0
    last_end = parent.start
    for start, end in intervals:
        if end > max(last_end, start):
            covered += end - max(last_end, start)
            last_end = end
    return covered


def exclusive_timings(trace: dict[str, Any]) -> list[Timing]:
    """Use the union of child intervals, not their sum, for overlapping calls."""
    spans = _spans(trace)
    children: dict[str, list[Span]] = defaultdict(list)
    for span in spans:
        if span.parent:
            children[span.parent].append(span)

    timings: list[Timing] = []
    for span in spans:
        duration = span.end - span.start
        direct = children[span.span_id]
        own = duration - _covered_ns(span, direct)
        service = span.service
        if span.kind in {"3", "SPAN_KIND_CLIENT"}:
            remotes = {
                child.service for child in direct
                if child.kind in {"2", "SPAN_KIND_SERVER"} and child.service != span.service
            }
            if len(remotes) != 1:
                continue
            service = next(iter(remotes))
            kind = "client wait outside paired server"
        elif span.kind in {"2", "SPAN_KIND_SERVER"}:
            kind = "server self time"
        else:
            continue
        timings.append(Timing(service, span.name, kind, own / 1e6, duration / 1e6))
    return sorted(timings, key=lambda timing: -timing.exclusive_ms)
