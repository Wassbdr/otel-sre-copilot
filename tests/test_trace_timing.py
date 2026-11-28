from typing import Any

from src.trace_timing import exclusive_timings


def test_exclusive_time_clips_and_counts_overlapping_children_once() -> None:
    def span(
        span_id: str, start: int, end: int, kind: int, parent: str = "",
    ) -> dict[str, Any]:
        return {
            "spanId": span_id, "name": span_id, "parentSpanId": parent, "kind": kind,
            "startTimeUnixNano": str(start * 1_000_000), "endTimeUnixNano": str(end * 1_000_000),
        }

    def resource(service: str, *spans: dict[str, Any]) -> dict[str, Any]:
        return {
            "resource": {"attributes": [
                {"key": "service.name", "value": {"stringValue": service}},
            ]},
            "scopeSpans": [{"spans": spans}],
        }

    result = exclusive_timings({"batches": [
        resource("frontend", span("entry", 5, 100, 2), span("call", 0, 80, 3, "entry"),
                 span("other", 50, 90, 1, "entry")),
        resource("shipping", span("remote", 10, 70, 2, "call")),
    ]})
    assert [(t.service, t.exclusive_ms) for t in result] == [
        ("shipping", 60), ("shipping", 20), ("frontend", 10),
    ]
