# Reference tools on recorded telemetry

The replay server exposes captured Prometheus range and instant queries, Loki
range queries and labels, and Tempo search and trace lookup on loopback. It does
not implement PromQL, LogQL or general TraceQL. Prometheus and Loki expressions
must match the queries in the snapshot. Prometheus accepts either single or
double quotes around simple label values. Time filters apply to stored samples.
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

To score HolmesGPT with the other methods, point `HOLMES_PYTHON` at the
interpreter in the HolmesGPT environment, set `NIM_API_KEY` and run:

```bash
make bench BENCH_RUN_ID=round2-holmes BENCH_METHODS='agent react agent_no_prior holmes'
```

HolmesGPT uses the same NIM model and runs once per snapshot, in the first
repeat. Its Prometheus, Loki and Tempo tools use a fresh loopback replay
server. LiteLLM sends model requests through that server to the same cache
and adaptive limiter as the other benchmark methods. The standalone HolmesGPT
CLI does not use that limiter. The scorer checks citations against successful
replay queries and trace IDs, not against the model's account of its calls.

HolmesGPT has ten model steps. Its first model request with tools requires a
tool call; later steps can choose to stop. If it reaches the final step without
a diagnosis, that request has no tools and uses JSON output mode. The prompt
supplies snapshot timestamps, recorded service names, and query templates. Tool discovery and
readiness checks do not count as incident evidence. Successful replay calls
record their time parameters in the trace.

The scorer reads ranked pairs from the result JSON, including a JSON block in
prose. It does not infer a diagnosis from unlabeled prose. Service aliases such
as `checkoutservice` and `productcatalog` map to the telemetry names
`checkout` and `product-catalog` for all methods. HolmesGPT fault labels are
case and separator insensitive. Explicit aliases map pod kill and
CrashLoopBackOff to `pod_crash`, latency injection to `high_latency`, CPU
throttling to `cpu_stress`, OOMKilled to `memory_stress`, request abort to
`http_abort`, and network loss or dependency timeout to `dependency_failure`.
Other labels are scored as `unknown`. The results retain the original HolmesGPT
answer separately and distinguish a malformed answer from an empty diagnosis.

For a first pass on four development snapshots, add `BENCH_MAX_SNAPSHOTS=4`
and `BENCH_MAX_REPEATS=1`. Resume the full cohort with the same run ID and
without those limits. The table keeps the full expected sample size.

## ReAct and no-prior

ReAct has access to the full observation tool set, including request-rate
comparison and exclusive span timing, and can use up to ten tool rounds before
the report call. It receives no seeded hypotheses and has no in-agent grounding
filter or fallback. The no-prior ablation shares the full agent's short tool
budget and can see request-rate observations, but gets no candidate list or
fallback. The external scorer uses the same accuracy and citation checks for both.

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
