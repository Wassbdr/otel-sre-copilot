# Changelog

## 0.2.0

- Investigate a captured snapshot or live telemetry through the `copilot` CLI or Python API.
- Replay captured Prometheus, Loki and Tempo responses over HTTP.
- Rank request loss alongside error rates, latency and resource signals.
- Measure span self time separately from downstream waits.
- Rank service and fault pairs before the model runs, and fill unsupported report slots from the grounded prior.
- Compare the full agent, ReAct, no-prior, HolmesGPT and statistical baselines on matched snapshots.
- Resume matched benchmark runs by snapshot, repeat and method.
- Run the local telemetry backends and sample traffic through Docker Compose.

## 0.1.0

- Capture Astronomy Shop telemetry during Chaos Mesh faults and replay it offline.
- Score incident reports, check citations and compare statistical baselines.
