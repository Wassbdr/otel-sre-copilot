"""Serve recorded telemetry through a read-only subset of three HTTP APIs."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import structlog

log = structlog.get_logger()


def _seconds(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return datetime.fromisoformat(value).timestamp()


def _promql_quote_style(query: str) -> str:
    return re.sub(r"((?:!?=~?|!~)\s*)'([^'\"\\]*)'", r'\1"\2"', query)


def _duration_ms(value: str) -> float:
    if value.endswith("ms"):
        return float(value[:-2])
    if value.endswith("s"):
        return float(value[:-1]) * 1000
    return float(value)


class SnapshotHTTP:
    def __init__(self, snapshot: Path) -> None:
        self.snapshot = snapshot
        self.prom = json.loads((snapshot / "prometheus/raw_queries.json").read_text())
        self.loki = json.loads((snapshot / "loki/raw_queries.json").read_text())
        self.traces = json.loads((snapshot / "tempo/trace_summaries.json").read_text())

    def get(
        self, path: str, params: dict[str, list[str]],
    ) -> tuple[HTTPStatus, dict[str, Any]]:
        def param(key: str, default: str = "") -> str:
            return params.get(key, [default])[0]

        query = param("query")
        if path in {"/ready", "/-/ready", "/api/echo"}:
            return HTTPStatus.OK, {"status": "success"}
        if path in {"/api/v1/query_range", "/api/v1/query"}:
            instant = path.endswith("/query")
            kind = "instant" if instant else "range"
            if not query:
                raise ValueError("Specify a captured PromQL query.")
            if instant and query == "up":
                return _result("vector", [])
            query = _promql_quote_style(query)
            entries = [e for e in self.prom if e["query"] == query and e["type"] == kind]
            if not entries:
                return _unsupported("PromQL expression was not recorded for this endpoint.")
            if instant:
                cutoff = _seconds(param("time", "inf"))
                samples = [
                    series for entry in entries for series in entry["result"]
                    if float(series["value"][0]) <= cutoff
                ]
                latest = {json.dumps(s["metric"], sort_keys=True): s for s in sorted(
                    samples, key=lambda series: float(series["value"][0]),
                )}
                return _result("vector", list(latest.values()))
            start = _seconds(param("start", "-inf"))
            end = _seconds(param("end", "inf"))
            grouped: dict[str, tuple[dict[str, str], dict[float, str]]] = {}
            for entry in entries:
                for series in entry["result"]:
                    labels = series["metric"]
                    _, points = grouped.setdefault(json.dumps(labels, sort_keys=True), (labels, {}))
                    points.update((float(t), v) for t, v in series["values"] if start <= t <= end)
            return _result("matrix", [
                {"metric": labels, "values": sorted(points.items())}
                for labels, points in grouped.values() if points
            ])
        if path == "/loki/api/v1/labels":
            labels_seen = {
                name for entry in self.loki for stream in entry["result"]
                for name in stream["stream"]
            }
            return HTTPStatus.OK, {"status": "success", "data": sorted(labels_seen)}
        if path == "/loki/api/v1/query_range":
            if not query:
                raise ValueError("Specify a captured LogQL query.")
            if query == '{job="test_endpoint"}':
                return _result("streams", [])
            entries = [entry for entry in self.loki if entry["logql"] == query]
            if not entries:
                return _unsupported("LogQL expression was not recorded.")
            def nanos(value: str) -> int:
                return int(value) if value.isdecimal() else int(_seconds(value) * 1e9)

            start, end = nanos(param("start", "0")), nanos(param("end", str(2**63 - 1)))
            limit = max(0, min(1000, int(param("limit", "100"))))
            streams = [
                {"stream": stream["stream"], "values": values}
                for entry in entries for stream in entry["result"]
                if (values := sorted(
                    ((t, line) for t, line in stream["values"] if start <= int(t) <= end),
                    key=lambda value: int(value[0]), reverse=param("direction") != "forward",
                )[:limit])
            ]
            return _result("streams", streams)
        if path == "/api/search":
            expression = param("q")
            tags = param("tags")
            service = param("service.name")
            if expression and expression.strip() != "{}":
                match = re.fullmatch(
                    r'\{\s*(?:resource)?\.service\.name\s*=\s*"([^"]+)"\s*\}', expression,
                )
                if not match:
                    return _unsupported("Only a resource.service.name TraceQL filter is supported.")
                service = match[1]
            if tags:
                match = re.fullmatch(r'service\.name="?([^" ]+)"?', tags)
                if not match:
                    return _unsupported("Only the service.name Tempo tag filter is supported.")
                service = match[1]
            start, end = _seconds(param("start", "0")), _seconds(param("end", "inf"))
            minimum = _duration_ms(param("minDuration", "0"))
            maximum = _duration_ms(param("maxDuration", "inf"))
            limit = max(0, min(1000, int(param("limit", "20"))))
            matches = [
                t for t in self.traces if minimum <= int(t.get("durationMs", 0)) <= maximum
                and start <= int(t["startTimeUnixNano"]) / 1e9 <= end
                and (not service or t.get("rootServiceName") == service)
            ]
            return HTTPStatus.OK, {"traces": matches[:limit], "metrics": {}}
        trace_match = re.fullmatch(r"/api/(?:v2/)?traces/([0-9a-fA-F]{16,32})", path)
        if trace_match:
            trace_file = self.snapshot / "tempo/traces" / f"{trace_match[1]}.json"
            if trace_file.is_file():
                document = json.loads(trace_file.read_text())
                return HTTPStatus.OK, {"trace": document} if "/v2/" in path else document
        return HTTPStatus.NOT_FOUND, {"status": "error", "error": "Not recorded or unsupported."}


def _result(kind: str, entries: list[Any]) -> tuple[HTTPStatus, dict[str, Any]]:
    return HTTPStatus.OK, {"status": "success", "data": {"resultType": kind, "result": entries}}


def _unsupported(message: str) -> tuple[HTTPStatus, dict[str, Any]]:
    return HTTPStatus.UNPROCESSABLE_ENTITY, {
        "status": "error", "errorType": "not_recorded", "error": message,
    }


def make_server(
    snapshot: Path, host: str, port: int, *,
    observe: Callable[[str, dict[str, list[str]], dict[str, Any]], None] | None = None,
    complete: Callable[[bytes, str], tuple[int, bytes]] | None = None,
) -> ThreadingHTTPServer:
    replay = SnapshotHTTP(snapshot)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self._respond({})

        def do_POST(self) -> None:  # noqa: N802
            length = self.headers.get("Content-Length", "0")
            if complete is not None and self.path == "/v1/chat/completions":
                if not length.isdecimal() or not 0 < int(length) <= 2**20:
                    self.send_error(HTTPStatus.BAD_REQUEST)
                    return
                status, body = complete(
                    self.rfile.read(int(length)), self.headers.get("Authorization", ""),
                )
                self._write_json(status, body)
                return
            if not length.isdecimal() or int(length) > 65536:
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            self._respond(parse_qs(self.rfile.read(int(length)).decode(errors="replace")))

        def _respond(self, form: dict[str, list[str]]) -> None:
            url = urlsplit(self.path)
            params = {**parse_qs(url.query), **form}
            try:
                status, payload = replay.get(url.path, params)
            except (ValueError, OverflowError) as error:
                status, payload = HTTPStatus.BAD_REQUEST, {"status": "error", "error": str(error)}
            if observe is not None and status == HTTPStatus.OK:
                observe(url.path, params, payload)
            self._write_json(status, json.dumps(payload).encode())

        def _write_json(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            log.debug("replay_request", message=format % args)

    return ThreadingHTTPServer((host, port), Handler)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    try:
        server = make_server(args.snapshot, "127.0.0.1", args.port)
    except (OSError, ValueError) as error:
        parser.error(f"Cannot start snapshot replay: {error}")
    with server:
        log.info("replay_listening", port=server.server_port)
        with suppress(KeyboardInterrupt):
            server.serve_forever()


if __name__ == "__main__":
    main()
