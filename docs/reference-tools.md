# Reference tools on recorded telemetry

The replay server exposes captured Prometheus range and instant queries, Loki
range queries and labels, and Tempo search and trace lookup on loopback. It does
not implement PromQL, LogQL or general TraceQL. Prometheus and Loki expressions
must match the queries in the snapshot. Time filters apply to stored samples.
Tempo supports unfiltered search or an exact root-service filter. Full span
payloads are available only for traces that were downloaded during capture.

## HolmesGPT 0.48.0

In an isolated Python 3.12 environment, install `holmesgpt==0.48.0`. Run the
server in the project environment:

```bash
python -m src.replay_server --snapshot snapshots/shipping-high_latency-seed42 --port 18080
```

The HolmesGPT Prometheus toolset connected, its Loki client retrieved one
stream, and its Tempo client fetched a five-batch trace. LiteLLM resolved the
model string `nvidia_nim/nvidia/nemotron-3.5-lightning-30b-a3b` to provider
`nvidia_nim` and the same benchmark model.

The connection checks did not invoke an LLM. To configure the reference, point
`holmes ask --config benchmarks/holmes-replay.yaml` at the sample window in
`metadata.json` and use `--model nvidia_nim/nvidia/nemotron-3.5-lightning-30b-a3b`.
LiteLLM uses `NVIDIA_NIM_API_KEY`. No live HolmesGPT investigation was attempted:
the current NIM budget is reserved for the three local variants, and the
standalone HolmesGPT CLI does not go through this project's limiter or cache.
No HolmesGPT accuracy score is available.

## k8sgpt v0.4.41

`k8sgpt analyze --kubeconfig /path/to/missing --filter Pod --output json`
failed at `initialising kubernetes client`. The
[pod analyzer](https://github.com/k8sgpt-ai/k8sgpt/blob/v0.4.41/pkg/analyzer/pod.go)
lists pods and events through the Kubernetes API. These snapshots contain event
records but do not reconstruct the resource state or serve a Kubernetes API.
A check against a live cluster would not use the same recorded inputs.

## Microsoft OpenRCA

The upstream [RCA-agent runner](https://github.com/microsoft/OpenRCA/blob/main/rca/run_agent_standard.py)
loads `dataset/<case>/query.csv` and `record.csv`, selects system-specific prompts
for Bank, Telecom or Market, and reads dated telemetry files. Our snapshots use
query response JSON and trace payloads. There is no direct input adapter.
A comparison would need a conversion of telemetry and incident questions, plus
a prompt and output adapter for the same service, fault type and evidence metrics.
No OpenRCA benchmark was run.
