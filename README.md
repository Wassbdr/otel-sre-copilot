# OTel SRE-Copilot

An LLM agent that investigates incidents in Kubernetes microservices instrumented with
OpenTelemetry. Given an incident time window, the agent queries metrics, traces, and logs,
then produces a ranked root-cause analysis with evidence and remediation steps.

**Core value: rigorous, reproducible evaluation — not just a demo.**

## Quick Start

```bash
git clone https://github.com/Wassbdr/otel-sre-copilot
cd otel-sre-copilot
cp .env.example .env          # fill in NIM_API_KEY
make setup                    # install Python deps + kind + helm
make up                       # spin up cluster (~5 min)
make health-check             # verify all backends healthy
make fault SCENARIO=scenarios/mvp/001-checkoutservice-pod-crash.yaml
make eval                     # run 7 MVP scenarios, produce results
make compare                  # agent vs 3 baselines
```

## Results (MVP — seed=42)

Evaluation in progress — harness and 7 scenarios are implemented, full benchmark run pending cluster setup.

Metrics tracked: Acc@1, Acc@3, MRR, FaultType accuracy, grounding score, latency, cost/run.
Baselines: Random, Z-score (error_rate), Composite Z-score.
Model: `meta/llama-3.1-70b-instruct`

## Architecture

```
kind cluster
  OTel Astronomy Shop (~15 services)
    → OTel Collector → Prometheus / Tempo / Loki
  Chaos Mesh (fault injection → ground truth)

Agent (LangGraph + NIM API)
  Tools: query_prometheus, search_traces, query_loki, get_pod_events, get_topology
  Output: InvestigationReport (ranked root causes + evidence + remediation)

Eval Harness
  ReplayDataSource (no live cluster needed)
  7 metrics · 3 baselines · anti-hallucination grounding check
```

## Reproducing Results

```bash
make eval-replay RUN_ID=<run_id_from_artifacts/>
```

All eval runs in `artifacts/` are bit-reproducible given the same `config.json`.

## Known Limitations

- Requires a NVIDIA NIM API key (`NIM_API_KEY`) — no OpenAI fallback yet
- Live mode needs a running kind cluster (~5 min setup via `make up`)
- Replay mode works offline with the bundled telemetry snapshots

## Project Structure

```
src/datasources/   DataSource Protocol + Live + Replay implementations
src/agent/         LangGraph agent (graph, tools, schemas, prompts)
eval/              Harness (metrics, grounding verifier, baselines, compare)
scenarios/mvp/     7 Chaos Mesh fault scenarios (YAML)
snapshots/         Telemetry snapshots (metadata + ground_truth versioned)
artifacts/         Pinned eval results (JSON, committed)
infra/             kind config, helm values, OTel Collector config
scripts/           inject_and_snapshot.py, snapshot_telemetry.py, health_check.py
```
