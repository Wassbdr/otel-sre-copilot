from pathlib import Path
from threading import Thread

import httpx

from src.replay_server import make_server
from src.telemetry_queries import LOKI_QUERIES, METRIC_QUERIES


def test_replay_http_uses_recorded_queries_and_limits_windows() -> None:
    snapshot = Path(__file__).parents[1] / "snapshots/shipping-high_latency-seed42"
    with make_server(snapshot, "127.0.0.1", 0) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}"
            with httpx.Client(base_url=url) as client:
                query = METRIC_QUERIES["request_rate"].format(svc="shipping")
                response = client.post("/api/v1/query_range", data={"query": query})
                assert response.is_success
                points = response.json()["data"]["result"][0]["values"]
                ts = points[0][0]
                clipped = client.get("/api/v1/query_range", params={
                    "query": query, "start": ts, "end": ts,
                })
                assert clipped.json()["data"]["result"][0]["values"] == [points[0]]
                missing = client.get("/api/v1/query_range", params={"query": "never_recorded"})
                assert missing.status_code == 422

                response = client.get("/loki/api/v1/query_range", params={
                    "query": LOKI_QUERIES["error_logs"].format(svc="shipping"), "limit": 1,
                })
                assert response.is_success
                assert all(len(stream["values"]) <= 1
                           for stream in response.json()["data"]["result"])
                probe = client.get("/loki/api/v1/query_range", params={
                    "query": '{job="test_endpoint"}',
                })
                assert probe.json()["data"]["result"] == []
                assert client.post("/v1/chat/completions", json={}).status_code == 404

                traces = client.get("/api/search", params={"q": "{}", "limit": 1}).json()["traces"]
                assert len(traces) == 1
                probe = client.get("/api/search", params={
                    "q": '{ .service.name = "test-endpoint" }',
                })
                assert probe.json()["traces"] == []
                trace = client.get(f"/api/v2/traces/{traces[0]['traceID']}").json()
                assert trace["trace"]["batches"]
                assert client.get("/api/traces/../../metadata").status_code == 404
        finally:
            server.shutdown()
            thread.join(timeout=5)
