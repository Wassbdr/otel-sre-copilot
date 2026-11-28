# Investigate your telemetry

Install Python 3.12 or 3.13 and run `python -m pip install -e .`. Set
`NIM_API_KEY` or set `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL` for an
OpenAI-compatible model that supports tool calls and JSON output. Use
`LLM_PROVIDER=fake` only for a scripted smoke test. It does not diagnose incidents.

## Live cluster

Forward your cluster's telemetry services to local ports or use reachable
service URLs. Set the Kubernetes context with `KUBE_CONTEXT` if the active
context is not the one you want. The identity needs permission to list events
in the incident namespace; missing event access does not stop metric queries.

```bash
export PROMETHEUS_URL=http://localhost:9090
export LOKI_URL=http://localhost:3100
export TEMPO_URL=http://localhost:3200
copilot investigate --live --namespace storefront --service checkout --service payments \
  --start 2026-01-15T14:00:00Z --end 2026-01-15T14:10:00Z --output report.json
```

Replace the example timestamps with the incident window. Allow at least
30 minutes of metrics before the window for live baseline estimates. The
canonical metrics come from the Collector's spanmetrics connector:
`calls_total` and `duration_milliseconds_bucket`, with `service_name`,
`span_kind` and `status_code` labels. CPU, memory and restart queries use the
namespace and a pod-name prefix matching the service. See
[`src/telemetry_queries.py`](../src/telemetry_queries.py) for the exact queries.
Tempo uses the `service.name` resource attribute. For Loki, configure your
collector to index that attribute as `service_name`.

Pass one `--service` flag per candidate. Without flags the agent uses the
Astronomy Shop defaults. For other labels, sampling schemes or topology,
implement the [`DataSource` protocol](../src/datasources/protocol.py) and pass it
to `src.api.investigate`. The agent does not infer a dependency graph for an
arbitrary cluster. Provider requests contain selected telemetry evidence.
Review your organization's data handling rules before using live telemetry.

## Snapshot or Python

```bash
copilot investigate --snapshot snapshots/checkout-pod_crash-seed42
```

```python
from src.api import investigate_snapshot

report = investigate_snapshot("snapshots/checkout-pod_crash-seed42")
for cause in report.root_causes:
    print(cause.rank, cause.service, cause.fault_type)
```

Snapshot mode takes timestamps and namespace from `metadata.json`. It reads
recorded telemetry but it still calls the configured LLM. Use `make demo` to
play an already recorded investigation without an LLM.

## Local Compose

`make compose-up` starts the Collector, Prometheus, Loki and Tempo plus
sample logs and traces. Host endpoints are Prometheus at `127.0.0.1:19090`,
Loki at `127.0.0.1:13100`, Tempo at `127.0.0.1:13200` and OTLP on ports
`4317` and `4318`. The services listen on loopback. Sample traffic comes from
Telemetrygen, not from a Kubernetes API. Use `--service telemetrygen` to
inspect that telemetry and choose a window after startup. To run the packaged
CLI inside the stack, use `docker compose run --rm copilot investigate` with
the same live flags. `make compose-down` removes the local stack.

Use `make up` for the Astronomy Shop on kind, Kubernetes events and Chaos
Mesh fault injection. Compose does not simulate those components.
